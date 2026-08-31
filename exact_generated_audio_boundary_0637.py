"""Exact-boundary generated-audio assembly for H3 0.6.37.

This overlay sits after exact_generated_audio_tail_0637.  The tail overlay made
raw H3 padding safe, but its first implementation let a later masked-AV scene
own its private incoming audio head even when generated-audio continuity was
OFF.  In that policy the incoming audio target is fully denoisable, so the head
is not predecessor audio and must never be written before the authored scene
boundary.

Rules:
* generated_continuity=off: write each delivered scene waveform at its exact
  authored boundary.  A tiny post-boundary de-click interpolation smooths the
  sample discontinuity without moving scene timing.
* generated_continuity=on: preserve the existing private-overlap ownership for
  masked AV, because that head is genuine predecessor audio continuity.
* disposable raw H3 tail is never written in either mode.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable


_LOG = logging.getLogger("minimax_h3_context_loop.exact_audio_boundary")
_SENTINEL = "_h3_exact_generated_audio_boundary_overlay_v1"
_TAIL_SENTINEL = "_h3_exact_generated_audio_tail_overlay_v1"
BUILD = "H3_EXACT_GENERATED_AUDIO_BOUNDARY_0_6_37_V1"
DECLICK_MILLISECONDS = 5.0


class ExactGeneratedAudioBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactGeneratedAudioBoundaryReport:
    activated: bool
    patched: tuple[str, ...]


def _tail_geometry(value: Any, *, where: str) -> tuple[int, int, int, int]:
    if not isinstance(value, dict):
        raise ExactGeneratedAudioBoundaryError(f"{where} is not a mapping")
    try:
        raw = int(value.get("raw_frames", 0))
        delivered = int(value.get("delivered_frames", 0))
        tail = int(value.get("tail_trim_frames", 0) or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExactGeneratedAudioBoundaryError(
            f"{where} has invalid raw/delivered/tail frame metadata") from exc
    if raw < 1 or delivered < 1 or tail < 0:
        raise ExactGeneratedAudioBoundaryError(
            f"{where} has invalid raw/delivered/tail frames {raw}/{delivered}/{tail}")
    head = raw - delivered - tail
    if head < 0:
        raise ExactGeneratedAudioBoundaryError(
            f"{where} cannot contain {delivered} delivered + {tail} tail frames inside {raw} raw frames")
    return raw, delivered, tail, head


def _signature_prefix(function: Callable[..., Any], expected: tuple[str, ...], *, label: str) -> None:
    try:
        names = tuple(inspect.signature(function).parameters)
    except (TypeError, ValueError) as exc:
        raise ExactGeneratedAudioBoundaryError(f"cannot inspect {label}") from exc
    if names[: len(expected)] != expected:
        raise ExactGeneratedAudioBoundaryError(
            f"refusing exact-audio boundary overlay: {label} signature {names!r} does not begin with {expected!r}")


def _declick_after_boundary(chain_module: Any, waveform: Any, boundary_sample: int,
                            next_end_sample: int, sample_rate: int) -> int:
    """Smooth only the first few ms after a cut; never move audio in time."""
    boundary = int(boundary_sample)
    stop = int(next_end_sample)
    if boundary <= 0 or boundary >= stop:
        return 0
    available = stop - boundary
    wanted = max(2, int(round(int(sample_rate) * DECLICK_MILLISECONDS / 1000.0)))
    count = min(available, wanted)
    if count < 2:
        return 0
    previous = waveform[..., boundary - 1:boundary].clone()
    current = waveform[..., boundary:boundary + count].clone()
    shape = [1] * current.ndim
    shape[-1] = count
    ramp = chain_module.torch.linspace(
        0.0, 1.0, count, device=current.device, dtype=current.dtype
    ).reshape(shape)
    waveform[..., boundary:boundary + count] = previous + (current - previous) * ramp
    return count


def _generated_audio_boundary_safe(chain_module: Any, manifest: dict[str, Any]):
    if chain_module._st_load is None or chain_module.torch is None:
        raise RuntimeError("Exact generated-audio boundary assembly requires safetensors and torch.")
    segments = list(manifest.get("segments") or [])
    if not segments:
        raise ValueError("Exact generated-audio boundary assembly requires at least one scene.")

    sample_rate = None
    records: list[dict[str, Any]] = []
    compatibility = manifest.get("compatibility") or {}
    default_mode = chain_module.migrate_continuation_mode(
        compatibility.get("continuation_mode", "guide"))

    for ordinal, segment in enumerate(segments):
        raw, delivered_frames, tail, head = _tail_geometry(
            segment, where=f"manifest scene {ordinal + 1}")
        checkpoint = chain_module._absolute_output_path(segment["checkpoint"])
        tensors = chain_module._st_load(checkpoint)
        delivered = tensors.get("delivered_audio")
        if delivered is None:
            raise ValueError(
                "Checkpoint for clip %d has no exact delivered audio."
                % int(segment.get("index", ordinal + 1)))
        current_rate = int(segment.get("sample_rate", 0))
        if current_rate <= 0:
            raise ValueError(
                "Checkpoint for clip %d has no audio sample rate."
                % int(segment.get("index", ordinal + 1)))
        if sample_rate is None:
            sample_rate = current_rate
        elif current_rate != sample_rate:
            raise ValueError("Exact generated segment audio sample rates do not match.")

        delivered_expected = chain_module.sample_boundary_from_frames(
            delivered_frames, current_rate, chain_module.FPS)
        if int(delivered.shape[-1]) != delivered_expected:
            raise ValueError(
                "Checkpoint for clip %d has %d delivered audio samples; expected %d for exact %d-frame delivery."
                % (int(segment.get("index", ordinal + 1)), int(delivered.shape[-1]),
                   delivered_expected, delivered_frames))

        mode = chain_module.migrate_continuation_mode(
            segment.get("continuation_mode", default_mode))
        carry = bool(chain_module._audio_policy_uses_generated_continuity(
            manifest, segment))
        overlap = tensors.get("audio_with_overlap")
        if overlap is not None:
            overlap_expected = chain_module.sample_boundary_from_frames(
                raw, current_rate, chain_module.FPS)
            if int(overlap.shape[-1]) != overlap_expected:
                raise ValueError(
                    "Checkpoint for clip %d has %d full-overlap samples; expected %d for %d raw frames."
                    % (int(segment.get("index", ordinal + 1)), int(overlap.shape[-1]),
                       overlap_expected, raw))
            if tuple(overlap.shape[:-1]) != tuple(delivered.shape[:-1]):
                raise ValueError(
                    "Checkpoint for clip %d delivered/full-overlap channel shapes differ."
                    % int(segment.get("index", ordinal + 1)))

        needs_overlap = (
            ordinal > 0
            and carry
            and mode in chain_module.MASKED_CONTINUATION_MODES
            and head > 0
        )
        if needs_overlap and overlap is None:
            raise ValueError(
                "Exact Final Timeline: clip %d carries generated audio through %s with a %d-frame incoming head, but its checkpoint has no private Loop Trim audio overlap."
                % (int(segment.get("index", ordinal + 1)), mode, head))

        records.append({
            "segment": segment,
            "delivered": delivered,
            "overlap": overlap,
            "delivered_frames": delivered_frames,
            "raw_frames": raw,
            "tail_frames": tail,
            "head_frames": head,
            "mode": mode,
            "generated_continuity": carry,
        })

    total_frames = sum(item["delivered_frames"] for item in records)
    total_samples = chain_module.sample_boundary_from_frames(
        total_frames, int(sample_rate), chain_module.FPS)
    first = records[0]["delivered"]
    assembled = chain_module.torch.zeros(
        (*tuple(first.shape[:-1]), total_samples),
        dtype=first.dtype, device=first.device)

    cumulative_frames = 0
    for ordinal, record in enumerate(records):
        segment = record["segment"]
        boundary_frame = cumulative_frames
        end_frame = cumulative_frames + record["delivered_frames"]
        boundary_sample = chain_module.sample_boundary_from_frames(
            boundary_frame, int(sample_rate), chain_module.FPS)
        end_sample = chain_module.sample_boundary_from_frames(
            end_frame, int(sample_rate), chain_module.FPS)

        use_overlap = (
            ordinal > 0
            and record["generated_continuity"]
            and record["mode"] in chain_module.MASKED_CONTINUATION_MODES
            and record["head_frames"] > 0
            and record["overlap"] is not None
        )

        if use_overlap:
            start_frame = boundary_frame - record["head_frames"]
            if start_frame < 0:
                raise ValueError(
                    "Clip %d exact AV overlap begins before the generated timeline."
                    % int(segment.get("index", ordinal + 1)))
            start_sample = chain_module.sample_boundary_from_frames(
                start_frame, int(sample_rate), chain_module.FPS)
            source = record["overlap"]
            budget = end_sample - start_sample
            have = int(source.shape[-1])
            if have > budget:
                source = source[..., :budget]
            elif have < budget:
                source = chain_module.torch.nn.functional.pad(
                    source, (0, budget - have))
            assembled[..., start_sample:end_sample] = source.to(
                device=assembled.device, dtype=assembled.dtype)
            _LOG.info(
                "Exact generated audio: clip %d uses %d-frame genuine generated-audio carry; %d disposable tail frame(s) excluded.",
                int(segment.get("index", ordinal + 1)),
                int(record["head_frames"]), int(record["tail_frames"]))
        else:
            source = record["delivered"]
            if tuple(source.shape[:-1]) != tuple(assembled.shape[:-1]):
                raise ValueError(
                    "Generated clip %d audio channel shape %s does not match %s."
                    % (int(segment.get("index", ordinal + 1)),
                       tuple(source.shape[:-1]), tuple(assembled.shape[:-1])))
            assembled[..., boundary_sample:end_sample] = source.to(
                device=assembled.device, dtype=assembled.dtype)
            if ordinal > 0 and not record["generated_continuity"]:
                smoothed = _declick_after_boundary(
                    chain_module, assembled, boundary_sample, end_sample,
                    int(sample_rate))
                _LOG.info(
                    "Exact generated audio: clip %d starts exactly at authored frame %d; generated continuity off; %d-sample post-boundary de-click ramp applied; no incoming head written early.",
                    int(segment.get("index", ordinal + 1)), boundary_frame, smoothed)

        cumulative_frames = end_frame

    result = {"waveform": assembled, "sample_rate": int(sample_rate)}

    # Prelude ownership is meaningful only when generated continuity is real.
    first_record = records[0]
    if (
        first_record["generated_continuity"]
        and first_record["mode"] in chain_module.MASKED_CONTINUATION_MODES
        and first_record["head_frames"] > 0
        and first_record["overlap"] is not None
    ):
        exact_overlap_frames = (
            first_record["head_frames"] + first_record["delivered_frames"])
        exact_overlap_samples = chain_module.sample_boundary_from_frames(
            exact_overlap_frames, int(sample_rate), chain_module.FPS)
        result.update({
            chain_module.AUDIO_WITH_OVERLAP_WAVEFORM_KEY:
                first_record["overlap"][..., :exact_overlap_samples],
            chain_module.AUDIO_WITH_OVERLAP_FRAMES_KEY: exact_overlap_frames,
            chain_module.AUDIO_TRIM_FRAMES_KEY: first_record["head_frames"],
        })

    return result


def preflight_exact_generated_audio_boundary(chain_module: Any) -> tuple[str, ...]:
    generated = getattr(chain_module, "_generated_audio", None)
    if not callable(generated):
        raise ExactGeneratedAudioBoundaryError("chain_nodes._generated_audio is missing")
    _signature_prefix(generated, ("manifest",), label="chain_nodes._generated_audio")
    if not bool(getattr(generated, _TAIL_SENTINEL, False)):
        raise ExactGeneratedAudioBoundaryError(
            "exact generated-audio tail overlay must activate before boundary overlay")
    for name in (
        "_audio_policy_uses_generated_continuity",
        "MASKED_CONTINUATION_MODES",
        "AUDIO_WITH_OVERLAP_WAVEFORM_KEY",
        "AUDIO_WITH_OVERLAP_FRAMES_KEY",
        "AUDIO_TRIM_FRAMES_KEY",
        "sample_boundary_from_frames",
        "migrate_continuation_mode",
        "FPS",
    ):
        if not hasattr(chain_module, name):
            raise ExactGeneratedAudioBoundaryError(
                f"chain module is missing required exact-audio symbol {name}")
    return ("chain_nodes._generated_audio",)


def activate_exact_generated_audio_boundary(
    chain_module: Any,
) -> ExactGeneratedAudioBoundaryReport:
    preflight_exact_generated_audio_boundary(chain_module)
    existing = getattr(chain_module, _SENTINEL, None)
    if isinstance(existing, ExactGeneratedAudioBoundaryReport):
        return existing

    previous = chain_module._generated_audio

    @wraps(previous)
    def generated_audio(manifest):
        return _generated_audio_boundary_safe(chain_module, manifest)

    generated_audio.__name__ = "_generated_audio_exact_boundary_safe"
    generated_audio._exact_generated_audio_boundary_original = previous
    setattr(generated_audio, _SENTINEL, True)
    chain_module._generated_audio = generated_audio

    report = ExactGeneratedAudioBoundaryReport(
        activated=True,
        patched=("chain_nodes._generated_audio",),
    )
    setattr(chain_module, _SENTINEL, report)
    return report
