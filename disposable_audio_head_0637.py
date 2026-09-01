"""Protect disposable masked-video head audio when generated continuity is off.

Exact Final Timeline may prepend a repeated visual-context head to a raw H3
scene and trim that head after decoding.  When generated-audio continuity is
off, masked_context intentionally leaves the corresponding audio target fully
denoisable.  H3 can therefore begin newly prompted dialogue or effects inside
that hidden head; Loop Trim then removes the beginning of the generated sound.

This MASTER-only overlay preserves the existing policy split:

* generated continuity ON: unchanged; genuine predecessor audio remains copied
  and protected by masked_context;
* generated continuity OFF: the disposable video head receives a protected
  audio guard over the same physical interval, without copying predecessor
  audio and without changing the target audio latent samples;
* locked/source audio: unchanged in content and timing; its pre-existing audio
  mask is already protected, so applying the guard is idempotent.

The guard rounds the video-head duration UP to the next 40 Hz audio-latent tick.
That prevents a new utterance from beginning in the fractional audio tick that
straddles the exact 24 fps delivery boundary.  The authored scene timeline is
never shifted.
"""
from __future__ import annotations

import inspect
import math
from functools import wraps
from typing import Any

BUILD = "H3_MASTER_DISPOSABLE_AUDIO_HEAD_0_6_37_V1"
_MARKER = "_h3_master_disposable_audio_head_0637"


class DisposableAudioHeadError(RuntimeError):
    pass


def _guard_steps(trim_frames: Any, available_audio_steps: Any,
                 fps: Any = 24, audio_hz: Any = 40.0) -> int:
    """Return audio ticks covering the complete disposable video-head span."""
    try:
        trim = int(trim_frames)
        available = int(available_audio_steps)
        fps_value = float(fps)
        audio_rate = float(audio_hz)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DisposableAudioHeadError("invalid disposable-head timing") from exc
    if trim <= 0 or available <= 0:
        return 0
    if not math.isfinite(fps_value) or fps_value <= 0.0:
        raise DisposableAudioHeadError("invalid H3 video frame rate")
    if not math.isfinite(audio_rate) or audio_rate <= 0.0:
        raise DisposableAudioHeadError("invalid H3 audio latent rate")
    # Subtract a tiny epsilon only to keep mathematically integral ratios such
    # as 39*40/24 from becoming 66 because of binary floating-point noise.
    exact = trim * audio_rate / fps_value
    ticks = int(math.ceil(exact - 1e-12))
    return min(available, max(0, ticks))


def activate_disposable_audio_head(masked_module: Any) -> str:
    """Wrap this companion package's masked-prefix helper, never shared core."""
    current = getattr(masked_module, "apply_masked_prefix", None)
    if getattr(current, _MARKER, False):
        return BUILD
    if not callable(current):
        raise DisposableAudioHeadError(
            "masked_context.apply_masked_prefix is unavailable")
    for name in ("_streams_from_latent", "_existing_mask_streams", "FPS", "AUDIO_HZ"):
        if not hasattr(masked_module, name):
            raise DisposableAudioHeadError(
                "masked_context is missing required symbol %s" % name)

    try:
        signature = inspect.signature(current)
    except (TypeError, ValueError) as exc:
        raise DisposableAudioHeadError(
            "cannot inspect masked_context.apply_masked_prefix") from exc
    if "preserve_audio_prefix" not in signature.parameters:
        raise DisposableAudioHeadError(
            "masked_context.apply_masked_prefix has no preserve_audio_prefix argument")

    original = current

    @wraps(original)
    def guarded_apply_masked_prefix(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        preserve_audio_prefix = bool(
            bound.arguments.get("preserve_audio_prefix", True))

        result = original(*args, **kwargs)
        if preserve_audio_prefix:
            # Genuine generated-audio carry owns this head.  Preserve the
            # predecessor audio and every existing feather/mask value exactly.
            return result
        if not isinstance(result, tuple) or len(result) != 3:
            raise DisposableAudioHeadError(
                "apply_masked_prefix returned an unexpected result")

        conditioning, out_latent, trim_frames = result
        trim = int(trim_frames)
        if trim <= 0:
            return result
        if not isinstance(out_latent, dict):
            raise DisposableAudioHeadError(
                "masked prefix returned a non-dict latent")

        streams = list(masked_module._streams_from_latent(out_latent))
        if len(streams) < 2:
            raise DisposableAudioHeadError(
                "masked prefix returned no H3 audio stream")
        video, audio = streams[:2]
        if getattr(video, "ndim", 0) == 4:
            video = video.unsqueeze(0)
        if getattr(audio, "ndim", 0) == 3:
            audio = audio.unsqueeze(0)
        if getattr(audio, "ndim", 0) != 4:
            raise DisposableAudioHeadError(
                "masked prefix audio stream has unexpected shape %s" %
                (tuple(getattr(audio, "shape", ())),))

        video_mask, audio_mask = masked_module._existing_mask_streams(
            out_latent, video, audio)
        available = int(audio_mask.shape[-1])
        guard = _guard_steps(
            trim, available, masked_module.FPS, masked_module.AUDIO_HZ)
        if guard <= 0:
            return result

        # Do not replace or zero audio samples.  For an ordinary generated H3
        # target this protects the stock empty/zero audio latent; for locked
        # source audio it simply preserves the already-authoritative samples.
        # Only the hidden raw head becomes non-denoisable.
        audio_mask[..., :guard] = 0.0

        import comfy.nested_tensor

        guarded_latent = out_latent.copy()
        guarded_latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (video_mask, audio_mask))

        logger = getattr(masked_module, "_LOG", None)
        if logger is not None:
            logger.info(
                "h3_masked_prefix: protected %d disposable audio tick(s) for "
                "%d-frame hidden video head; generated continuity remains off",
                guard, trim)
        return conditioning, guarded_latent, trim_frames

    setattr(guarded_apply_masked_prefix, _MARKER, True)
    guarded_apply_masked_prefix.__wrapped__ = original
    masked_module.apply_masked_prefix = guarded_apply_masked_prefix
    return BUILD
