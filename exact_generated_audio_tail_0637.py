"""Exact-safe generated-audio assembly for H3 0.6.37 exact timelines.

The Exact Final Timeline V1 guard correctly prevented RAW H3 tail padding from
entering a final generated soundtrack, but its original implementation had to
block every generated-audio export as soon as one scene carried
``tail_trim_frames > 0``.

Runtime evidence now gives us a stronger invariant:

* Segment Save receives a frame-exact ``delivered_audio`` waveform after Loop
  Trim and the exact-timeline wrapper crops it to ``delivered_frames``.
* Loop Trim also carries a private full decoded audio window for AV overlap.
  That window contains: repeated head + delivered scene + disposable H3 tail.
* The disposable tail is always at the END of that private window.

This overlay keeps the fail-closed continuation rules intact while making
final generated-audio assembly exact-safe:

1. Preserve Loop Trim's private full overlap through the exact Segment Save
   wrapper. A transient compatibility trim value is supplied only to the old
   0.6.37 Segment Save validator; it is not persisted as authored timing.
2. Assemble delivered audio on absolute video-frame sample boundaries.
3. For masked-AV joins, later-scene overlap ownership uses only
   ``head_context + delivered_frames`` samples. ``tail_trim_frames`` are never
   copied into the final soundtrack.
4. A masked-AV scene that needs a repeated head but has no saved private
   overlap fails closed instead of silently falling back to a hard audio cut.

RAW sampler/checkpoint latents remain immutable. This module does not weaken
live/resume continuation sanitation.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable


_LOG = logging.getLogger("minimax_h3_context_loop.exact_generated_audio")
_SENTINEL = "_h3_exact_generated_audio_tail_overlay_v1"
BUILD = "H3_EXACT_GENERATED_AUDIO_TAIL_0_6_37_V1"


class ExactGeneratedAudioTailError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactGeneratedAudioTailReport:
    activated: bool
    patched: tuple[str, ...]


def _private_audio_keys(chain_module: Any) -> tuple[str, str, str]:
    return (
        str(chain_module.AUDIO_WITH_OVERLAP_WAVEFORM_KEY),
        str(chain_module.AUDIO_WITH_OVERLAP_FRAMES_KEY),
        str(chain_module.AUDIO_TRIM_FRAMES_KEY),
    )


def _tail_geometry(value: Any, *, where: str) -> tuple[int, int, int, int]:
    if not isinstance(value, dict):
        raise ExactGeneratedAudioTailError(f"{where} is not a mapping")
    try:
        raw = int(value.get("raw_frames", 0))
        delivered = int(value.get("delivered_frames", 0))
        tail = int(value.get("tail_trim_frames", 0) or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExactGeneratedAudioTailError(
            f"{where} has invalid raw/delivered/tail frame metadata"
        ) from exc
    if raw < 1 or delivered < 1 or tail < 0:
        raise ExactGeneratedAudioTailError(
            f"{where} has invalid raw/delivered/tail frames "
            f"{raw}/{delivered}/{tail}"
        )
    head = raw - delivered - tail
    if head < 0:
        raise ExactGeneratedAudioTailError(
            f"{where} cannot contain {delivered} delivered + {tail} tail "
            f"frames inside {raw} raw frames"
        )
    return raw, delivered, tail, head


def _signature_prefix(
    function: Callable[..., Any], expected: tuple[str, ...], *, label: str,
) -> None:
    try:
        names = tuple(inspect.signature(function).parameters)
    except (TypeError, ValueError) as exc:
        raise ExactGeneratedAudioTailError(f"cannot inspect {label}") from exc
    if names[: len(expected)] != expected:
        raise ExactGeneratedAudioTailError(
            f"refusing generated-audio overlay: {label} signature {names!r} "
            f"does not begin with {expected!r}"
        )


def _wrap_trim_audio_to_frames(original: Callable[..., Any], chain_module: Any):
    if getattr(original, _SENTINEL, False):
        return original
    waveform_key, frames_key, trim_key = _private_audio_keys(chain_module)

    @wraps(original)
    def trim_audio_to_frames(audio: Any, frames: int):
        result = original(audio, frames)
        if not isinstance(audio, dict) or not isinstance(result, dict):
            return result
        present = [key in audio for key in (waveform_key, frames_key, trim_key)]
        if any(present) and not all(present):
            raise ExactGeneratedAudioTailError(
                "Exact delivered audio received incomplete private Loop Trim "
                "overlap metadata"
            )
        if all(present):
            result = dict(result)
            result[waveform_key] = audio[waveform_key]
            result[frames_key] = audio[frames_key]
            result[trim_key] = audio[trim_key]
        return result

    setattr(trim_audio_to_frames, _SENTINEL, True)
    trim_audio_to_frames._exact_generated_audio_original = original
    return trim_audio_to_frames


def _wrap_segment_save(original: Callable[..., Any], chain_module: Any):
    if getattr(original, _SENTINEL, False):
        return original
    waveform_key, frames_key, trim_key = _private_audio_keys(chain_module)

    @wraps(original)
    def save(
        self, state, images, sampled_latent, audio=None,
        images_with_overlap=None, denoised_latent=None,
        prompt=None, extra_pnginfo=None,
    ):
        adjusted_audio = audio
        if isinstance(audio, dict):
            present = [key in audio for key in (waveform_key, frames_key, trim_key)]
            if any(present) and not all(present):
                raise ExactGeneratedAudioTailError(
                    "Segment Save received incomplete private Loop Trim overlap "
                    "metadata"
                )
            if all(present):
                try:
                    index = int(state["index"])
                    shot = state["plan"]["shots"][index - 1]
                except (KeyError, TypeError, ValueError, IndexError) as exc:
                    raise ExactGeneratedAudioTailError(
                        "Segment Save cannot resolve current exact scene timing"
                    ) from exc
                raw, delivered, tail, head = _tail_geometry(
                    shot, where=f"scene {index}"
                )
                try:
                    overlap_frames = int(audio[frames_key])
                    overlap_trim = int(audio[trim_key])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ExactGeneratedAudioTailError(
                        f"scene {index} has invalid Loop Trim overlap metadata"
                    ) from exc
                if overlap_frames != raw:
                    raise ExactGeneratedAudioTailError(
                        f"scene {index} Loop Trim overlap describes "
                        f"{overlap_frames} frames; expected raw {raw}"
                    )
                if overlap_trim != head:
                    raise ExactGeneratedAudioTailError(
                        f"scene {index} Loop Trim removed {overlap_trim} head "
                        f"frames; exact timing requires {head}"
                    )
                # The stock 0.6.37 Segment Save validator knows only
                # raw-delivered and therefore counts disposable tail as if it
                # were repeated head. Feed that validator its legacy number so
                # it will persist the full overlap tensor. The value itself is
                # not checkpointed; exact final assembly below recomputes the
                # real head from raw-delivered-tail.
                adjusted_audio = dict(audio)
                adjusted_audio[trim_key] = raw - delivered
                if tail:
                    _LOG.info(
                        "Exact Final Timeline scene %d preserves full decoded "
                        "audio overlap for final assembly: head %df, delivered "
                        "%df, disposable tail %df.",
                        index, head, delivered, tail,
                    )

        return original(
            self, state, images, sampled_latent, audio=adjusted_audio,
            images_with_overlap=images_with_overlap,
            denoised_latent=denoised_latent,
            prompt=prompt, extra_pnginfo=extra_pnginfo,
        )

    setattr(save, _SENTINEL, True)
    save._exact_generated_audio_original = original
    return save


def _generated_audio_exact_safe(chain_module: Any, manifest: dict[str, Any]):
    if chain_module._st_load is None or chain_module.torch is None:
        raise RuntimeError(
            "Exact generated-audio assembly requires safetensors and torch."
        )
    segments = list(manifest.get("segments") or [])
    if not segments:
        raise ValueError(
            "Exact generated-audio assembly requires at least one scene."
        )

    sample_rate = None
    records: list[dict[str, Any]] = []
    compatibility = manifest.get("compatibility") or {}
    default_mode = chain_module.migrate_continuation_mode(
        compatibility.get("continuation_mode", "guide")
    )

    for ordinal, segment in enumerate(segments):
        raw, delivered_frames, tail, head = _tail_geometry(
            segment, where=f"manifest scene {ordinal + 1}"
        )
        checkpoint = chain_module._absolute_output_path(segment["checkpoint"])
        tensors = chain_module._st_load(checkpoint)
        waveform = tensors.get("delivered_audio")
        if waveform is None:
            raise ValueError(
                "Checkpoint for clip %d has no exact delivered audio. Wire "
                "decoded audio through Loop Trim and Segment Save."
                % int(segment.get("index", ordinal + 1))
            )
        current_rate = int(segment.get("sample_rate", 0))
        if current_rate <= 0:
            raise ValueError(
                "Checkpoint for clip %d has no audio sample rate."
                % int(segment.get("index", ordinal + 1))
            )
        if sample_rate is None:
            sample_rate = current_rate
        elif current_rate != sample_rate:
            raise ValueError(
                "Exact generated segment audio sample rates do not match."
            )

        expected = chain_module.sample_boundary_from_frames(
            delivered_frames, current_rate, chain_module.FPS
        )
        if int(waveform.shape[-1]) != expected:
            raise ValueError(
                "Checkpoint for clip %d has %d delivered audio samples; "
                "expected %d for exact %d-frame delivery."
                % (
                    int(segment.get("index", ordinal + 1)),
                    int(waveform.shape[-1]), expected, delivered_frames,
                )
            )

        mode = chain_module.migrate_continuation_mode(
            segment.get("continuation_mode", default_mode)
        )
        overlap = tensors.get("audio_with_overlap")
        if overlap is not None:
            overlap_expected = chain_module.sample_boundary_from_frames(
                raw, current_rate, chain_module.FPS
            )
            if int(overlap.shape[-1]) != overlap_expected:
                raise ValueError(
                    "Checkpoint for clip %d has %d full-overlap samples; "
                    "expected %d for %d raw frames."
                    % (
                        int(segment.get("index", ordinal + 1)),
                        int(overlap.shape[-1]), overlap_expected, raw,
                    )
                )
            if tuple(overlap.shape[:-1]) != tuple(waveform.shape[:-1]):
                raise ValueError(
                    "Checkpoint for clip %d delivered/full-overlap channel "
                    "shapes differ."
                    % int(segment.get("index", ordinal + 1))
                )

        # For an incoming masked-AV boundary, using delivered-only audio is
        # timeline-safe but produces a hard cut. New exact checkpoints must
        # retain the full private overlap so the final master is not silently
        # degraded.
        if (
            ordinal > 0
            and mode in chain_module.MASKED_CONTINUATION_MODES
            and head > 0
            and overlap is None
        ):
            raise ValueError(
                "Exact Final Timeline: clip %d uses %s with a %d-frame "
                "incoming head but its checkpoint has no private Loop Trim "
                "audio overlap. Re-render this scene with the current exact "
                "Segment Save; final assembly refuses a legacy hard audio cut."
                % (
                    int(segment.get("index", ordinal + 1)), mode, head,
                )
            )

        records.append({
            "segment": segment,
            "delivered": waveform,
            "overlap": overlap,
            "delivered_frames": delivered_frames,
            "raw_frames": raw,
            "tail_frames": tail,
            "head_frames": head,
            "mode": mode,
        })

    total_frames = sum(item["delivered_frames"] for item in records)
    total_samples = chain_module.sample_boundary_from_frames(
        total_frames, int(sample_rate), chain_module.FPS
    )
    first = records[0]["delivered"]
    assembled = chain_module.torch.zeros(
        (*tuple(first.shape[:-1]), total_samples),
        dtype=first.dtype, device=first.device,
    )

    cumulative_frames = 0
    for ordinal, record in enumerate(records):
        segment = record["segment"]
        source = record["delivered"]
        start_frame = cumulative_frames
        use_overlap = (
            ordinal > 0
            and record["mode"] in chain_module.MASKED_CONTINUATION_MODES
            and record["head_frames"] > 0
            and record["overlap"] is not None
        )
        if use_overlap:
            source = record["overlap"]
            start_frame -= record["head_frames"]
            if start_frame < 0:
                raise ValueError(
                    "Clip %d exact AV overlap begins before the generated "
                    "timeline."
                    % int(segment.get("index", ordinal + 1))
                )
            _LOG.info(
                "Exact generated audio: clip %d owns %d incoming head frames; "
                "%d disposable raw tail frame(s) are excluded from the write "
                "budget.",
                int(segment.get("index", ordinal + 1)),
                int(record["head_frames"]), int(record["tail_frames"]),
            )

        end_frame = cumulative_frames + record["delivered_frames"]
        start_sample = chain_module.sample_boundary_from_frames(
            start_frame, int(sample_rate), chain_module.FPS
        )
        end_sample = chain_module.sample_boundary_from_frames(
            end_frame, int(sample_rate), chain_module.FPS
        )
        budget = end_sample - start_sample
        have = int(source.shape[-1])
        if have > budget:
            source = source[..., :budget]
        elif have < budget:
            source = chain_module.torch.nn.functional.pad(
                source, (0, budget - have)
            )
        if tuple(source.shape[:-1]) != tuple(assembled.shape[:-1]):
            raise ValueError(
                "Generated clip %d audio channel shape %s does not match %s."
                % (
                    int(segment.get("index", ordinal + 1)),
                    tuple(source.shape[:-1]), tuple(assembled.shape[:-1]),
                )
            )
        assembled[..., start_sample:end_sample] = source.to(
            device=assembled.device, dtype=assembled.dtype
        )
        cumulative_frames = end_frame

    result = {"waveform": assembled, "sample_rate": int(sample_rate)}

    # Existing Video Context can prepend scene 1. Preserve only the exact
    # head+delivered portion of its private overlap; the raw H3 tail is cropped
    # before _audio_with_prelude ever sees it.
    first_record = records[0]
    if (
        first_record["mode"] in chain_module.MASKED_CONTINUATION_MODES
        and first_record["head_frames"] > 0
        and first_record["overlap"] is not None
    ):
        exact_overlap_frames = (
            first_record["head_frames"] + first_record["delivered_frames"]
        )
        exact_overlap_samples = chain_module.sample_boundary_from_frames(
            exact_overlap_frames, int(sample_rate), chain_module.FPS
        )
        waveform_key, frames_key, trim_key = _private_audio_keys(chain_module)
        result.update({
            waveform_key: first_record["overlap"][..., :exact_overlap_samples],
            frames_key: exact_overlap_frames,
            trim_key: first_record["head_frames"],
        })

    return result


def preflight_exact_generated_audio_tail(
    chain_module: Any, exact_module: Any,
) -> tuple[str, ...]:
    segment_cls = getattr(chain_module, "MiniMaxH3ChainSegmentSave", None)
    if not isinstance(segment_cls, type):
        raise ExactGeneratedAudioTailError("MiniMaxH3ChainSegmentSave is missing")
    save = getattr(segment_cls, "save", None)
    generated = getattr(chain_module, "_generated_audio", None)
    trim = getattr(exact_module, "_trim_audio_to_frames", None)
    if not callable(save) or not callable(generated) or not callable(trim):
        raise ExactGeneratedAudioTailError(
            "exact generated-audio owners are missing"
        )
    _signature_prefix(
        save,
        ("self", "state", "images", "sampled_latent", "audio"),
        label="MiniMaxH3ChainSegmentSave.save",
    )
    _signature_prefix(
        trim, ("audio", "frames"), label="exact _trim_audio_to_frames"
    )
    for name in (
        "AUDIO_WITH_OVERLAP_WAVEFORM_KEY",
        "AUDIO_WITH_OVERLAP_FRAMES_KEY",
        "AUDIO_TRIM_FRAMES_KEY",
        "MASKED_CONTINUATION_MODES",
        "sample_boundary_from_frames",
        "migrate_continuation_mode",
        "FPS",
    ):
        if not hasattr(chain_module, name):
            raise ExactGeneratedAudioTailError(
                f"chain module is missing required exact-audio symbol {name}"
            )
    return (
        "MiniMaxH3ChainSegmentSave.save",
        "exact_final_timeline._trim_audio_to_frames",
        "chain_nodes._generated_audio",
    )


def activate_exact_generated_audio_tail(
    chain_module: Any, exact_module: Any,
) -> ExactGeneratedAudioTailReport:
    preflight_exact_generated_audio_tail(chain_module, exact_module)
    existing = getattr(chain_module, _SENTINEL, None)
    if isinstance(existing, ExactGeneratedAudioTailReport):
        return existing

    exact_module._trim_audio_to_frames = _wrap_trim_audio_to_frames(
        exact_module._trim_audio_to_frames, chain_module
    )
    chain_module.MiniMaxH3ChainSegmentSave.save = _wrap_segment_save(
        chain_module.MiniMaxH3ChainSegmentSave.save, chain_module
    )

    previous_generated_audio = chain_module._generated_audio

    def generated_audio(manifest):
        return _generated_audio_exact_safe(chain_module, manifest)

    generated_audio.__name__ = "_generated_audio_exact_tail_safe"
    generated_audio._exact_generated_audio_original = previous_generated_audio
    setattr(generated_audio, _SENTINEL, True)
    chain_module._generated_audio = generated_audio

    report = ExactGeneratedAudioTailReport(
        activated=True,
        patched=(
            "MiniMaxH3ChainSegmentSave.save",
            "exact_final_timeline._trim_audio_to_frames",
            "chain_nodes._generated_audio",
        ),
    )
    setattr(chain_module, _SENTINEL, report)
    return report
