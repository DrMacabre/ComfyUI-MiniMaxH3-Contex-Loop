"""Boundary-exact generated-audio continuity for H3 Contex Loop 0.6.37.

Exact Final Timeline must never feed the RAW predecessor video latent into a
new scene after the predecessor was padded beyond its authored edit boundary.
The existing continuation sanitation therefore removes ``previous_latent``
whenever ``tail_trim_frames > 0``.  That is correct for picture, but it also
made generated-audio continuity impossible because the current 0.6.37 context
path uses the same AV carrier for both streams.

This overlay keeps the sanitation rule and reconstructs only the disposable
next-scene carrier:

* video comes from the already delivered RGB tail and is re-encoded, so it ends
  exactly on the authored picture boundary;
* audio comes from the immutable RAW predecessor checkpoint but is sliced so
  its END is ``raw_frames - tail_trim_frames`` rather than the RAW sampler end;
* the synthetic AV carrier is marked timeline-exact before the existing
  Exact Final Timeline context wrapper sees it.

The checkpoint itself is never modified.  Missing metadata, incompatible
geometry, or insufficient exact context still fail closed.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable


_LOG = logging.getLogger("minimax_h3_context_loop.exact_generated_continuity")
_SENTINEL = "_h3_exact_generated_continuity_overlay_v2"
BUILD = "H3_EXACT_GENERATED_CONTINUITY_0_6_37_V2"
AUDIO_HZ = 40
_SHARED_AV_GRID = (
    243, 226, 209, 192, 175, 158, 141, 124,
    107, 90, 73, 56, 39, 22, 5, 1,
)
_FRAME_PER_TOKEN = (1, 4, 4, 4, 4)


class ExactGeneratedContinuityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactGeneratedContinuityReport:
    activated: bool
    patched: tuple[str, ...]


def _signature_prefix(
    function: Callable[..., Any], expected: tuple[str, ...], *, label: str,
) -> None:
    try:
        names = tuple(inspect.signature(function).parameters)
    except (TypeError, ValueError) as exc:
        raise ExactGeneratedContinuityError(f"cannot inspect {label}") from exc
    if names[: len(expected)] != expected:
        raise ExactGeneratedContinuityError(
            f"refusing exact generated-continuity overlay: {label} signature "
            f"{names!r} does not begin with {expected!r}"
        )


def _pixel_frames(latent_steps: int) -> int:
    return sum(_FRAME_PER_TOKEN[k % len(_FRAME_PER_TOKEN)]
               for k in range(int(latent_steps)))


def _audio_steps(frames: int, fps: int) -> int:
    return int(round(int(frames) * AUDIO_HZ / float(int(fps))))


def _tail_geometry(value: Any, *, where: str) -> tuple[int, int, int]:
    if not isinstance(value, dict):
        raise ExactGeneratedContinuityError(f"{where} is not a mapping")
    try:
        raw = int(value.get("raw_frames", 0))
        delivered = int(value.get("delivered_frames", 0))
        tail = int(value.get("tail_trim_frames", 0) or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExactGeneratedContinuityError(
            f"{where} has invalid raw/delivered/tail frame metadata"
        ) from exc
    if raw < 1 or delivered < 1 or tail < 1 or tail >= raw:
        raise ExactGeneratedContinuityError(
            f"{where} has invalid raw/delivered/tail frames "
            f"{raw}/{delivered}/{tail}"
        )
    boundary = raw - tail
    if delivered > boundary:
        raise ExactGeneratedContinuityError(
            f"{where} delivers {delivered} frames past its exact boundary "
            f"{boundary}"
        )
    return raw, delivered, tail


def _audio_predecessor_index(chain_module: Any, plan: dict[str, Any],
                             index: int) -> int:
    resolver = getattr(chain_module, "_resume_context_predecessors", None)
    if callable(resolver):
        try:
            resolved = resolver(plan, int(index))
        except Exception as exc:
            raise ExactGeneratedContinuityError(
                f"cannot resolve scene {index} audio predecessor"
            ) from exc
        if isinstance(resolved, dict) and resolved.get("audio") is not None:
            try:
                value = int(resolved["audio"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ExactGeneratedContinuityError(
                    f"scene {index} audio predecessor is invalid"
                ) from exc
            if value > 0:
                return value
    return int(index) - 1


def _segment_for_index(state: dict[str, Any], source_index: int) -> dict[str, Any]:
    segments = state.get("segments")
    if not isinstance(segments, list):
        raise ExactGeneratedContinuityError(
            "exact generated continuity has no predecessor segment history"
        )
    for item in reversed(segments):
        if not isinstance(item, dict):
            continue
        try:
            item_index = int(item.get("index", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if item_index == int(source_index):
            return item
    raise ExactGeneratedContinuityError(
        f"exact generated continuity cannot find predecessor scene {source_index}"
    )


def _choose_carrier_frames(required: int, available: int, boundary: int) -> int:
    cap = min(int(available), int(boundary))
    required = max(1, int(required))
    candidates = [value for value in _SHARED_AV_GRID
                  if value <= cap and value >= required]
    if candidates:
        return min(candidates)
    fallback = next((value for value in _SHARED_AV_GRID if value <= cap), 0)
    if fallback and required <= fallback:
        return fallback
    raise ExactGeneratedContinuityError(
        "exact generated continuity cannot build a shared H3 AV carrier: "
        f"needs at least {required} frames but only {cap} exact delivered "
        "frames are available"
    )


def _build_boundary_latent(
    chain_module: Any,
    state: dict[str, Any],
    vae: Any,
    target_latent: Any,
    *,
    context_frames: int,
    audio_context_frames: int,
) -> tuple[dict[str, Any], int, int]:
    plan = state.get("plan")
    if not isinstance(plan, dict):
        raise ExactGeneratedContinuityError("current chain state has no Plan")
    try:
        index = int(state["index"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ExactGeneratedContinuityError(
            "current chain state has no valid scene index"
        ) from exc

    source_index = _audio_predecessor_index(chain_module, plan, index)
    segment = _segment_for_index(state, source_index)
    raw, delivered, tail = _tail_geometry(
        segment, where=f"predecessor scene {source_index}"
    )
    boundary = raw - tail

    previous_frames = state.get("previous_frames")
    if getattr(previous_frames, "ndim", 0) != 4:
        raise ExactGeneratedContinuityError(
            "exact generated continuity requires delivered predecessor RGB "
            "frames in state['previous_frames']"
        )
    available = int(previous_frames.shape[0])
    required = max(int(context_frames), int(audio_context_frames), 1)
    carrier_frames = _choose_carrier_frames(required, available, boundary)

    if not callable(getattr(chain_module, "_streams_from_latent", None)):
        raise ExactGeneratedContinuityError(
            "chain module cannot unpack the current H3 target latent"
        )
    target_streams = chain_module._streams_from_latent(target_latent)
    if not target_streams:
        raise ExactGeneratedContinuityError("current H3 target latent has no video")
    target_video = target_streams[0]
    if getattr(target_video, "ndim", 0) == 4:
        target_video = target_video.unsqueeze(0)
    if getattr(target_video, "ndim", 0) != 5:
        raise ExactGeneratedContinuityError(
            "current H3 target video latent is not [B,C,T,H,W]"
        )
    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16
    crop = str(plan.get("compatibility", {}).get("crop", "center"))
    rgb_tail = previous_frames[-carrier_frames:]
    resized = chain_module._resize(rgb_tail, width, height, crop)
    encoded_video = vae.encode(resized)
    if getattr(encoded_video, "ndim", 0) != 5:
        raise ExactGeneratedContinuityError(
            "video VAE did not return a 5D H3 latent for exact RGB context"
        )
    covered = _pixel_frames(int(encoded_video.shape[2]))
    if covered != carrier_frames:
        raise ExactGeneratedContinuityError(
            f"{carrier_frames} exact RGB frames encoded to "
            f"{int(encoded_video.shape[2])} H3 steps covering {covered} frames"
        )
    if (int(encoded_video.shape[1]) != int(target_video.shape[1])
            or tuple(encoded_video.shape[3:]) != tuple(target_video.shape[3:])):
        raise ExactGeneratedContinuityError(
            "exact RGB carrier geometry does not match the target H3 latent"
        )

    if chain_module._st_load is None:
        raise ExactGeneratedContinuityError(
            "safetensors is unavailable for exact generated-audio continuity"
        )
    checkpoint = segment.get("checkpoint")
    if not checkpoint:
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} has no checkpoint path"
        )
    tensors = chain_module._st_load(chain_module._absolute_output_path(checkpoint))
    raw_video = tensors.get("video")
    raw_audio = tensors.get("audio")
    if raw_video is None or raw_audio is None:
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} checkpoint has no RAW AV streams"
        )
    if getattr(raw_video, "ndim", 0) == 4:
        raw_video = raw_video.unsqueeze(0)
    if getattr(raw_audio, "ndim", 0) == 3:
        raw_audio = raw_audio.unsqueeze(0)
    if getattr(raw_video, "ndim", 0) != 5 or getattr(raw_audio, "ndim", 0) != 4:
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} checkpoint RAW AV shapes are invalid"
        )
    raw_covered = _pixel_frames(int(raw_video.shape[2]))
    if raw_covered != raw:
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} RAW video latent covers "
            f"{raw_covered} frames; metadata says {raw}"
        )

    fps = int(chain_module.FPS)
    expected_raw_audio = _audio_steps(raw, fps)
    if int(raw_audio.shape[-1]) != expected_raw_audio:
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} RAW audio has "
            f"{int(raw_audio.shape[-1])} steps; expected {expected_raw_audio} "
            f"for {raw} frames"
        )
    boundary_audio = _audio_steps(boundary, fps)
    carrier_audio = _audio_steps(carrier_frames, fps)
    start_audio = boundary_audio - carrier_audio
    if start_audio < 0 or boundary_audio > int(raw_audio.shape[-1]):
        raise ExactGeneratedContinuityError(
            f"predecessor scene {source_index} cannot provide an exact "
            f"{carrier_frames}-frame audio window ending at frame {boundary}"
        )
    audio_tail = raw_audio[:1, ..., start_audio:boundary_audio].clone()
    if int(audio_tail.shape[-1]) != carrier_audio:
        raise ExactGeneratedContinuityError(
            "exact generated-audio boundary slice produced the wrong length"
        )

    _LOG.info(
        "Exact Final Timeline scene %d rebuilt a boundary-exact AV carrier "
        "from scene %d: %df delivered RGB + %d audio steps ending at frame "
        "%d; %d RAW tail frame(s) excluded.",
        index, source_index, carrier_frames, carrier_audio, boundary, tail,
    )
    return {"samples": [encoded_video, audio_tail]}, carrier_frames, source_index


def _wrap_context_apply(original: Callable[..., Any], chain_module: Any):
    if getattr(original, _SENTINEL, False):
        return original

    @wraps(original)
    def apply(
        self, state, conditioning, vae, latent, audio_vae=None,
        model=None, drift_sigmas=None, boundary_anchors=None,
        visual_cond_noise_aug=None, future_end_anchor=False,
    ):
        patched_state = state
        try:
            index = int(state.get("index", 1))
        except (AttributeError, TypeError, ValueError, OverflowError):
            index = 1
        if index > 1 and state.get("previous_latent_timeline_exact") is False:
            plan = state.get("plan")
            if not isinstance(plan, dict):
                raise ExactGeneratedContinuityError(
                    "exact generated continuity cannot resolve the current Plan"
                )
            shots = plan.get("shots")
            if not isinstance(shots, list) or index > len(shots):
                raise ExactGeneratedContinuityError(
                    f"exact generated continuity cannot resolve scene {index}"
                )
            shot = shots[index - 1]
            cfg = plan.get("compatibility") or {}
            context = chain_module._shot_context_length(
                shot, int(cfg.get("context_length", 0)))
            audio_context = chain_module._shot_audio_context_length(
                shot, int(cfg.get("audio_context_length", 0)), context)
            generated_audio = (
                chain_module._audio_policy_uses_generated_continuity(cfg, shot)
                and not chain_module._audio_policy_locks_source_audio(cfg, shot)
                and int(audio_context) > 0
            )
            if generated_audio:
                safe_latent, _carrier_frames, _source_index = _build_boundary_latent(
                    chain_module,
                    state,
                    vae,
                    latent,
                    context_frames=int(context),
                    audio_context_frames=int(audio_context),
                )
                patched_state = dict(state)
                patched_state["previous_latent"] = safe_latent
                patched_state["previous_latent_timeline_exact"] = True
                patched_state["_exact_generated_continuity_boundary"] = True

        kwargs = {
            "audio_vae": audio_vae,
            "model": model,
            "drift_sigmas": drift_sigmas,
            "boundary_anchors": boundary_anchors,
            "future_end_anchor": future_end_anchor,
        }
        if visual_cond_noise_aug is not None:
            kwargs["visual_cond_noise_aug"] = visual_cond_noise_aug
        return original(
            self, patched_state, conditioning, vae, latent, **kwargs
        )

    setattr(apply, _SENTINEL, True)
    apply._exact_generated_continuity_original = original
    return apply


def preflight_exact_generated_continuity(chain_module: Any) -> tuple[str, ...]:
    context_cls = getattr(chain_module, "MiniMaxH3ChainContext", None)
    if not isinstance(context_cls, type):
        raise ExactGeneratedContinuityError("MiniMaxH3ChainContext is missing")
    apply = getattr(context_cls, "apply", None)
    if not callable(apply):
        raise ExactGeneratedContinuityError("MiniMaxH3ChainContext.apply is missing")
    _signature_prefix(
        apply,
        ("self", "state", "conditioning", "vae", "latent"),
        label="MiniMaxH3ChainContext.apply",
    )
    for name in (
        "_shot_context_length",
        "_shot_audio_context_length",
        "_audio_policy_uses_generated_continuity",
        "_audio_policy_locks_source_audio",
        "_streams_from_latent",
        "_resize",
        "_absolute_output_path",
        "FPS",
    ):
        if not hasattr(chain_module, name):
            raise ExactGeneratedContinuityError(
                f"chain module is missing required continuity symbol {name}"
            )
    return ("MiniMaxH3ChainContext.apply",)


def activate_exact_generated_continuity(
    chain_module: Any,
) -> ExactGeneratedContinuityReport:
    preflight_exact_generated_continuity(chain_module)
    existing = getattr(chain_module, _SENTINEL, None)
    if isinstance(existing, ExactGeneratedContinuityReport):
        return existing

    chain_module.MiniMaxH3ChainContext.apply = _wrap_context_apply(
        chain_module.MiniMaxH3ChainContext.apply, chain_module
    )
    report = ExactGeneratedContinuityReport(
        activated=True,
        patched=("MiniMaxH3ChainContext.apply",),
    )
    setattr(chain_module, _SENTINEL, report)
    return report
