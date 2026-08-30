"""Canonicalize deferred Source Timeline PCM windows on exact 24 fps boundaries.

Fool for Love 0.6.37 can see the same source audio twice in different
representations: the live Source Timeline enters Loop Start as a deferred AUDIO
tensor, while recursive/resume state materializes that tensor to a path-backed
asset.  The deferred route historically sliced with ``start_seconds +
duration_seconds`` floating-point arithmetic, whereas the path-backed decoder
uses independent absolute start/end frame boundaries.  At 44.1 kHz those two
expressions can differ by one PCM sample, creating a false
``resume_predecessor_invalid`` even though the scene and source media are
unchanged.

This compatibility layer changes only deferred Source Timeline window slicing.
It keeps the existing validation/error path, then re-slices the already-aligned
tensor using the same absolute video-frame sample boundaries used elsewhere in
the exact-timeline code.
"""

from __future__ import annotations

from typing import Any

BUILD = "FFL_RESUME_SOURCE_PCM_CANONICAL_0_6_37_V1"
_MARKER = "_ffl_resume_source_pcm_canonical_0637"


def activate_resume_source_pcm_canonical(chain_module: Any) -> str:
    current = getattr(chain_module, "_source_timeline_scene_audio", None)
    if getattr(current, _MARKER, False):
        return BUILD
    if not callable(current):
        raise RuntimeError(
            "H3 resume PCM canonicalization needs _source_timeline_scene_audio().")

    original = current

    def frame_exact_source_timeline_scene_audio(
            timeline: Any, source_start: int, source_end: int) -> Any:
        # Preserve all upstream validation and all non-deferred decoding paths.
        baseline = original(timeline, source_start, source_end)
        source = chain_module._validate_source_timeline(
            timeline, require_runtime=True)
        audio = source["audio"]
        if (audio.get("kind") != "deferred_tensor"
                or baseline is None
                or not bool(audio.get("aligned_to_timeline_origin", False))):
            return baseline

        waveform, sample_rate = chain_module._validate_audio(
            audio["value"], "H3 Source Timeline deferred audio")
        start = int(source_start)
        end = int(source_end)
        sample_start = chain_module.sample_boundary_from_frames(
            start, sample_rate, chain_module.FPS)
        sample_end = chain_module.sample_boundary_from_frames(
            end, sample_rate, chain_module.FPS)
        total = int(waveform.shape[-1])

        # The original call above has already validated the frame window. An
        # exact boundary outside the tensor would therefore indicate corrupt
        # Source Timeline metadata rather than something to pad or truncate.
        if (sample_start < 0 or sample_end <= sample_start
                or sample_start >= total or sample_end > total):
            raise ValueError(
                "H3 Source Timeline deferred audio cannot satisfy exact "
                "frame window %d:%d at %d Hz (%d:%d of %d samples)." %
                (start, end, sample_rate, sample_start, sample_end, total))

        return {
            "waveform": waveform[..., sample_start:sample_end],
            "sample_rate": sample_rate,
        }

    setattr(frame_exact_source_timeline_scene_audio, _MARKER, True)
    frame_exact_source_timeline_scene_audio.__wrapped__ = original
    chain_module._source_timeline_scene_audio = (
        frame_exact_source_timeline_scene_audio)
    return BUILD
