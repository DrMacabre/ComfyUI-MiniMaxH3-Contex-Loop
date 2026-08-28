"""Fool for Love exact-final-timeline compatibility layer for upstream 0.6.37.

This module is intentionally surgical.  It leaves the current upstream H3
continuation/policy/asset implementation intact and changes only the contract
between an authored scene duration and H3's internal 17k+5 generation grid.

Authoritative edit timing:
    requested_frames == delivered_frames
H3 internal timing:
    raw_frames = round_up_17k_plus_5(requested_frames + repeated_head)
    tail_trim_frames = raw_frames - repeated_head - delivered_frames

The raw tail is model padding.  It is never allowed to advance the edit/source
timeline or become hidden continuation context.
"""

from __future__ import annotations

import copy
import contextvars
import inspect
import json
import logging
import math
from typing import Any

from . import chain_nodes as _chain

_LOG = logging.getLogger("minimax_h3_context_loop.exact_final_timeline")
BUILD = "FFL_EXACT_FINAL_TIMELINE_0_6_37_V1"
_SELECTED_REVIEW_REQUESTED = contextvars.ContextVar(
    "ffl_exact_review_requested", default=None)

_ORIG_VALIDATE_H3_LENGTH = _chain._validate_h3_length
_ORIG_NORMALIZE_PLAN = _chain._normalize_plan
_ORIG_RETIME_REVIEW_PLAN = _chain._retime_review_plan
_ORIG_PLAN_WITH_REVIEW_REVISION = _chain._plan_with_review_revision
_ORIG_PLAN_WITH_EXTERNAL_CONTEXT = _chain._plan_with_external_context
_ORIG_CANONICAL_SOURCE_REFERENCE_DEPENDENCY = (
    _chain._canonical_source_reference_dependency)
_ORIG_PUBLIC_SEGMENT = _chain._public_segment
_ORIG_INITIAL_STATE = _chain._initial_state
_ORIG_CURRENT = _chain.MiniMaxH3ChainCurrent.current
_ORIG_SEGMENT_SAVE = _chain.MiniMaxH3ChainSegmentSave.save
_ORIG_CONTEXT_APPLY = _chain.MiniMaxH3ChainContext.apply
_ORIG_LOOP_END = _chain.MiniMaxH3ChainLoopEnd.end
_ORIG_RECURSE = _chain.MiniMaxH3ChainLoopEnd._recurse
_ORIG_BLEND_VIDEO_RECORDS = _chain._blend_video_records
_ORIG_GENERATED_AUDIO = _chain._generated_audio
_ORIG_SELECT_REVIEW_CANDIDATE = _chain._select_review_candidate
_ORIG_REVIEW_VIDEO = _chain._review_video


def _validate_requested_frame_length(length: Any, label: str) -> int:
    try:
        value = int(length)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be an integer final frame count." % label) from exc
    if value < 1 or value > _chain.MAX_H3_FRAMES:
        raise ValueError(
            "%s must be between 1 and %d final frames; got %d." %
            (label, _chain.MAX_H3_FRAMES, value))
    return value


def _quantized_h3_delivery(target_delivery: Any, trim_frames: Any,
                           label: str) -> tuple[int, int, int]:
    """Return raw H3 frames, exact delivered frames and disposable raw tail."""
    target = _validate_requested_frame_length(target_delivery, label)
    trim = max(0, int(trim_frames))
    target_raw = target + trim
    raw = target_raw + (5 - target_raw % 17) % 17
    raw = max(5, raw)
    if raw > _chain.MAX_H3_FRAMES:
        raise ValueError(
            "%s needs %d raw frames after %d repeated context frames; "
            "H3's largest valid 17k+5 length is %d." %
            (label, raw, trim, _chain.MAX_H3_FRAMES))
    tail = raw - trim - target
    return raw, target, tail


def _review_aware_validate_h3_length(length: Any, label: str) -> int:
    """Review Gate edits final scene length; every other H3 socket stays strict."""
    text = str(label or "").lower()
    if "review retry" in text:
        return _validate_requested_frame_length(length, label)
    return _ORIG_VALIDATE_H3_LENGTH(length, label)


def _parse_plan_document(plan_json: Any) -> dict[str, Any]:
    try:
        raw = json.loads(str(plan_json or ""))
    except json.JSONDecodeError as exc:
        raise ValueError("H3 Chain Plan JSON is invalid: %s" % exc) from exc
    if isinstance(raw, list):
        raw = {"shots": raw}
    if not isinstance(raw, dict):
        raise ValueError("H3 Chain Plan must be a JSON object or a list of shots.")
    shots = raw.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("H3 Chain Plan requires a non-empty 'shots' list.")
    return raw


def _duration_to_requested_frames(seconds: Any, label: str) -> int:
    try:
        value = float(seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be a finite positive duration." % label) from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("%s must be a finite positive duration." % label)
    return _validate_requested_frame_length(
        max(1, int(round(value * float(_chain.FPS)))), label)


def _requested_frames_from_document(
        raw: dict[str, Any], default_duration_seconds: Any) -> list[int]:
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    default_duration = defaults.get(
        "duration_seconds",
        raw.get("duration_seconds", default_duration_seconds),
    )
    values: list[int] = []
    for offset, item in enumerate(raw["shots"]):
        index = offset + 1
        if isinstance(item, str):
            item = {}
        if not isinstance(item, dict):
            values.append(_duration_to_requested_frames(
                default_duration, "Shot %d requested duration" % index))
            continue
        explicit = item.get("length", item.get("frames"))
        if explicit is not None:
            values.append(_validate_requested_frame_length(
                explicit, "Shot %d requested length" % index))
        else:
            duration = item.get("duration_seconds", default_duration)
            values.append(_duration_to_requested_frames(
                duration, "Shot %d requested duration" % index))
    return values


def _shadow_plan_json(raw: dict[str, Any]) -> str:
    """Give upstream safe raw-grid lengths while it validates modern policies."""
    shadow = copy.deepcopy(raw)
    rewritten = []
    for item in shadow["shots"]:
        if isinstance(item, str):
            item = {"prompt": item}
        elif isinstance(item, dict):
            item = dict(item)
        rewritten.append(item)
    shadow["shots"] = rewritten
    for item in shadow["shots"]:
        if not isinstance(item, dict):
            continue
        item["length"] = int(_chain.MAX_H3_FRAMES)
        item.pop("frames", None)
        item.pop("duration_seconds", None)
    return json.dumps(shadow, ensure_ascii=False)


def _recompute_plan_hash(plan: dict[str, Any]) -> None:
    contracts = []
    for shot in plan["shots"]:
        contract = {
            key: value for key, value in shot.items()
            if key not in (
                "prompt", "scene_prompt", "scene_prompt_template",
                "prompt_choice_seed", "prompt_seed", "prompt_seed_mode")
        }
        if "prompt_template_hash" in shot:
            contract["prompt_hash"] = shot["prompt_template_hash"]
        contracts.append(contract)
    plan["plan_hash"] = _chain._fingerprint({
        "compatibility": plan["compatibility"],
        "shots": contracts,
    })


def _validate_exact_visual_context(plan: dict[str, Any]) -> None:
    shots = plan["shots"]
    if len(shots) < 2:
        return
    default_context = int(plan["compatibility"].get("context_length", 0))
    default_blend = int(plan["compatibility"].get("video_blend_frames", 0))
    for target_index in range(2, len(shots) + 1):
        target = shots[target_index - 1]
        source_index = _chain._shot_visual_context_source(plan, target_index)
        source = shots[source_index - 1]
        next_context = _chain._shot_context_length(target, default_context)
        lead_source_index = _chain._shot_visual_context_lead_source(
            plan, target_index)
        lead_frames = (
            _chain._shot_visual_context_lead_frames(target, next_context)
            if lead_source_index is not None else 0)
        recent_frames = next_context - lead_frames
        if int(source["delivered_frames"]) < recent_frames:
            raise ValueError(
                "Shot %d (%s) delivers only %d exact timeline frames, but "
                "scene %d requires %d second-block visual context frames." %
                (source["index"], source["id"], source["delivered_frames"],
                 target_index, recent_frames))
        recent_start = _chain._shot_visual_context_start_frame(
            target, "visual_context_start_frame",
            int(source["raw_frames"]), int(source["delivered_frames"]),
            recent_frames, lead_frames)
        if "visual_context_start_frame" in target:
            recent_default = _chain._native_context_window_starts(
                int(source["raw_frames"]), int(source["delivered_frames"]),
                recent_frames, lead_frames)[-1]
            if recent_start == recent_default:
                target.pop("visual_context_start_frame", None)
            else:
                target["visual_context_start_frame"] = recent_start
        if lead_source_index is not None:
            lead_source = shots[lead_source_index - 1]
            if int(lead_source["delivered_frames"]) < lead_frames:
                raise ValueError(
                    "Shot %d (%s) delivers only %d exact timeline frames, but "
                    "scene %d requires %d composed lead frames." %
                    (lead_source["index"], lead_source["id"],
                     lead_source["delivered_frames"], target_index, lead_frames))
            lead_start = _chain._shot_visual_context_start_frame(
                target, "visual_context_lead_start_frame",
                int(lead_source["raw_frames"]),
                int(lead_source["delivered_frames"]), lead_frames, 0)
            if "visual_context_lead_start_frame" in target:
                lead_default = _chain._native_context_window_starts(
                    int(lead_source["raw_frames"]),
                    int(lead_source["delivered_frames"]), lead_frames, 0)[-1]
                if lead_start == lead_default:
                    target.pop("visual_context_lead_start_frame", None)
                else:
                    target["visual_context_lead_start_frame"] = lead_start
        if ((source_index != target_index - 1
                or lead_source_index is not None
                or "visual_context_start_frame" in target
                or "visual_context_lead_start_frame" in target)
                and int(target.get("video_blend_frames", default_blend))):
            raise ValueError(
                "Shot %d selects non-linear, composed, or windowed visual "
                "context, so its video_blend_frames must be 0." % target_index)


def _retime_exact(plan: dict[str, Any],
                  requested_frames: list[int] | None = None) -> None:
    shots = plan["shots"]
    if requested_frames is None:
        requested_frames = [
            _validate_requested_frame_length(
                shot.get("requested_frames",
                         shot.get("delivered_frames", shot["raw_frames"])),
                "Shot %d requested length" % (offset + 1))
            for offset, shot in enumerate(shots)
        ]
    if len(requested_frames) != len(shots):
        raise ValueError("Exact timeline scene-count mismatch.")

    cfg = plan["compatibility"]
    context_default = int(cfg.get("context_length", 0))
    anchor_mode = str(cfg.get("anchor_mode", "head"))
    external_span = int(cfg.get("external_context_frames", 0))
    stitched = 0
    for offset, (shot, requested) in enumerate(zip(shots, requested_frames)):
        index = offset + 1
        requested = _validate_requested_frame_length(
            requested, "Shot %d requested length" % index)
        if offset == 0:
            trim = external_span if (external_span and anchor_mode == "head") else 0
            generation_start = -external_span if trim else 0
            if external_span:
                shot["external_context_frames"] = external_span
        else:
            scene_context = _chain._shot_context_length(shot, context_default)
            trim = scene_context if anchor_mode == "head" else 0
            generation_start = (
                stitched - scene_context if anchor_mode == "head" else stitched)
        raw, delivered, tail = _quantized_h3_delivery(
            requested, trim, "Shot %d requested length" % index)
        shot["requested_frames"] = requested
        shot["raw_frames"] = raw
        shot["delivered_frames"] = delivered
        shot["tail_trim_frames"] = tail
        shot["generation_start_frame"] = generation_start
        shot["audio_start_seconds"] = max(0, generation_start) / float(_chain.FPS)
        shot["audio_duration_seconds"] = raw / float(_chain.FPS)
        stitched += delivered

    _validate_exact_visual_context(plan)
    plan["total_delivered_frames"] = stitched
    imported = "; imported video" if external_span else ""
    plan["summary"] = (
        "%d clips; %d exact delivered frames (%.3fs) at %dx%d; context=%d; "
        "blend=%d; audio=%s%s; run=%s" %
        (len(shots), stitched, stitched / float(_chain.FPS),
         int(cfg.get("width", 0)), int(cfg.get("height", 0)),
         context_default, int(cfg.get("video_blend_frames", 0)),
         _chain._audio_policy_summary(cfg), imported, plan["run_name"]))


def _normalize_plan_exact(plan_json: str, *args, **kwargs) -> dict[str, Any]:
    bound = inspect.signature(_ORIG_NORMALIZE_PLAN).bind_partial(
        plan_json, *args, **kwargs)
    bound.apply_defaults()
    raw = _parse_plan_document(plan_json)
    requested = _requested_frames_from_document(
        raw, bound.arguments.get("default_duration_seconds", 15.0))
    shadow = _shadow_plan_json(raw)
    prepared = _ORIG_NORMALIZE_PLAN(shadow, *args, **kwargs)
    _retime_exact(prepared, requested)
    _recompute_plan_hash(prepared)
    return prepared


def _retime_review_plan_exact(plan: dict[str, Any]) -> None:
    _retime_exact(plan)


def _plan_with_review_revision_exact(
        plan: dict[str, Any], index: int, scene_prompt: str, seed: int,
        raw_frames: int | None = None) -> dict[str, Any]:
    index = int(index)
    current = plan["shots"][index - 1]
    requested = int(current.get(
        "requested_frames", current.get("delivered_frames", current["raw_frames"])))
    forced = _SELECTED_REVIEW_REQUESTED.get()
    if (isinstance(forced, tuple) and len(forced) == 2
            and int(forced[0]) == index):
        requested = _validate_requested_frame_length(
            forced[1], "Selected review candidate requested length")
    elif raw_frames is not None:
        incoming = int(raw_frames)
        if incoming != int(current.get("raw_frames", -1)):
            requested = _validate_requested_frame_length(
                incoming, "H3 review retry requested length")
    revised = _ORIG_PLAN_WITH_REVIEW_REVISION(
        plan, index, scene_prompt, seed, None)
    revised["shots"][index - 1]["requested_frames"] = requested
    _retime_exact(revised)
    overrides = dict(revised.get("review_overrides") or {})
    entry = dict(overrides.get(str(index)) or {})
    shot = revised["shots"][index - 1]
    entry.update({
        "requested_frames": int(shot["requested_frames"]),
        "raw_frames": int(shot["raw_frames"]),
        "delivered_frames": int(shot["delivered_frames"]),
        "tail_trim_frames": int(shot.get("tail_trim_frames", 0)),
    })
    overrides[str(index)] = entry
    revised["review_overrides"] = overrides
    base_plan_hash = str(revised.get("base_plan_hash") or plan["plan_hash"])
    source_hash = str(
        revised.get("compatibility", {}).get("source_audio_hash") or "none")
    external_hash = str(
        revised.get("compatibility", {}).get("external_context_hash") or "none")
    contract = {
        "base_plan_hash": base_plan_hash,
        "source_audio_hash": source_hash,
        "review_overrides": overrides,
    }
    if external_hash != "none":
        contract["external_context_hash"] = external_hash
    revised["plan_hash"] = _chain._fingerprint(contract)
    return revised


def _plan_with_external_context_exact(
        plan: dict[str, Any], external_context: Any) -> dict[str, Any]:
    if external_context is None:
        return _ORIG_PLAN_WITH_EXTERNAL_CONTEXT(plan, external_context)
    contract = _chain._external_context_contract(external_context)
    span = int(contract["context_frames"])
    working = dict(plan)
    working["shots"] = [dict(shot) for shot in plan["shots"]]
    first = working["shots"][0]
    requested = int(first.get(
        "requested_frames", first.get("delivered_frames", first["raw_frames"])))
    trim = span if str(plan["compatibility"].get("anchor_mode", "head")) == "head" else 0
    raw, _delivered, _tail = _quantized_h3_delivery(
        requested, trim, "Shot 1 requested length")
    first["raw_frames"] = raw
    prepared = _ORIG_PLAN_WITH_EXTERNAL_CONTEXT(working, external_context)
    _retime_exact(prepared)
    return prepared


def _visible_raw_frames(shot: dict[str, Any]) -> int:
    raw = int(shot["raw_frames"])
    tail = max(0, int(shot.get("tail_trim_frames", 0)))
    visible = raw - tail
    if visible < 1:
        raise ValueError("Exact H3 source window is empty.")
    return visible


def _pad_audio_to_raw(audio: Any, raw_frames: int) -> Any:
    if audio is None or _chain.torch is None:
        return audio
    waveform, sample_rate = _chain._validate_audio(
        audio, "Exact H3 source-audio window")
    wanted = _chain.sample_boundary_from_frames(
        int(raw_frames), int(sample_rate), _chain.FPS)
    have = int(waveform.shape[-1])
    if have < wanted:
        waveform = _chain.torch.nn.functional.pad(waveform, (0, wanted - have))
    elif have > wanted:
        waveform = waveform[..., :wanted]
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


def _exact_source_window(
        plan: dict[str, Any], state: dict[str, Any], shot: dict[str, Any],
        source_timeline: Any, source_audio: Any) -> Any:
    visible = _visible_raw_frames(shot)
    raw = int(shot["raw_frames"])
    external = int(shot.get("external_context_frames", 0))
    index = int(state["index"])
    if source_timeline is not None:
        if index == 1 and external > 0:
            delivered = int(shot["delivered_frames"])
            extension = _chain._source_timeline_scene_audio(
                source_timeline, 0, delivered)
            audio = _chain._slice_audio_after_external_context(
                extension, state.get("previous_audio"),
                visible, external, pad_silence=False)
        else:
            start = int(round(float(shot["audio_start_seconds"]) * _chain.FPS))
            audio = _chain._source_timeline_scene_audio(
                source_timeline, start, start + visible)
    else:
        if index == 1 and external > 0:
            audio = _chain._slice_audio_after_external_context(
                source_audio, state.get("previous_audio"),
                visible, external,
                pad_silence=bool(plan["compatibility"].get(
                    "source_audio_silent_padding")))
        else:
            audio = _chain._slice_audio(
                source_audio, float(shot["audio_start_seconds"]),
                visible / float(_chain.FPS),
                pad_silence=bool(plan["compatibility"].get(
                    "source_audio_silent_padding")))
    return _pad_audio_to_raw(audio, raw)


def _current_exact(
        self, state, source_audio=None, align_audio_reference=False):
    result = _ORIG_CURRENT(
        self, state, source_audio=source_audio,
        align_audio_reference=align_audio_reference)
    if not isinstance(result, dict) or "result" not in result:
        return result
    plan = state["plan"]
    index = int(state["index"])
    shot = plan["shots"][index - 1]
    tail = int(shot.get("tail_trim_frames", 0))
    if tail <= 0:
        return result
    values = list(result["result"])
    dependency_state = dict(values[0])
    source_timeline = state.get("source_timeline")
    source_reference = _chain._audio_policy_uses_source_reference(plan, shot)
    source_locked = _chain._audio_policy_locks_source_audio(plan, shot)
    if source_reference or source_locked:
        exact = _exact_source_window(
            plan, state, shot, source_timeline, source_audio)
        dependency_state["current_source_audio_target"] = (
            exact if source_locked else dependency_state.get(
                "current_source_audio_target"))
        values[12] = exact if source_reference else None
    values[0] = dependency_state
    values[13] = (
        "%s; exact=%df raw=%df tail-pad=%df" %
        (values[13], int(shot["delivered_frames"]),
         int(shot["raw_frames"]), tail))
    result = dict(result)
    result["result"] = tuple(values)
    return result


def _canonical_source_reference_dependency_exact(
        plan: dict[str, Any], index: int, source_timeline: Any = None,
        source_audio: Any = None) -> dict[str, Any] | None:
    shot = plan["shots"][int(index) - 1]
    if int(shot.get("tail_trim_frames", 0)) <= 0:
        return _ORIG_CANONICAL_SOURCE_REFERENCE_DEPENDENCY(
            plan, index, source_timeline, source_audio)
    if (not _chain._audio_policy_uses_source_reference(plan, shot)
            and not _chain._audio_policy_locks_source_audio(plan, shot)):
        return None
    start_frame = (
        0 if int(index) == 1 and int(shot.get("external_context_frames", 0)) > 0
        else max(0, int(shot["generation_start_frame"])))
    visible = _visible_raw_frames(shot)
    if source_timeline is not None:
        audio = _chain._source_timeline_scene_audio(
            source_timeline, start_frame, start_frame + visible)
        route = (
            "legacy_audio"
            if _chain._source_timeline_recovers_legacy_audio(
                plan["compatibility"], source_timeline)
            else "source_timeline")
    else:
        if source_audio is None:
            return None
        audio = _chain._slice_audio(
            source_audio, start_frame / float(_chain.FPS),
            visible / float(_chain.FPS),
            pad_silence=bool(plan["compatibility"].get(
                "source_audio_silent_padding")))
        route = "legacy_audio"
    waveform, sample_rate = _chain._validate_audio(
        audio, "Exact scene source-reference dependency")
    return {
        "route": route,
        "start_frame": start_frame,
        "end_frame": start_frame + visible,
        "frame_count": visible,
        "tail_padding_frames": int(shot.get("tail_trim_frames", 0)),
        "sample_rate": int(sample_rate),
        "sample_count": int(waveform.shape[-1]),
        "pcm_sha256": _chain._audio_fingerprint({
            "waveform": waveform, "sample_rate": sample_rate}),
    }


def _trim_audio_to_frames(audio: Any, frames: int) -> Any:
    if audio is None or _chain.torch is None:
        return audio
    waveform, sample_rate = _chain._validate_audio(
        audio, "Exact delivered H3 audio")
    wanted = _chain.sample_boundary_from_frames(
        int(frames), int(sample_rate), _chain.FPS)
    return {
        "waveform": waveform[..., :wanted],
        "sample_rate": int(sample_rate),
    }


def _segment_save_exact(
        self, state, images, sampled_latent, audio=None,
        images_with_overlap=None, denoised_latent=None,
        prompt=None, extra_pnginfo=None):
    plan = state["plan"]
    index = int(state["index"])
    shot = plan["shots"][index - 1]
    expected = int(shot["delivered_frames"])
    tail = int(shot.get("tail_trim_frames", 0))
    actual = int(images.shape[0])
    if actual < expected:
        raise ValueError(
            "H3 chain clip %d produced only %d decoded frames after head trim; "
            "the exact edit timeline requires %d." % (index, actual, expected))
    if actual > expected:
        images = images[:expected]
        _LOG.info(
            "H3 Chain exact timeline clip %d discarded %d raw tail frame(s); "
            "final scene length is exactly %d.",
            index, actual - expected, expected)

    if images_with_overlap is not None:
        context = _chain._shot_context_length(
            shot, int(plan["compatibility"].get("context_length", 0)))
        head = max(
            0, int(shot["raw_frames"]) - expected - tail)
        blend = min(
            head, _chain._shot_video_blend_frames(
                shot, int(plan["compatibility"].get(
                    "video_blend_frames", 0)), context))
        wanted = expected + blend
        if int(images_with_overlap.shape[0]) >= wanted:
            images_with_overlap = images_with_overlap[:wanted]

    audio = _trim_audio_to_frames(audio, expected)
    result = _ORIG_SEGMENT_SAVE(
        self, state, images, sampled_latent, audio=audio,
        images_with_overlap=images_with_overlap,
        denoised_latent=denoised_latent,
        prompt=prompt, extra_pnginfo=extra_pnginfo)

    def annotate(segment: dict[str, Any]) -> None:
        segment["requested_frames"] = int(shot.get(
            "requested_frames", expected))
        segment["tail_trim_frames"] = tail

    if isinstance(result, dict) and isinstance(result.get("result"), tuple):
        values = list(result["result"])
        if values and isinstance(values[0], dict):
            segment = dict(values[0])
            annotate(segment)
            metadata_value = segment.get("metadata")
            if isinstance(metadata_value, str) and metadata_value:
                try:
                    path = _chain._absolute_output_path(metadata_value)
                    document = _chain._read_json(path)
                    if isinstance(document, dict) and isinstance(
                            document.get("segment"), dict):
                        document["segment"].update({
                            "requested_frames": segment["requested_frames"],
                            "tail_trim_frames": tail,
                        })
                        _chain._atomic_json(path, document)
                except Exception as exc:
                    _LOG.warning(
                        "Exact timeline could not annotate clip %d metadata: %s",
                        index, exc)
            values[0] = segment
            result = dict(result)
            result["result"] = tuple(values)
    elif isinstance(result, tuple) and result and isinstance(result[0], dict):
        values = list(result)
        segment = dict(values[0])
        annotate(segment)
        values[0] = segment
        result = tuple(values)
    return result


def _public_segment_exact(value: dict[str, Any]) -> dict[str, Any]:
    public = _ORIG_PUBLIC_SEGMENT(value)
    for key in ("requested_frames", "tail_trim_frames"):
        if key in value:
            public[key] = value[key]
    return public


def _initial_state_exact(*args, **kwargs) -> dict[str, Any]:
    state = _ORIG_INITIAL_STATE(*args, **kwargs)
    segments = state.get("segments")
    if isinstance(segments, list) and segments:
        tail = int(segments[-1].get("tail_trim_frames", 0))
        state["previous_latent_timeline_exact"] = tail == 0
    else:
        state["previous_latent_timeline_exact"] = True
    return state


def _context_apply_exact(
        self, state, conditioning, vae, latent, audio_vae=None,
        model=None, drift_sigmas=None, boundary_anchors=None,
        visual_cond_noise_aug=_chain.VISUAL_COND_NOISE_AUG_DEFAULT,
        future_end_anchor=False):
    plan = state["plan"]
    index = int(state["index"])
    if index > 1 and not bool(state.get("previous_latent_timeline_exact", True)):
        shot = plan["shots"][index - 1]
        cfg = plan["compatibility"]
        mode = _chain.migrate_continuation_mode(shot.get(
            "continuation_mode", cfg.get("continuation_mode", "guide")))
        context = _chain._shot_context_length(
            shot, int(cfg.get("context_length", 0)))
        generated_audio_context = (
            _chain._audio_policy_uses_generated_continuity(cfg, shot)
            and not _chain._audio_policy_locks_source_audio(cfg, shot)
            and _chain._shot_audio_context_length(
                shot, int(cfg.get("audio_context_length", 0)), context) > 0)
        if generated_audio_context:
            raise ValueError(
                "Exact Final Timeline: scene %d follows an H3-padded scene and "
                "requests generated-audio latent continuity. The predecessor "
                "sampled latent extends past the edit boundary, so using it "
                "would leak hidden future audio. Use locked/source audio, turn "
                "Generated continuity off for this boundary, or choose a "
                "grid-aligned previous scene." % index)
        if mode in _chain.MASKED_CONTINUATION_MODES:
            state = dict(state)
            state["previous_latent"] = None
            _LOG.info(
                "Exact Final Timeline scene %d re-encodes delivered RGB context "
                "because the predecessor sampled latent contains raw tail padding.",
                index)
        elif mode == "latent_guide":
            state = dict(state)
            exact_plan = dict(plan)
            exact_plan["shots"] = [dict(item) for item in plan["shots"]]
            exact_plan["shots"][index - 1]["continuation_mode"] = "guide"
            state["plan"] = exact_plan
            _LOG.info(
                "Exact Final Timeline scene %d uses RGB Guide instead of latent "
                "Guide because predecessor latent extends past the edit boundary.",
                index)
    return _ORIG_CONTEXT_APPLY(
        self, state, conditioning, vae, latent, audio_vae=audio_vae,
        model=model, drift_sigmas=drift_sigmas,
        boundary_anchors=boundary_anchors,
        visual_cond_noise_aug=visual_cond_noise_aug,
        future_end_anchor=future_end_anchor)


def _loop_end_exact(self, flow, state, images, sampled_latent, segment,
                    *args, **kwargs):
    shot = state["plan"]["shots"][int(state["index"]) - 1]
    expected = int(shot["delivered_frames"])
    if int(images.shape[0]) < expected:
        raise ValueError(
            "Exact Final Timeline cannot carry clip %d: only %d decoded frames "
            "are available for an exact %d-frame scene." %
            (int(state["index"]), int(images.shape[0]), expected))
    if int(images.shape[0]) > expected:
        images = images[:expected]
    return _ORIG_LOOP_END(
        self, flow, state, images, sampled_latent, segment, *args, **kwargs)


def _recurse_exact(self, flow, next_state, dynprompt, unique_id):
    state = dict(next_state)
    index = int(state.get("index", 1))
    previous_index = index - 1
    plan = state.get("plan")
    if isinstance(plan, dict) and 1 <= previous_index <= len(plan.get("shots", [])):
        tail = int(plan["shots"][previous_index - 1].get("tail_trim_frames", 0))
        state["previous_latent_timeline_exact"] = tail == 0
    return _ORIG_RECURSE(self, flow, state, dynprompt, unique_id)


def _blend_video_records_exact(
        manifest, segments, prelude, blend_schedule="plan", video_vae=None,
        temporary_paths=None, force_records=False):
    tails = [
        int(item.get("tail_trim_frames", 0))
        for item in segments if isinstance(item, dict)]
    schedule_text = str(
        blend_schedule if blend_schedule is not None else "plan").strip().lower()
    if any(tails) and schedule_text not in ("", "plan"):
        raise ValueError(
            "Exact Final Timeline: custom recovery blend schedules on a "
            "tail-padded H3 checkpoint are intentionally blocked in V1. Use "
            "the saved Plan blend schedule; arbitrary checkpoint re-decode "
            "would otherwise expose raw tail padding.")
    adjusted = []
    for item in segments:
        clone = dict(item)
        tail = int(clone.get("tail_trim_frames", 0))
        if tail:
            clone["raw_frames"] = int(clone["raw_frames"]) - tail
        adjusted.append(clone)
    return _ORIG_BLEND_VIDEO_RECORDS(
        manifest, adjusted, prelude, blend_schedule=blend_schedule,
        video_vae=video_vae, temporary_paths=temporary_paths,
        force_records=force_records)


def _generated_audio_exact(manifest: dict[str, Any]) -> dict[str, Any]:
    if any(int(item.get("tail_trim_frames", 0))
           for item in manifest.get("segments", ())
           if isinstance(item, dict)):
        raise ValueError(
            "Exact Final Timeline V1 blocks final generated-audio assembly "
            "when an H3 scene required disposable raw tail padding. Use the "
            "source/locked final soundtrack for this migration, or a "
            "grid-aligned scene. This fail-closed guard prevents hidden raw "
            "tail audio from entering the edit.")
    return _ORIG_GENERATED_AUDIO(manifest)


def _select_review_candidate_exact(
        state: dict[str, Any], current_segment: dict[str, Any],
        decision: dict[str, Any]):
    """Promote a saved candidate using its final authored length, not raw H3 length."""
    revision = str(decision.get("candidate_revision") or "")
    if not revision or revision == str(current_segment.get("revision") or ""):
        return current_segment, state
    plan = state["plan"]
    index = int(state["index"])
    try:
        metadata, _metadata_path = _chain._load_checkpoint_revision(
            str(plan["run_name"]), index, revision)
        selected = metadata.get("segment")
        requested = (
            int(selected.get(
                "requested_frames",
                selected.get("delivered_frames", selected.get("raw_frames", 0))))
            if isinstance(selected, dict) else 0)
    except Exception:
        requested = 0
    if requested < 1:
        return _ORIG_SELECT_REVIEW_CANDIDATE(
            state, current_segment, decision)
    token = _SELECTED_REVIEW_REQUESTED.set((index, requested))
    try:
        return _ORIG_SELECT_REVIEW_CANDIDATE(
            state, current_segment, decision)
    finally:
        _SELECTED_REVIEW_REQUESTED.reset(token)



def _review_video_exact(
        plan: dict[str, Any], segment: dict[str, Any], audio: Any,
        retain_previous: bool = False):
    """Use exact delivered duration for Review without mutating saved RAW AV."""
    if audio is not None and isinstance(segment, dict):
        delivered = int(segment.get(
            "delivered_frames",
            int(segment.get("raw_frames", 0)) -
            int(segment.get("tail_trim_frames", 0))))
        if delivered > 0:
            audio = _trim_audio_to_frames(audio, delivered)
    return _ORIG_REVIEW_VIDEO(
        plan, segment, audio, retain_previous=retain_previous)

def install() -> str:
    if getattr(_chain, "_FFL_EXACT_FINAL_TIMELINE_BUILD", None) == BUILD:
        return BUILD

    _chain._validate_h3_length = _review_aware_validate_h3_length
    _chain._validate_requested_frame_length = _validate_requested_frame_length
    _chain._quantized_h3_delivery = _quantized_h3_delivery

    _chain._normalize_plan = _normalize_plan_exact
    _chain._retime_review_plan = _retime_review_plan_exact
    _chain._plan_with_review_revision = _plan_with_review_revision_exact
    _chain._plan_with_external_context = _plan_with_external_context_exact
    _chain._canonical_source_reference_dependency = (
        _canonical_source_reference_dependency_exact)
    _chain._public_segment = _public_segment_exact
    _chain._initial_state = _initial_state_exact
    _chain._blend_video_records = _blend_video_records_exact
    _chain._generated_audio = _generated_audio_exact
    _chain._select_review_candidate = _select_review_candidate_exact
    _chain._review_video = _review_video_exact

    _chain.MiniMaxH3ChainCurrent.current = _current_exact
    _chain.MiniMaxH3ChainSegmentSave.save = _segment_save_exact
    _chain.MiniMaxH3ChainContext.apply = _context_apply_exact
    _chain.MiniMaxH3ChainLoopEnd.end = _loop_end_exact
    _chain.MiniMaxH3ChainLoopEnd._recurse = _recurse_exact

    _chain._FFL_EXACT_FINAL_TIMELINE_BUILD = BUILD
    _LOG.info("Installed %s", BUILD)
    return BUILD
