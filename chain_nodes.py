"""Disk-backed recursive clip chains specialized for MiniMax H3.

The visible graph contains one H3 sampling body.  Chain Start and Chain End
recursively clone that body with ComfyUI's GraphBuilder, carrying only the
previous clip's context tail and compact AV latent into the next iteration.
Each iteration is persisted before recursion, so a long chain can resume from
the first unfinished clip instead of starting over.

The recursive graph traversal is adapted from Ethanfel's SxCP loop nodes in
ComfyUI-Prompt-Builder, using the same ComfyUI expansion pattern with a single,
typed MiniMax chain state rather than arbitrary carry sockets.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import uuid
import wave
from fractions import Fraction
from typing import Any

import folder_paths

try:
    import av
except ImportError:  # ComfyUI normally ships PyAV.
    av = None

try:
    import torch
except ImportError:  # ComfyUI always ships torch; keeps local imports clear.
    torch = None

try:
    from safetensors.torch import load_file as _st_load, save_file as _st_save
except ImportError:
    _st_load = _st_save = None

try:
    from comfy_execution.graph_utils import GraphBuilder, ExecutionBlocker, is_link
except ImportError:
    GraphBuilder = None
    ExecutionBlocker = None

    def is_link(value):
        return isinstance(value, list) and len(value) == 2

try:
    from aiohttp import web
    from server import PromptServer
except ImportError:
    web = None
    PromptServer = None

from .nodes import MiniMaxH3MotionContext, _streams_from_latent


_LOG = logging.getLogger("h3_motion_context.chain")

FPS = 24
PLAN_VERSION = 2
MAX_SHOTS = 128
MAX_SEED = 0xFFFFFFFFFFFFFFFF
MAX_H3_FRAMES = 3592  # largest 17k+5 value accepted by H3's 3600-frame socket
H3_CONTEXT_LENGTHS = (1, 5, 22, 39)
AUDIO_MODES = ("source_track", "generated_audio", "source_plus_timeline")

PLAN_TYPE = "H3_CHAIN_PLAN"
STATE_TYPE = "H3_CHAIN_STATE"
FLOW_TYPE = "H3_CHAIN_FLOW"
SEGMENT_TYPE = "H3_CHAIN_SEGMENT"
MANIFEST_TYPE = "H3_CHAIN_MANIFEST"

_PENDING_REVIEWS: dict[str, dict[str, Any]] = {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_name(value: str, fallback: str = "chain") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    text = text.strip("._-")
    return (text or fallback)[:96]


def _prompt_text(value: Any, label: str) -> str:
    """Normalize a prompt string or a human-editable JSON array of lines."""
    if isinstance(value, list):
        if not all(isinstance(line, str) for line in value):
            raise ValueError("%s line arrays may contain only strings." % label)
        return "\n".join(value).strip()
    return str(value or "").strip()


def _h3_frame_length(seconds: float) -> int:
    """Round a duration up to H3's valid 17k+5 frame grid."""
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("H3 shot duration must be a finite positive number.")
    # Subtract a tiny tolerance so an exactly frame-aligned decimal does not
    # jump a frame because of binary floating-point representation.
    requested = max(5, int(math.ceil(seconds * FPS - 1e-9)))
    length = requested + (5 - requested % 17) % 17
    if length > MAX_H3_FRAMES:
        raise ValueError(
            "H3 shot duration %.6fs rounds to %d frames; the largest valid "
            "17k+5 length is %d frames (%.6fs)." %
            (seconds, length, MAX_H3_FRAMES, MAX_H3_FRAMES / float(FPS)))
    return length


def _validate_h3_length(length: Any, label: str) -> int:
    length = int(length)
    if length < 5 or length > MAX_H3_FRAMES or length % 17 != 5:
        raise ValueError(
            "%s must be an H3-valid frame length between 5 and %d "
            "with length %% 17 == 5; got %d." %
            (label, MAX_H3_FRAMES, length))
    return length


def _derived_seed(base_seed: int, index: int, shot_id: str) -> int:
    payload = "%d:%d:%s" % (int(base_seed), int(index), shot_id)
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8],
                          "big")


def _history_contract(plan: dict[str, Any], through_index: int) -> dict[str, Any]:
    shots = []
    for shot in plan["shots"][:int(through_index)]:
        shots.append({
            "id": shot["id"],
            "prompt_hash": shot["prompt_hash"],
            "seed": shot["seed"],
            "steps": shot["steps"],
            "raw_frames": shot["raw_frames"],
            "delivered_frames": shot["delivered_frames"],
            "generation_start_frame": shot["generation_start_frame"],
        })
    return {
        "version": PLAN_VERSION,
        "compatibility": plan["compatibility"],
        "shots": shots,
    }


def _history_hash(plan: dict[str, Any], through_index: int) -> str:
    return _fingerprint(_history_contract(plan, through_index))


def _audio_fingerprint(audio: dict[str, Any]) -> str:
    if torch is None:
        raise RuntimeError("Source-audio checkpoint validation requires torch.")
    waveform = audio["waveform"].detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(int(audio["sample_rate"])).encode("ascii"))
    digest.update(str(tuple(int(part) for part in waveform.shape)).encode("ascii"))
    digest.update(str(waveform.dtype).encode("ascii"))
    digest.update(memoryview(waveform.numpy()).cast("B"))
    return digest.hexdigest()


def _validate_audio(audio: dict[str, Any], label: str,
                    expected_frames: int | None = None) -> tuple[Any, int]:
    if torch is None:
        raise RuntimeError("H3 chain audio validation requires torch.")
    if not isinstance(audio, dict) or "waveform" not in audio:
        raise ValueError("%s must be a ComfyUI AUDIO value." % label)
    waveform = audio["waveform"]
    if not torch.is_tensor(waveform) or waveform.ndim not in (1, 2, 3):
        raise ValueError(
            "%s waveform must be a 1D, 2D, or 3D tensor; got %r." %
            (label, getattr(waveform, "shape", None)))
    sample_rate = int(audio.get("sample_rate", 0))
    if sample_rate <= 0:
        raise ValueError("%s sample rate must be positive." % label)
    samples = int(waveform.shape[-1])
    if samples < 1:
        raise ValueError("%s waveform is empty." % label)
    if expected_frames is not None:
        expected = int(round(int(expected_frames) / float(FPS) * sample_rate))
        if samples != expected:
            raise ValueError(
                "%s contains %d samples at %d Hz; expected exactly %d samples "
                "for %d delivered frames at %d fps. Wire decoded audio through "
                "H3 Motion Context Trim with match_tail enabled." %
                (label, samples, sample_rate, expected, int(expected_frames), FPS))
    return waveform, sample_rate


def _validate_source_audio_hash(compatibility: dict[str, Any],
                                source_audio: dict[str, Any] | None,
                                usage: str) -> None:
    if source_audio is None:
        raise ValueError("%s requires source_audio." % usage)
    _validate_audio(source_audio, "%s source audio" % usage)
    expected = str(compatibility.get("source_audio_hash") or "")
    if not expected or expected == "none":
        raise ValueError("%s has no source-audio fingerprint to validate." % usage)
    actual = _audio_fingerprint(source_audio)
    if actual != expected:
        raise ValueError(
            "%s received a different source waveform than H3 Chain Loop Start. "
            "Wire the same AUDIO value to Start, Current Shot, and Assemble." % usage)


def _plan_with_source_audio(plan: dict[str, Any],
                            source_audio: dict[str, Any] | None) -> dict[str, Any]:
    mode = plan["compatibility"]["audio_mode"]
    if mode in ("source_track", "source_plus_timeline"):
        if source_audio is None:
            raise ValueError("H3 chain audio mode %s requires source_audio on "
                             "Loop Start." % mode)
        waveform, sample_rate = _validate_audio(
            source_audio, "H3 Chain Loop Start source audio")
        required_samples = int(round(
            int(plan["total_delivered_frames"]) / float(FPS) * sample_rate))
        if int(waveform.shape[-1]) < required_samples:
            raise ValueError(
                "H3 Chain Loop Start source audio is too short: it contains %d "
                "samples at %d Hz, but this plan requires at least %d samples "
                "for %d delivered frames." %
                (int(waveform.shape[-1]), sample_rate, required_samples,
                 int(plan["total_delivered_frames"])))
        source_hash = _audio_fingerprint(source_audio)
    else:
        source_hash = "none"
    prepared = dict(plan)
    prepared["base_plan_hash"] = plan["plan_hash"]
    prepared["compatibility"] = dict(plan["compatibility"])
    prepared["compatibility"]["source_audio_hash"] = source_hash
    prepared["plan_hash"] = _fingerprint({
        "base_plan_hash": plan["plan_hash"],
        "source_audio_hash": source_hash,
    })
    return prepared


def _plan_with_review_revision(plan: dict[str, Any], index: int,
                               scene_prompt: str, seed: int) -> dict[str, Any]:
    """Revise the current scene while preserving the accepted history contract."""
    index = int(index)
    if index < 1 or index > len(plan["shots"]):
        raise ValueError("H3 review revision index is outside the plan.")
    scene_prompt = str(scene_prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not scene_prompt:
        raise ValueError("H3 review retry prompt cannot be empty.")
    seed = int(seed)
    if seed < 0 or seed > MAX_SEED:
        raise ValueError("H3 review retry seed is outside the uint64 range.")

    revised = dict(plan)
    revised["shots"] = [dict(shot) for shot in plan["shots"]]
    shot = revised["shots"][index - 1]
    prefix = str(revised.get("prompt_prefix") or "").strip()
    full_prompt = (prefix + "\n\n" + scene_prompt) if prefix else scene_prompt
    shot["scene_prompt"] = scene_prompt
    shot["prompt"] = full_prompt
    shot["prompt_hash"] = hashlib.sha256(
        full_prompt.encode("utf-8")).hexdigest()
    shot["seed"] = seed

    overrides = dict(revised.get("review_overrides") or {})
    overrides[str(index)] = {
        "scene_prompt": scene_prompt,
        "prompt_hash": shot["prompt_hash"],
        "seed": seed,
    }
    revised["review_overrides"] = overrides
    base_plan_hash = str(revised.get("base_plan_hash") or revised["plan_hash"])
    source_hash = str(
        revised.get("compatibility", {}).get("source_audio_hash") or "none")
    revised["plan_hash"] = _fingerprint({
        "base_plan_hash": base_plan_hash,
        "source_audio_hash": source_hash,
        "review_overrides": overrides,
    })
    return revised


def _normalize_plan(
    plan_json: str,
    run_name: str,
    width: int,
    height: int,
    context_length: int,
    encode_mode: str,
    anchor_mode: str,
    crop: str,
    audio_mode: str,
    audio_context_length: int,
    default_duration_seconds: float,
    default_steps: int,
    base_seed: int,
    segment_crf: int,
    generation_fingerprint: str = "",
) -> dict[str, Any]:
    try:
        raw = json.loads(str(plan_json or ""))
    except json.JSONDecodeError as exc:
        raise ValueError("H3 Chain Plan JSON is invalid: %s" % exc) from exc
    if isinstance(raw, list):
        raw = {"shots": raw}
    if not isinstance(raw, dict):
        raise ValueError("H3 Chain Plan must be a JSON object or a list of shots.")

    raw_shots = raw.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("H3 Chain Plan requires a non-empty 'shots' list.")
    if len(raw_shots) > MAX_SHOTS:
        raise ValueError("H3 Chain Plan supports at most %d shots." % MAX_SHOTS)

    width, height = int(width), int(height)
    if width < 32 or height < 32 or width % 32 or height % 32:
        raise ValueError("H3 chain width and height must be positive multiples of 32.")
    context_length = int(context_length)
    if context_length not in H3_CONTEXT_LENGTHS:
        raise ValueError("H3 context length must be one of %s." % (H3_CONTEXT_LENGTHS,))
    if encode_mode not in ("video", "frames"):
        raise ValueError("Unknown H3 context encode mode %r." % encode_mode)
    if anchor_mode not in ("head", "before"):
        raise ValueError("Unknown H3 context anchor mode %r." % anchor_mode)
    if crop not in ("disabled", "center"):
        raise ValueError("Unknown H3 context crop mode %r." % crop)
    if audio_mode not in AUDIO_MODES:
        raise ValueError("Unknown H3 chain audio mode %r." % audio_mode)
    default_steps = max(1, min(10000, int(default_steps)))
    base_seed = max(0, min(MAX_SEED, int(base_seed)))
    segment_crf = max(0, min(51, int(segment_crf)))

    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    default_duration = float(defaults.get(
        "duration_seconds", default_duration_seconds))
    default_steps = int(defaults.get("steps", default_steps))
    if not math.isfinite(default_duration) or default_duration <= 0:
        raise ValueError("Default shot duration must be a finite positive number.")
    if default_steps < 1:
        raise ValueError("Default sampler steps must be at least 1.")

    prompt_prefix = _prompt_text(
        raw.get("prompt_prefix", raw.get("global_prompt", "")),
        "H3 Chain prompt_prefix",
    )
    seen_ids: set[str] = set()
    shots: list[dict[str, Any]] = []
    stitched_frames = 0
    for offset, item in enumerate(raw_shots):
        index = offset + 1
        if isinstance(item, str):
            item = {"prompt": item}
        if not isinstance(item, dict):
            raise ValueError("Shot %d must be an object or prompt string." % index)

        shot_id = _safe_name(item.get("id", "clip_%04d" % index),
                             "clip_%04d" % index)
        if shot_id in seen_ids:
            raise ValueError("Duplicate H3 shot id %r." % shot_id)
        seen_ids.add(shot_id)

        prompt = _prompt_text(item.get("prompt", ""),
                              "Shot %d (%s) prompt" % (index, shot_id))
        if not prompt:
            raise ValueError("Shot %d (%s) has an empty prompt." % (index, shot_id))
        scene_prompt = prompt
        if prompt_prefix:
            prompt = prompt_prefix + "\n\n" + prompt

        explicit_length = item.get("length", item.get("frames"))
        if explicit_length is None:
            duration = float(item.get("duration_seconds", default_duration))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(
                    "Shot %d duration must be a finite positive number." % index)
            raw_frames = _h3_frame_length(duration)
        else:
            raw_frames = _validate_h3_length(explicit_length,
                                                   "Shot %d length" % index)

        if index == 1:
            generation_start_frame = 0
            delivered_frames = raw_frames
        else:
            if raw_frames <= context_length:
                raise ValueError(
                    "Shot %d has %d raw frames, not enough for a %d-frame "
                    "continuation overlap." % (index, raw_frames, context_length))
            if anchor_mode == "head":
                generation_start_frame = stitched_frames - context_length
                delivered_frames = raw_frames - context_length
            else:
                # `before` places context at negative coordinates, so no
                # repeated head is delivered or trimmed from the new clip.
                generation_start_frame = stitched_frames
                delivered_frames = raw_frames

        steps = int(item.get("steps", default_steps))
        if steps < 1 or steps > 10000:
            raise ValueError("Shot %d steps must be between 1 and 10000." % index)
        seed_value = item.get("seed")
        seed = (_derived_seed(base_seed, index, shot_id)
                if seed_value is None else int(seed_value))
        if seed < 0 or seed > MAX_SEED:
            raise ValueError("Shot %d seed is outside the uint64 range." % index)

        shot = {
            "index": index,
            "id": shot_id,
            # Kept separately so the review gate can edit only this scene
            # without duplicating the shared prompt prefix.
            "scene_prompt": scene_prompt,
            "prompt": prompt,
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "seed": seed,
            "steps": steps,
            "raw_frames": raw_frames,
            "delivered_frames": delivered_frames,
            "generation_start_frame": generation_start_frame,
            "audio_start_seconds": generation_start_frame / float(FPS),
            "audio_duration_seconds": raw_frames / float(FPS),
        }
        shots.append(shot)
        stitched_frames += delivered_frames

    for shot in shots[:-1]:
        if shot["delivered_frames"] < context_length:
            raise ValueError(
                "Shot %d (%s) delivers only %d frames, but the next clip "
                "requires %d context frames. Increase its length or reduce "
                "context_length." %
                (shot["index"], shot["id"], shot["delivered_frames"],
                 context_length))

    compatibility = {
        "fps": FPS,
        "width": width,
        "height": height,
        "context_length": context_length,
        "encode_mode": encode_mode,
        "anchor_mode": anchor_mode,
        "crop": crop,
        "audio_mode": audio_mode,
        "audio_context_length": max(0, int(audio_context_length)),
        "segment_crf": segment_crf,
        # Model, VAE, references, CFG, and scheduler live outside this node's
        # inputs. This caller-supplied tag lets a workflow make those external
        # generation dependencies part of the resume contract.
        "generation_fingerprint": str(generation_fingerprint or "").strip(),
    }
    plan = {
        "version": PLAN_VERSION,
        "run_name": _safe_name(run_name, "h3_chain"),
        "prompt_prefix": prompt_prefix,
        "shots": shots,
        "compatibility": compatibility,
        "segment_crf": segment_crf,
        "total_delivered_frames": stitched_frames,
    }
    plan["plan_hash"] = _fingerprint({
        "compatibility": compatibility,
        "shots": [{k: v for k, v in shot.items()
                   if k not in ("prompt", "scene_prompt")}
                  for shot in shots],
    })
    plan["summary"] = (
        "%d clips; %d delivered frames (%.3fs) at %dx%d; context=%d; "
        "audio=%s; run=%s" %
        (len(shots), stitched_frames, stitched_frames / float(FPS), width,
         height, context_length, audio_mode, plan["run_name"]))
    return plan


def _output_root() -> str:
    return os.path.abspath(folder_paths.get_output_directory())


def _run_dir(plan: dict[str, Any]) -> str:
    root = _output_root()
    path = os.path.abspath(os.path.join(root, "h3_chains", plan["run_name"]))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("H3 chain run path escapes the ComfyUI output directory.")
    return path


def _relative_output_path(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), _output_root())


def _absolute_output_path(path: str) -> str:
    if os.path.isabs(path):
        resolved = os.path.abspath(path)
    else:
        resolved = os.path.abspath(os.path.join(_output_root(), path))
    root = _output_root()
    if os.path.commonpath([root, resolved]) != root:
        raise ValueError("H3 chain artifact path escapes the output directory.")
    return resolved


def _artifact_paths(plan: dict[str, Any], index: int) -> dict[str, str]:
    run_dir = _run_dir(plan)
    return {
        "run_dir": run_dir,
        "segment": os.path.join(run_dir, "segments", "clip_%04d.mp4" % index),
        "checkpoint": os.path.join(run_dir, "checkpoints",
                                   "clip_%04d.safetensors" % index),
        "metadata": os.path.join(run_dir, "checkpoints", "clip_%04d.json" % index),
    }


def _versioned_path(path: str, transaction: str) -> str:
    stem, extension = os.path.splitext(path)
    return "%s.%s%s" % (stem, transaction, extension)


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _cleanup_previous_artifacts(plan: dict[str, Any], index: int,
                                previous_metadata: Any,
                                keep: set[str]) -> None:
    if not isinstance(previous_metadata, dict):
        return
    previous = previous_metadata.get("segment")
    if not isinstance(previous, dict):
        return
    canonical = _artifact_paths(plan, index)
    allowed = {
        "segment": os.path.dirname(canonical["segment"]),
        "checkpoint": os.path.dirname(canonical["checkpoint"]),
    }
    prefix = "clip_%04d" % index
    for key in ("segment", "checkpoint"):
        value = previous.get(key)
        if not isinstance(value, str):
            continue
        try:
            path = _absolute_output_path(value)
        except (ValueError, OSError):
            continue
        if (path in keep or os.path.dirname(path) != allowed[key] or
                not os.path.basename(path).startswith(prefix)):
            continue
        try:
            _safe_unlink(path)
        except OSError as exc:
            _LOG.warning("H3 Chain could not clean old %s artifact %s: %s",
                         key, path, exc)


def _atomic_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        _safe_unlink(temporary)


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _tensor_cpu_clone(value: Any) -> Any:
    if torch is not None and torch.is_tensor(value):
        return value.detach().cpu().contiguous().clone()
    return value


def _compact_latent(latent: dict[str, Any]) -> dict[str, Any]:
    parts = _streams_from_latent(latent)
    if len(parts) < 2:
        raise ValueError("H3 Chain requires a sampled MiniMax AV latent.")
    return {"samples": [_tensor_cpu_clone(parts[0]),
                        _tensor_cpu_clone(parts[1])]}


def _public_segment(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in (
        "index", "id", "segment", "checkpoint", "metadata",
        "raw_frames", "delivered_frames", "history_hash", "prompt_hash",
        "seed", "steps", "sample_rate", "segment_sha256",
        "checkpoint_sha256") if key in value}


def _verify_segment_artifacts(segment: dict[str, Any], index: int) -> None:
    if int(segment.get("index", -1)) != int(index):
        raise ValueError(
            "H3 chain metadata slot %d points to segment index %r." %
            (index, segment.get("index")))
    for key, hash_key in (("segment", "segment_sha256"),
                          ("checkpoint", "checkpoint_sha256")):
        value = segment.get(key)
        expected_hash = str(segment.get(hash_key) or "")
        if not isinstance(value, str) or not expected_hash:
            raise ValueError(
                "H3 chain clip %d metadata has no verified %s artifact." %
                (index, key))
        artifact = _absolute_output_path(value)
        if not os.path.isfile(artifact):
            raise FileNotFoundError(
                "H3 chain clip %d %s is missing: %s" %
                (index, key, artifact))
        actual_hash = _file_sha256(artifact)
        if actual_hash != expected_hash:
            raise ValueError(
                "H3 chain clip %d %s failed its SHA-256 integrity check." %
                (index, key))


def _load_resume_state(plan: dict[str, Any], start_clip: int) -> dict[str, Any]:
    if _st_load is None:
        raise RuntimeError("safetensors is required to resume H3 chains.")
    previous_index = start_clip - 1
    segments = []
    previous_meta = None
    for index in range(1, previous_index + 1):
        paths = _artifact_paths(plan, index)
        if not os.path.isfile(paths["metadata"]):
            raise FileNotFoundError(
                "Cannot resume clip %d: metadata for predecessor clip %d is "
                "missing: %s" % (start_clip, index, paths["metadata"]))
        metadata = _read_json(paths["metadata"])
        expected = _history_hash(plan, index)
        if metadata.get("history_hash") != expected:
            raise ValueError(
                "Cannot resume clip %d: clip %d was generated from different "
                "settings, prompts, seeds, or durations." % (start_clip, index))
        segment = metadata.get("segment")
        if not isinstance(segment, dict):
            raise ValueError("Checkpoint metadata for clip %d has no segment." % index)
        if segment.get("history_hash") != expected:
            raise ValueError(
                "Checkpoint segment record for clip %d has a mismatched history."
                % index)
        _verify_segment_artifacts(segment, index)
        segments.append(_public_segment(segment))
        previous_meta = metadata

    if previous_meta is None:
        raise RuntimeError("Internal resume error: predecessor metadata unavailable.")
    checkpoint = _absolute_output_path(previous_meta["segment"]["checkpoint"])
    tensors = _st_load(checkpoint)
    required = {"context_frames", "video", "audio"}
    missing = sorted(required - set(tensors))
    if missing:
        raise ValueError("H3 chain checkpoint is missing tensors: %s" % missing)
    expected_context = min(
        int(plan["compatibility"]["context_length"]),
        int(plan["shots"][previous_index - 1]["delivered_frames"]))
    if int(tensors["context_frames"].shape[0]) != expected_context:
        raise ValueError(
            "H3 chain predecessor checkpoint contains %d context frames; "
            "expected %d." %
            (int(tensors["context_frames"].shape[0]), expected_context))
    return {
        "plan": plan,
        "index": start_clip,
        "previous_frames": tensors["context_frames"],
        "previous_latent": {"samples": [tensors["video"], tensors["audio"]]},
        "segments": segments,
        "resumed_from": previous_index,
    }


def _initial_state(plan: dict[str, Any], start_clip: int) -> dict[str, Any]:
    total = len(plan["shots"])
    start_clip = int(start_clip)
    if start_clip < 1 or start_clip > total:
        raise ValueError("start_clip must be between 1 and %d." % total)
    if start_clip > 1:
        return _load_resume_state(plan, start_clip)
    return {
        "plan": plan,
        "index": 1,
        "previous_frames": None,
        "previous_latent": None,
        "segments": [],
        "resumed_from": 0,
    }


def _slice_audio(audio: dict[str, Any], start_seconds: float,
                 duration_seconds: float) -> dict[str, Any]:
    waveform, sample_rate = _validate_audio(audio, "H3 source audio")
    total = int(waveform.shape[-1])
    start = max(0, int(round(float(start_seconds) * sample_rate)))
    end = max(start + 1, int(round(
        (float(start_seconds) + float(duration_seconds)) * sample_rate)))
    wanted = end - start
    if start >= total:
        raise ValueError(
            "H3 source audio ends at %.3fs, before this clip's %.3fs start." %
            (total / float(sample_rate), start_seconds))
    if end > total:
        raise ValueError(
            "H3 source audio is too short for this chain: clip window "
            "%.3f..%.3fs requires %d samples, but the waveform ends at %.3fs. "
            "Short audio would truncate the final video." %
            (start_seconds, start_seconds + duration_seconds, wanted,
             total / float(sample_rate)))
    return {"waveform": waveform[..., start:end], "sample_rate": sample_rate}


def _write_segment_video(images: Any, path: str, fps: int, crf: int) -> None:
    if av is None or torch is None:
        raise RuntimeError("H3 segment saving requires PyAV and torch.")
    if len(images.shape) != 4 or int(images.shape[0]) < 1:
        raise ValueError("H3 segment images must be [frames,height,width,channels].")
    height, width = int(images.shape[1]), int(images.shape[2])
    if width % 2 or height % 2:
        raise ValueError("H.264 segment dimensions must be even.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path[:-4] + ".tmp.mp4"
    if os.path.exists(temporary):
        os.unlink(temporary)
    container = None
    try:
        container = av.open(temporary, mode="w")
        stream = container.add_stream("libx264", rate=Fraction(int(fps), 1))
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": str(int(crf)), "preset": "medium"}
        for image in images:
            array = (torch.clamp(image[..., :3] * 255.0, 0, 255)
                     .to(device="cpu", dtype=torch.uint8).numpy())
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        container = None
        os.replace(temporary, path)
    except Exception:
        if container is not None:
            container.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _write_wav(audio: dict[str, Any], path: str) -> None:
    if torch is None:
        raise RuntimeError("H3 chain audio assembly requires torch.")
    waveform = audio["waveform"]
    if len(waveform.shape) == 3:
        waveform = waveform[0]
    elif len(waveform.shape) == 1:
        waveform = waveform.unsqueeze(0)
    if len(waveform.shape) != 2:
        raise ValueError("H3 chain audio must be [batch,channels,samples].")
    pcm = (torch.clamp(waveform, -1.0, 1.0).movedim(0, 1) * 32767.0)
    pcm = pcm.round().to(device="cpu", dtype=torch.int16).contiguous().numpy()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(int(pcm.shape[1]))
        handle.setsampwidth(2)
        handle.setframerate(int(audio["sample_rate"]))
        handle.writeframes(pcm.tobytes())


class MiniMaxH3ChainPlan:
    @classmethod
    def INPUT_TYPES(cls):
        sample = json.dumps({
            "shots": [
                {"id": "intro", "prompt": "Describe the opening shot."},
                {"id": "continuation", "prompt": "Continue the same take."},
            ]
        }, indent=2)
        return {
            "required": {
                "plan_json": ("STRING", {"default": sample, "multiline": True,
                                           "dynamicPrompts": False}),
                "run_name": ("STRING", {"default": "h3_chain"}),
                "generation_fingerprint": ("STRING", {
                    "default": "",
                    "tooltip": "Change this tag whenever the model, VAE, global "
                               "references, CFG, scheduler, or other external "
                               "generation settings change. It is enforced when "
                               "resuming checkpoints."}),
                "width": ("INT", {"default": 960, "min": 32, "max": 4096,
                                    "step": 32}),
                "height": ("INT", {"default": 544, "min": 32, "max": 4096,
                                     "step": 32}),
                "context_length": (list(H3_CONTEXT_LENGTHS), {"default": 22}),
                "encode_mode": (["video", "frames"], {"default": "video"}),
                "anchor_mode": (["head", "before"], {"default": "head"}),
                "crop": (["disabled", "center"], {"default": "disabled"}),
                "audio_mode": (list(AUDIO_MODES), {"default": "source_track"}),
                "audio_context_length": ("INT", {"default": 22, "min": 0,
                                                    "max": 240}),
                "default_duration_seconds": ("FLOAT", {"default": 15.0,
                                                         "min": 0.1,
                                                         "max": MAX_H3_FRAMES / FPS,
                                                         "step": 0.01}),
                "default_steps": ("INT", {"default": 20, "min": 1,
                                            "max": 10000}),
                "base_seed": ("INT", {"default": 0, "min": 0,
                                        "max": MAX_SEED}),
                "segment_crf": ("INT", {"default": 18, "min": 0,
                                          "max": 51}),
            }
        }

    RETURN_TYPES = (PLAN_TYPE, "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("plan", "summary", "clip_count", "width", "height")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Parse and validate a frame-exact MiniMax H3 shot plan. "
                   "The plan computes valid lengths, overlaps, audio windows, "
                   "seeds, and checkpoint compatibility hashes.")

    def build(self, plan_json, run_name, generation_fingerprint, width, height,
              context_length,
              encode_mode, anchor_mode, crop, audio_mode,
              audio_context_length, default_duration_seconds, default_steps,
              base_seed, segment_crf):
        plan = _normalize_plan(
            plan_json, run_name, width, height, context_length, encode_mode,
            anchor_mode, crop, audio_mode, audio_context_length,
            default_duration_seconds, default_steps, base_seed, segment_crf,
            generation_fingerprint)
        return (plan, plan["summary"], len(plan["shots"]),
                plan["compatibility"]["width"],
                plan["compatibility"]["height"])


class MiniMaxH3ChainLoopStart:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE,),
                "start_clip": ("INT", {"default": 1, "min": 1,
                                         "max": MAX_SHOTS}),
            },
            "optional": {
                "source_audio": ("AUDIO",),
            },
            "hidden": {
                "initial_state": (STATE_TYPE,),
            },
        }

    RETURN_TYPES = (FLOW_TYPE, STATE_TYPE, "STRING")
    RETURN_NAMES = ("flow", "state", "status")
    FUNCTION = "start"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Start or resume a sequential H3 chain. start_clip > 1 "
                   "loads and validates the preceding segment checkpoint.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def start(self, plan, start_clip, source_audio=None, initial_state=None):
        if initial_state is None:
            prepared_plan = _plan_with_source_audio(plan, source_audio)
            state = _initial_state(prepared_plan, start_clip)
        else:
            state = dict(initial_state)
            prepared_plan = state["plan"]
            if prepared_plan.get("base_plan_hash") != plan.get("plan_hash"):
                raise ValueError("H3 chain plan changed during recursive execution.")
            state["plan"] = prepared_plan
        status = "clip %d/%d" % (state["index"],
                                  len(prepared_plan["shots"]))
        if state.get("resumed_from"):
            status += "; resumed from clip %d" % state["resumed_from"]
        return ("h3_chain", state, status)


class MiniMaxH3ChainCurrent:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE,),
            },
            "optional": {
                "source_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = (STATE_TYPE, "INT", "INT", "STRING", "STRING", "INT",
                    "INT", "INT", "INT", "INT", "FLOAT", "FLOAT",
                    "AUDIO", "STRING")
    RETURN_NAMES = ("state", "clip_index", "clip_count", "shot_id", "prompt",
                    "noise_seed", "length", "steps", "width", "height",
                    "audio_start", "audio_duration", "source_audio_slice",
                    "status")
    FUNCTION = "current"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Expose the current shot's prompt, seed, dimensions, valid "
                   "length, steps, and frame-exact source-audio window.")

    def current(self, state, source_audio=None):
        plan = state["plan"]
        index = int(state["index"])
        shot = plan["shots"][index - 1]
        mode = plan["compatibility"]["audio_mode"]
        audio_slice = None
        if mode in ("source_track", "source_plus_timeline"):
            _validate_source_audio_hash(
                plan["compatibility"], source_audio, "H3 Chain Current Shot")
            audio_slice = _slice_audio(
                source_audio, shot["audio_start_seconds"],
                shot["audio_duration_seconds"])
        status = ("clip %d/%d %s; raw=%df delivered=%df; song %.3f..%.3fs; "
                  "seed=%d" %
                  (index, len(plan["shots"]), shot["id"], shot["raw_frames"],
                   shot["delivered_frames"], shot["audio_start_seconds"],
                   shot["audio_start_seconds"] + shot["audio_duration_seconds"],
                   shot["seed"]))
        cfg = plan["compatibility"]
        return (state, index, len(plan["shots"]), shot["id"], shot["prompt"],
                shot["seed"], shot["raw_frames"], shot["steps"], cfg["width"],
                cfg["height"], shot["audio_start_seconds"],
                shot["audio_duration_seconds"], audio_slice, status)


class MiniMaxH3ChainContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE,),
                "conditioning": ("CONDITIONING",),
                "vae": ("VAE",),
                "latent": ("LATENT",),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "INT", "BOOLEAN")
    RETURN_NAMES = ("conditioning", "trim_frames", "is_continuation")
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Pass clip 1 through unchanged; apply H3 Motion Context "
                   "automatically to every continuation using loop state.")

    def apply(self, state, conditioning, vae, latent):
        index = int(state["index"])
        if index == 1:
            return (conditioning, 0, False)
        previous_frames = state.get("previous_frames")
        if previous_frames is None:
            raise ValueError("H3 chain continuation has no previous frame checkpoint.")
        plan = state["plan"]
        cfg = plan["compatibility"]
        use_latent_audio = cfg["audio_mode"] in (
            "generated_audio", "source_plus_timeline")
        previous_latent = state.get("previous_latent") if use_latent_audio else None
        if use_latent_audio and previous_latent is None:
            raise ValueError("H3 chain continuation has no previous AV latent.")
        out, trim = MiniMaxH3MotionContext().apply(
            conditioning=conditioning,
            vae=vae,
            latent=latent,
            context_frames=previous_frames,
            context_length=cfg["context_length"],
            encode_mode=cfg["encode_mode"],
            anchor_mode=cfg["anchor_mode"],
            crop=cfg["crop"],
            audio_context_length=cfg["audio_context_length"],
            audio_mode="timeline",
            context_latent=previous_latent,
        )
        return (out, trim, True)


class MiniMaxH3ChainSegmentSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE,),
                "images": ("IMAGE",),
                "sampled_latent": ("LATENT",),
            },
            "optional": {
                "audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = (SEGMENT_TYPE, "STRING")
    RETURN_NAMES = ("segment", "status")
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Immediately save one delivered H3 clip as an H.264 segment "
                   "plus a safetensors resume checkpoint.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def save(self, state, images, sampled_latent, audio=None):
        if _st_save is None:
            raise RuntimeError("safetensors is required for H3 chain checkpoints.")
        plan = state["plan"]
        index = int(state["index"])
        shot = plan["shots"][index - 1]
        actual_frames = int(images.shape[0])
        expected_frames = int(shot["delivered_frames"])
        if actual_frames != expected_frames:
            raise ValueError(
                "H3 chain clip %d produced %d delivered frames; expected %d. "
                "Wire decoded images through H3 Motion Context Trim before "
                "Segment Save." % (index, actual_frames, expected_frames))

        mode = plan["compatibility"]["audio_mode"]
        if mode == "generated_audio" and audio is None:
            raise ValueError(
                "H3 chain generated_audio mode requires decoded audio on Segment "
                "Save. Wire it through H3 Motion Context Trim first.")
        compact = _compact_latent(sampled_latent)
        context_length = int(plan["compatibility"]["context_length"])
        context_frames = _tensor_cpu_clone(images[-context_length:])
        parts = compact["samples"]
        tensors = {
            "context_frames": context_frames,
            "video": parts[0],
            "audio": parts[1],
        }
        sample_rate = 0
        if audio is not None:
            waveform, sample_rate = _validate_audio(
                audio, "H3 chain clip %d delivered audio" % index,
                expected_frames=expected_frames)
            tensors["delivered_audio"] = _tensor_cpu_clone(waveform)

        paths = _artifact_paths(plan, index)
        os.makedirs(os.path.dirname(paths["segment"]), exist_ok=True)
        os.makedirs(os.path.dirname(paths["checkpoint"]), exist_ok=True)
        previous_metadata = None
        if os.path.isfile(paths["metadata"]):
            try:
                previous_metadata = _read_json(paths["metadata"])
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _LOG.warning("H3 Chain is replacing unreadable clip %d metadata: %s",
                             index, exc)

        transaction = uuid.uuid4().hex
        published_segment = _versioned_path(paths["segment"], transaction)
        published_checkpoint = _versioned_path(paths["checkpoint"], transaction)
        checkpoint_tmp = "%s.%s.tmp" % (published_checkpoint, uuid.uuid4().hex)
        committed = False
        try:
            _write_segment_video(
                images, published_segment, FPS, plan["segment_crf"])
            _st_save(tensors, checkpoint_tmp, metadata={
                "format": "h3_chain_checkpoint_v2",
                "index": str(index),
                "history_hash": _history_hash(plan, index),
                "sample_rate": str(sample_rate),
            })
            os.replace(checkpoint_tmp, published_checkpoint)

            segment = {
                "index": index,
                "id": shot["id"],
                "segment": _relative_output_path(published_segment),
                "checkpoint": _relative_output_path(published_checkpoint),
                "metadata": _relative_output_path(paths["metadata"]),
                "raw_frames": shot["raw_frames"],
                "delivered_frames": shot["delivered_frames"],
                "history_hash": _history_hash(plan, index),
                "prompt_hash": shot["prompt_hash"],
                "seed": shot["seed"],
                "steps": shot["steps"],
                "sample_rate": sample_rate,
                "segment_sha256": _file_sha256(published_segment),
                "checkpoint_sha256": _file_sha256(published_checkpoint),
            }
            metadata = {
                "format": "h3_chain_segment_v2",
                "run_name": plan["run_name"],
                "plan_hash": plan["plan_hash"],
                "history_hash": segment["history_hash"],
                "compatibility": plan["compatibility"],
                "segment": segment,
            }
            # This metadata replacement is the transaction's commit point. Until
            # it succeeds, resume keeps referencing the previous immutable pair.
            _atomic_json(paths["metadata"], metadata)
            committed = True
        finally:
            _safe_unlink(checkpoint_tmp)
            if not committed:
                _safe_unlink(published_segment)
                _safe_unlink(published_checkpoint)

        _cleanup_previous_artifacts(
            plan, index, previous_metadata,
            {published_segment, published_checkpoint})
        status = ("saved clip %d/%d: %s + checkpoint %s" %
                  (index, len(plan["shots"]), published_segment,
                   published_checkpoint))
        _LOG.info("H3 Chain %s", status)
        return {"ui": {"text": [status]}, "result": (segment, status)}


def _review_video(plan: dict[str, Any], segment: dict[str, Any],
                  audio: dict[str, Any] | None) -> tuple[dict[str, str], bool, str]:
    source = _absolute_output_path(segment["segment"])
    relative_source = _relative_output_path(source)
    if audio is None:
        return ({
            "filename": os.path.basename(relative_source),
            "subfolder": os.path.dirname(relative_source),
            "type": "output",
        }, False, "No audio is connected; this review is silent.")

    expected_frames = int(segment["delivered_frames"])
    waveform, sample_rate = _validate_audio(
        audio, "H3 Chain Review audio", expected_frames=expected_frames)
    audio_value = {"waveform": waveform, "sample_rate": sample_rate}
    audio_hash = _audio_fingerprint(audio_value)
    video_hash = str(segment.get("segment_sha256") or _file_sha256(source))
    index = int(segment["index"])
    review_dir = os.path.join(_run_dir(plan), "reviews")
    os.makedirs(review_dir, exist_ok=True)
    name = "clip_%04d.%s.%s.review.mp4" % (
        index, video_hash[:12], audio_hash[:12])
    review_path = os.path.join(review_dir, name)

    if not os.path.isfile(review_path):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for H3 Chain Review audio playback.")
        transaction = uuid.uuid4().hex
        wav_tmp = os.path.join(review_dir, ".review.%s.wav" % transaction)
        video_tmp = os.path.join(review_dir, ".review.%s.mp4" % transaction)
        try:
            _write_wav(audio_value, wav_tmp)
            _run_ffmpeg([
                ffmpeg, "-y", "-i", source, "-i", wav_tmp,
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-t", "%.9f" % (expected_frames / float(FPS)),
                "-movflags", "+faststart", video_tmp,
            ])
            os.replace(video_tmp, review_path)
        finally:
            _safe_unlink(wav_tmp)
            _safe_unlink(video_tmp)

        prefix = "clip_%04d." % index
        for filename in os.listdir(review_dir):
            if (filename != name and filename.startswith(prefix) and
                    filename.endswith(".review.mp4")):
                _safe_unlink(os.path.join(review_dir, filename))

    relative = _relative_output_path(review_path)
    return ({
        "filename": os.path.basename(relative),
        "subfolder": os.path.dirname(relative),
        "type": "output",
    }, True, "")


def _review_display_id(unique_id: Any, dynprompt: Any) -> str:
    execution_id = str(unique_id)
    if dynprompt is not None:
        try:
            return str(dynprompt.get_display_node_id(execution_id))
        except Exception:
            pass
    return execution_id


class MiniMaxH3ChainReview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": (STATE_TYPE,),
                "segment": (SEGMENT_TYPE,),
                "enabled": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Pause after every saved segment for approval."}),
                "unload_models_while_waiting": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Release model weights from VRAM while waiting; "
                               "the next retry/segment reloads them."}),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "tooltip": "Wire frame-exact delivered audio from H3 "
                               "Motion Context Trim for synchronized review."}),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = (SEGMENT_TYPE, "STRING")
    RETURN_NAMES = ("segment", "status")
    FUNCTION = "review"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Pause after a checkpointed H3 segment for synchronized "
                   "video/audio review. Approve, stop, retry an edited scene "
                   "prompt, or reroll its seed from the node UI.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    async def review(self, state, segment, enabled,
                     unload_models_while_waiting, audio=None,
                     dynprompt=None, unique_id=None):
        plan = state["plan"]
        index = int(state["index"])
        if int(segment.get("index", -1)) != index:
            raise ValueError(
                "H3 Chain Review received the wrong segment for clip %d." % index)
        if not enabled:
            status = "review bypassed for clip %d" % index
            return {"ui": {"text": [status]}, "result": (segment, status)}
        if PromptServer is None or web is None:
            raise RuntimeError("H3 Chain Review requires ComfyUI's prompt server.")

        # Keep tensor-to-WAV conversion on Comfy's execution thread. Some
        # PyTorch builds can deadlock when their CPU tensor pools are first
        # entered from asyncio.to_thread; the short ffmpeg stream-copy is a
        # predictable boundary before the actual asynchronous wait begins.
        video, has_audio, warning = _review_video(plan, segment, audio)
        shot = plan["shots"][index - 1]
        token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        payload = {
            "token": token,
            "node_id": _review_display_id(unique_id, dynprompt),
            "execution_id": str(unique_id),
            "clip_index": index,
            "clip_count": len(plan["shots"]),
            "shot_id": shot["id"],
            "scene_prompt": shot.get("scene_prompt", shot["prompt"]),
            "prompt_prefix": str(plan.get("prompt_prefix") or ""),
            "seed": str(shot["seed"]),
            "video": video,
            "has_audio": has_audio,
            "warning": warning,
        }
        _PENDING_REVIEWS[token] = {
            "future": future,
            "public": payload,
            "current_seed": int(shot["seed"]),
        }
        PromptServer.instance.send_sync(
            "h3_chain_review", payload, PromptServer.instance.client_id)

        if unload_models_while_waiting:
            try:
                import comfy.model_management as model_management
                model_management.unload_all_models()
                model_management.soft_empty_cache()
            except Exception as exc:
                _LOG.warning("H3 Chain Review could not unload models: %s", exc)

        try:
            decision = await future
        finally:
            _PENDING_REVIEWS.pop(token, None)

        action = decision["action"]
        if action == "approve":
            status = "approved clip %d/%d; continuing" % (
                index, len(plan["shots"]))
            return {"ui": {"text": [status]}, "result": (segment, status)}
        if action == "stop":
            if ExecutionBlocker is None:
                raise RuntimeError("This ComfyUI build does not support review blocking.")
            status = "approved clip %d and stopped at its checkpoint" % index
            return {
                "ui": {"text": [status]},
                "result": (ExecutionBlocker(None), status),
            }
        if action != "retry":
            raise RuntimeError("Unknown H3 review decision %r." % action)

        revised_segment = dict(segment)
        revised_segment["_h3_review_decision"] = {
            "action": "retry",
            "scene_prompt": decision["scene_prompt"],
            "seed": int(decision["seed"]),
        }
        status = "retrying clip %d with seed %d" % (
            index, int(decision["seed"]))
        return {"ui": {"text": [status]},
                "result": (revised_segment, status)}


def _manifest_from_state(state: dict[str, Any]) -> dict[str, Any]:
    plan = state["plan"]
    segments = [_public_segment(item) for item in state["segments"]]
    expected_count = len(plan["shots"])
    if len(segments) != expected_count:
        raise ValueError(
            "H3 chain manifest is incomplete: found %d persisted clips, expected %d."
            % (len(segments), expected_count))
    indexes = [int(item.get("index", -1)) for item in segments]
    if indexes != list(range(1, expected_count + 1)):
        raise ValueError("H3 chain manifest segment indexes are not contiguous.")
    return {
        "format": "h3_chain_manifest_v2",
        "run_name": plan["run_name"],
        "plan_hash": plan["plan_hash"],
        "compatibility": plan["compatibility"],
        "clip_count": expected_count,
        "total_delivered_frames": plan["total_delivered_frames"],
        "duration_seconds": plan["total_delivered_frames"] / float(FPS),
        "segments": segments,
    }


def _manifest_path(plan: dict[str, Any]) -> str:
    return os.path.join(_run_dir(plan), "manifest.json")


class MiniMaxH3ChainLoopEnd:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flow": (FLOW_TYPE, {"rawLink": True}),
                "state": (STATE_TYPE,),
                "images": ("IMAGE",),
                "sampled_latent": ("LATENT",),
                "segment": (SEGMENT_TYPE,),
            },
            "hidden": {
                "dynprompt": "DYNPROMPT",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = (MANIFEST_TYPE, "STRING", "IMAGE", "LATENT")
    RETURN_NAMES = ("manifest", "manifest_json", "last_context_frames",
                    "last_context_latent")
    FUNCTION = "end"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Finish one persisted clip, carry only its context tail and "
                   "AV latent, then recursively execute the next shot.")

    def _explore_dependencies(self, node_id: str, dynprompt: Any,
                              upstream: dict[str, list[str]],
                              parent_ids: list[str]) -> None:
        node_info = dynprompt.get_node(node_id)
        for value in node_info.get("inputs", {}).values():
            if not is_link(value):
                continue
            parent_id = value[0]
            display_id = dynprompt.get_display_node_id(parent_id)
            display_node = dynprompt.get_node(display_id)
            if display_node["class_type"] != "MiniMaxH3ChainLoopEnd":
                parent_ids.append(display_id)
            if parent_id not in upstream:
                upstream[parent_id] = []
                self._explore_dependencies(parent_id, dynprompt, upstream,
                                           parent_ids)
            upstream[parent_id].append(node_id)

    def _explore_output_nodes(self, dynprompt: Any,
                              upstream: dict[str, list[str]],
                              parent_ids: list[str]) -> None:
        try:
            import nodes as comfy_nodes
            mappings = comfy_nodes.NODE_CLASS_MAPPINGS
        except Exception:
            return
        output_nodes: dict[str, Any] = {}
        for node_id, node in dynprompt.get_original_prompt().items():
            class_def = mappings.get(node.get("class_type"))
            if not class_def or not getattr(class_def, "OUTPUT_NODE", False):
                continue
            for value in node.get("inputs", {}).values():
                if is_link(value):
                    output_nodes[node_id] = value
        for parent_id in list(upstream):
            display_id = dynprompt.get_display_node_id(parent_id)
            for output_id, link in output_nodes.items():
                linked_id = link[0]
                if (linked_id in parent_ids and display_id == linked_id and
                        output_id not in upstream[parent_id]):
                    if "." in parent_id:
                        parts = parent_id.split(".")
                        parts[-1] = output_id
                        upstream[parent_id].append(".".join(parts))
                    else:
                        upstream[parent_id].append(output_id)

    def _collect_contained(self, node_id: str,
                           upstream: dict[str, list[str]],
                           contained: dict[str, bool]) -> None:
        for child_id in upstream.get(node_id, []):
            if child_id in contained:
                continue
            contained[child_id] = True
            self._collect_contained(child_id, upstream, contained)

    def _recurse(self, flow, next_state, dynprompt, unique_id):
        if GraphBuilder is None:
            raise RuntimeError("H3 Chain Loop requires ComfyUI GraphBuilder.")
        unique_id = str(unique_id)
        upstream: dict[str, list[str]] = {}
        parent_ids: list[str] = []
        self._explore_dependencies(unique_id, dynprompt, upstream, parent_ids)
        parent_ids = list(set(parent_ids))
        self._explore_output_nodes(dynprompt, upstream, parent_ids)

        open_node = str(flow[0])
        start_info = dynprompt.get_node(open_node)
        if start_info["class_type"] != "MiniMaxH3ChainLoopStart":
            raise ValueError("H3 Chain Loop End must receive flow from H3 Chain Loop Start.")
        contained: dict[str, bool] = {unique_id: True, open_node: True}
        self._collect_contained(open_node, upstream, contained)

        graph = GraphBuilder()
        for node_id in contained:
            original = dynprompt.get_node(node_id)
            clone_id = "Recurse" if node_id == unique_id else node_id
            node = graph.node(original["class_type"], clone_id)
            node.set_override_display_id(node_id)
        for node_id in contained:
            original = dynprompt.get_node(node_id)
            clone_id = "Recurse" if node_id == unique_id else node_id
            node = graph.lookup_node(clone_id)
            for key, value in original.get("inputs", {}).items():
                if is_link(value) and value[0] in contained:
                    parent = graph.lookup_node(value[0])
                    node.set_input(key, parent.out(value[1]))
                else:
                    node.set_input(key, value)
        graph.lookup_node(open_node).set_input("initial_state", next_state)
        recurse = graph.lookup_node("Recurse")
        return {
            "result": tuple(recurse.out(index)
                            for index in range(len(self.RETURN_TYPES))),
            "expand": graph.finalize(),
        }

    def end(self, flow, state, images, sampled_latent, segment,
            dynprompt=None, unique_id=None):
        plan = state["plan"]
        index = int(state["index"])
        if int(segment.get("index", -1)) != index:
            raise ValueError("H3 Chain End received the wrong segment for clip %d."
                             % index)
        review = segment.get("_h3_review_decision")
        if isinstance(review, dict) and review.get("action") == "retry":
            revised_plan = _plan_with_review_revision(
                plan, index, review.get("scene_prompt", ""),
                int(review.get("seed", plan["shots"][index - 1]["seed"])))
            retry_state = dict(state)
            retry_state["plan"] = revised_plan
            # Keep the predecessor context and accepted segment list unchanged;
            # the just-saved rejected artifact is transactionally replaced by
            # Segment Save when this same index completes again.
            return self._recurse(flow, retry_state, dynprompt, unique_id)
        context_length = int(plan["compatibility"]["context_length"])
        next_state = {
            "plan": plan,
            "index": index + 1,
            # clone: a tensor view would retain the entire decoded clip
            "previous_frames": _tensor_cpu_clone(images[-context_length:]),
            "previous_latent": _compact_latent(sampled_latent),
            "segments": list(state.get("segments", [])) +
                        [_public_segment(segment)],
            "resumed_from": state.get("resumed_from", 0),
        }
        if index < len(plan["shots"]):
            return self._recurse(flow, next_state, dynprompt, unique_id)

        manifest = _manifest_from_state(next_state)
        # A normal chain has already created its run directory in Segment Save.
        # Keeping this conditional also permits lightweight/custom segment sinks
        # that deliberately do not use the disk-backed saver.
        if os.path.isdir(_run_dir(plan)):
            _atomic_json(_manifest_path(plan), manifest)
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2,
                                   sort_keys=True)
        return (manifest, manifest_json, next_state["previous_frames"],
                next_state["previous_latent"])


class MiniMaxH3ChainManifestLoad:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (PLAN_TYPE,),
            },
            "optional": {
                "source_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = (MANIFEST_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("manifest", "manifest_json", "status")
    FUNCTION = "load"
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Validate every saved clip and rebuild a completed chain "
                   "manifest without rerendering the final clip.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def load(self, plan, source_audio=None):
        prepared_plan = _plan_with_source_audio(plan, source_audio)
        completed = _load_resume_state(
            prepared_plan, len(prepared_plan["shots"]) + 1)
        manifest = _manifest_from_state(completed)
        _atomic_json(_manifest_path(prepared_plan), manifest)
        manifest_json = json.dumps(
            manifest, ensure_ascii=False, indent=2, sort_keys=True)
        status = "loaded and verified %d saved clips from %s" % (
            len(manifest["segments"]), _run_dir(prepared_plan))
        return (manifest, manifest_json, status)


def _generated_audio(manifest: dict[str, Any]) -> dict[str, Any]:
    if _st_load is None or torch is None:
        raise RuntimeError("Generated-audio assembly requires safetensors and torch.")
    waveforms = []
    sample_rate = None
    for segment in manifest["segments"]:
        checkpoint = _absolute_output_path(segment["checkpoint"])
        tensors = _st_load(checkpoint)
        if "delivered_audio" not in tensors:
            raise ValueError(
                "Checkpoint for clip %d has no delivered audio. Wire decoded "
                "audio through Trim and Segment Save." % segment["index"])
        current_rate = int(segment.get("sample_rate", 0))
        if current_rate <= 0:
            raise ValueError("Checkpoint for clip %d has no audio sample rate."
                             % segment["index"])
        if sample_rate is None:
            sample_rate = current_rate
        elif current_rate != sample_rate:
            raise ValueError("Generated segment audio sample rates do not match.")
        waveform = tensors["delivered_audio"]
        expected = int(round(
            int(segment["delivered_frames"]) / float(FPS) * current_rate))
        if int(waveform.shape[-1]) != expected:
            raise ValueError(
                "Checkpoint for clip %d has %d delivered audio samples; expected "
                "%d for %d frames." %
                (segment["index"], int(waveform.shape[-1]), expected,
                 int(segment["delivered_frames"])))
        waveforms.append(waveform)
    return {"waveform": torch.cat(waveforms, dim=-1),
            "sample_rate": int(sample_rate)}


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    segments = manifest.get("segments") or []
    clip_count = int(manifest.get("clip_count", 0))
    if clip_count < 1 or len(segments) != clip_count:
        raise ValueError(
            "H3 chain manifest contains %d segments; expected %d." %
            (len(segments), clip_count))
    total_frames = 0
    for index, segment in enumerate(segments, start=1):
        _verify_segment_artifacts(segment, index)
        total_frames += int(segment.get("delivered_frames", 0))
    expected_frames = int(manifest.get("total_delivered_frames", -1))
    if total_frames != expected_frames:
        raise ValueError(
            "H3 chain manifest segment durations total %d frames; expected %d."
            % (total_frames, expected_frames))
    return segments


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode:
        tail = "\n".join(result.stderr.splitlines()[-20:])
        raise RuntimeError("ffmpeg failed (%d):\n%s" % (result.returncode, tail))


class MiniMaxH3ChainAssemble:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (MANIFEST_TYPE,),
                "audio_source": (["plan", "source", "generated", "none"],
                                 {"default": "plan"}),
                "filename": ("STRING", {"default": "final"}),
                "audio_bitrate": ("INT", {"default": 256, "min": 64,
                                            "max": 512}),
            },
            "optional": {
                "source_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "assemble"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/chain"
    DESCRIPTION = ("Stream-copy saved H3 segments into one MP4 and mux either "
                   "the original source track or checkpointed generated audio.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def assemble(self, manifest, audio_source, filename, audio_bitrate,
                 source_audio=None):
        segments = _validate_manifest(manifest)
        selected = audio_source
        if selected == "plan":
            mode = manifest["compatibility"]["audio_mode"]
            selected = ("source" if mode in
                        ("source_track", "source_plus_timeline")
                        else "generated")
        audio = None
        if selected == "source":
            _validate_source_audio_hash(
                manifest["compatibility"], source_audio,
                "H3 Chain Assemble")
            waveform, sample_rate = _validate_audio(
                source_audio, "H3 Chain Assemble source audio")
            required_samples = int(round(
                int(manifest["total_delivered_frames"]) /
                float(FPS) * sample_rate))
            if int(waveform.shape[-1]) < required_samples:
                raise ValueError(
                    "H3 Chain Assemble source audio has %d samples; at least "
                    "%d are required for %d video frames." %
                    (int(waveform.shape[-1]), required_samples,
                     int(manifest["total_delivered_frames"])))
            audio = source_audio
        elif selected == "generated":
            audio = _generated_audio(manifest)
        elif selected != "none":
            raise ValueError("Unknown H3 chain assembly audio source %r."
                             % selected)

        run_name = _safe_name(manifest.get("run_name"), "h3_chain")
        run_dir = os.path.join(_output_root(), "h3_chains", run_name)
        final_dir = os.path.join(run_dir, "final")
        os.makedirs(final_dir, exist_ok=True)
        final_name = _safe_name(filename, "final")
        final_path = os.path.join(final_dir, final_name + ".mp4")
        concat_path = os.path.join(final_dir, ".concat.txt")
        video_tmp = os.path.join(final_dir, ".video.tmp.mp4")
        final_tmp = os.path.join(final_dir, ".final.tmp.mp4")
        wav_tmp = os.path.join(final_dir, ".audio.tmp.wav")

        segment_paths = []
        for item in segments:
            path = _absolute_output_path(item["segment"])
            if not os.path.isfile(path):
                raise FileNotFoundError("H3 chain segment is missing: %s" % path)
            segment_paths.append(path)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to assemble H3 chain segments.")
        with open(concat_path, "w", encoding="utf-8") as handle:
            for path in segment_paths:
                escaped = path.replace("\\", "\\\\").replace("'", "'\\''")
                handle.write("file '%s'\n" % escaped)

        for temporary in (video_tmp, final_tmp, wav_tmp):
            if os.path.exists(temporary):
                os.unlink(temporary)
        try:
            _run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i",
                         concat_path, "-c", "copy", video_tmp])

            if audio is None:
                os.replace(video_tmp, final_tmp)
            else:
                _write_wav(audio, wav_tmp)
                _run_ffmpeg([
                    ffmpeg, "-y", "-i", video_tmp, "-i", wav_tmp,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "%dk" % int(audio_bitrate),
                    "-t", "%.9f" % (int(manifest["total_delivered_frames"]) /
                                      float(FPS)),
                    "-movflags", "+faststart", final_tmp,
                ])
            os.replace(final_tmp, final_path)
        finally:
            for temporary in (concat_path, video_tmp, final_tmp, wav_tmp):
                if os.path.exists(temporary):
                    os.unlink(temporary)

        status = "assembled %d clips -> %s" % (len(segments), final_path)
        _LOG.info("H3 Chain %s", status)
        return {"ui": {"text": [status]}, "result": (final_path,)}


async def _submit_review_decision(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Expected a JSON request body."},
                                 status=400)
    token = str(body.get("token") or "")
    pending = _PENDING_REVIEWS.get(token)
    if pending is None:
        return web.json_response(
            {"error": "This H3 review is no longer pending."}, status=404)
    future = pending["future"]
    if future.done():
        return web.json_response(
            {"error": "This H3 review already has a decision."}, status=409)

    action = str(body.get("action") or "")
    if action not in ("approve", "retry", "reroll", "stop"):
        return web.json_response({"error": "Unknown review action."}, status=400)

    decision: dict[str, Any] = {"action": action}
    if action in ("retry", "reroll"):
        scene_prompt = str(body.get("scene_prompt") or "").strip()
        if not scene_prompt:
            return web.json_response(
                {"error": "The retry prompt cannot be empty."}, status=400)
        if len(scene_prompt) > 200000:
            return web.json_response(
                {"error": "The retry prompt is too large."}, status=400)
        if action == "reroll":
            seed = secrets.randbits(64)
            while seed == int(pending["current_seed"]):
                seed = secrets.randbits(64)
        else:
            try:
                seed = int(str(body.get("seed")))
            except (TypeError, ValueError):
                return web.json_response(
                    {"error": "The retry seed must be an integer."}, status=400)
            if seed < 0 or seed > MAX_SEED:
                return web.json_response(
                    {"error": "The retry seed is outside the uint64 range."},
                    status=400)
        decision = {
            "action": "retry",
            "scene_prompt": scene_prompt,
            "seed": seed,
        }

    future.set_result(decision)
    return web.json_response({
        "ok": True,
        "action": decision["action"],
        "seed": str(decision.get("seed", pending["current_seed"])),
    })


async def _list_pending_reviews(_request):
    reviews = [
        item["public"] for item in _PENDING_REVIEWS.values()
        if not item["future"].done()
    ]
    return web.json_response({"reviews": reviews})


if (PromptServer is not None and web is not None and
        getattr(PromptServer, "instance", None) is not None):
    PromptServer.instance.routes.post(
        "/h3_motion_context/review")(_submit_review_decision)
    PromptServer.instance.routes.get(
        "/h3_motion_context/reviews")(_list_pending_reviews)


CHAIN_NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ChainPlan": MiniMaxH3ChainPlan,
    "MiniMaxH3ChainLoopStart": MiniMaxH3ChainLoopStart,
    "MiniMaxH3ChainCurrent": MiniMaxH3ChainCurrent,
    "MiniMaxH3ChainContext": MiniMaxH3ChainContext,
    "MiniMaxH3ChainSegmentSave": MiniMaxH3ChainSegmentSave,
    "MiniMaxH3ChainReview": MiniMaxH3ChainReview,
    "MiniMaxH3ChainLoopEnd": MiniMaxH3ChainLoopEnd,
    "MiniMaxH3ChainManifestLoad": MiniMaxH3ChainManifestLoad,
    "MiniMaxH3ChainAssemble": MiniMaxH3ChainAssemble,
}

CHAIN_NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ChainPlan": "H3 Chain Plan",
    "MiniMaxH3ChainLoopStart": "H3 Chain Loop Start",
    "MiniMaxH3ChainCurrent": "H3 Chain Current Shot",
    "MiniMaxH3ChainContext": "H3 Chain Context",
    "MiniMaxH3ChainSegmentSave": "H3 Chain Segment + Checkpoint",
    "MiniMaxH3ChainReview": "H3 Chain Review Gate",
    "MiniMaxH3ChainLoopEnd": "H3 Chain Loop End",
    "MiniMaxH3ChainManifestLoad": "H3 Chain Load Completed Manifest",
    "MiniMaxH3ChainAssemble": "H3 Chain Assemble",
}
