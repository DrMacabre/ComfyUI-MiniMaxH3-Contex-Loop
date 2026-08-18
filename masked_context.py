"""Masked target-prefix continuation for recursive MiniMax H3 chains.

Generated scenes continue directly from the previous sampled H3 video/audio
latent tails, avoiding a lossy video decode/re-encode round trip.  Imported
scene-1 video and audio still use their respective VAEs because no sampled H3
latent exists yet.  A nested AV denoise mask protects the copied prefix while
the sampler generates only the future portion.

The mask design follows ComfyUI PR #15375 and seitanism's GPL-3.0
ComfyUI-H3-Motion-Context-MultiRef masked-extension work.  Runtime support is
enabled lazily so ordinary guide-mode chains do not patch H3 mask handling.
"""

from __future__ import annotations

import logging

import torch

from .nodes import (
    AV_RUN_GRID,
    AUDIO_HZ,
    FPS,
    _audio_tail_from_latent,
    _pixel_frames,
    _resize,
    _streams_from_latent,
)


_LOG = logging.getLogger("minimax_h3_context_loop.masked_prefix")


def _require_h3_mask_support():
    """Compatibility alias retained for focused tests and chain callers."""
    from .masking_support import require_h3_mask_support

    return require_h3_mask_support("masked AV continuation")


def _snap_prefix_length(requested, available, target_frames):
    """Resolve a context window to a shared H3 video/audio boundary."""
    cap = min(int(requested), int(available), int(target_frames) - 1)
    run = next((value for value in AV_RUN_GRID if value <= cap), 0)
    if run < 39:
        raise ValueError(
            "h3_masked_prefix: masked continuation needs at least 39 previous "
            "frames, a target longer than the prefix, and an exact shared "
            "video/audio boundary."
        )
    if run != int(requested):
        _LOG.warning(
            "h3_masked_prefix: context_length %d -> exact H3 prefix %d "
            "(exact shared AV runs are 39, 90, 141, 192, and 243)",
            int(requested), run,
        )
    return run


def _validate_target_streams(latent, strict_audio_grid=True):
    video, audio = _streams_from_latent(latent)[:2]
    if video.ndim == 4:
        video = video.unsqueeze(0)
    if audio.ndim == 3:
        audio = audio.unsqueeze(0)
    if video.ndim != 5:
        raise ValueError(
            "h3_masked_prefix: video latent must be [B,C,T,H,W], got %s" %
            (tuple(video.shape),)
        )
    if audio.ndim != 4:
        raise ValueError(
            "h3_masked_prefix: audio latent must be [B,C,2,T], got %s" %
            (tuple(audio.shape),)
        )
    if int(video.shape[0]) != 1 or int(audio.shape[0]) != 1:
        raise ValueError(
            "h3_masked_prefix: masked continuation supports H3 batch size 1."
        )
    target_frames = _pixel_frames(int(video.shape[2]))
    expected_audio = int(round(target_frames / float(FPS) * AUDIO_HZ))
    if int(audio.shape[-1]) != expected_audio:
        message = (
            "h3_masked_prefix: target latent has %d audio steps for %d video "
            "frames; expected %d on H3's nominal 40 Hz grid." %
            (int(audio.shape[-1]), target_frames, expected_audio)
        )
        if strict_audio_grid:
            raise RuntimeError(message)
        _LOG.warning("%s The target audio length is authoritative.", message)
    return video, audio, target_frames


def _generated_video_tail(previous_latent, frames, target_video):
    """Copy a phase-aligned video prefix from a generated H3 AV latent."""
    parts = _streams_from_latent(previous_latent)
    if len(parts) < 2:
        raise ValueError(
            "h3_masked_prefix: previous sampled latent has no audio stream. "
            "Wire the joint H3 AV sampler output, not a video-only latent."
        )
    source_video, source_audio = parts[:2]
    if source_video.ndim == 4:
        source_video = source_video.unsqueeze(0)
    if source_audio.ndim == 3:
        source_audio = source_audio.unsqueeze(0)
    if source_video.ndim != 5:
        raise ValueError(
            "h3_masked_prefix: previous video latent must be [B,C,T,H,W], "
            "got %s." % (tuple(source_video.shape),)
        )
    if source_audio.ndim != 4:
        raise ValueError(
            "h3_masked_prefix: previous audio latent must be [B,C,2,T], got "
            "%s." % (tuple(source_audio.shape),)
        )
    if int(source_video.shape[0]) != 1 or int(source_audio.shape[0]) != 1:
        raise ValueError(
            "h3_masked_prefix: generated-latent continuation supports H3 "
            "batch size 1."
        )

    # Valid H3 prefix runs 5/22/39/... map to 2/7/12/... latent steps. Full
    # H3 clips and these prefixes are both 2 mod 5 latent steps, so slicing the
    # source tail and placing it at target step zero preserves temporal phase.
    video_steps = 2 + 5 * ((int(frames) - 5) // 17)
    if _pixel_frames(video_steps) != int(frames):
        raise RuntimeError(
            "h3_masked_prefix: internal H3 context mapping failed for %d "
            "frames." % int(frames)
        )
    if int(source_video.shape[2]) < video_steps:
        raise ValueError(
            "h3_masked_prefix: previous sampled latent has too few video "
            "steps for the %d-frame context." % int(frames)
        )
    if tuple(source_video.shape[1:2] + source_video.shape[3:]) != tuple(
            target_video.shape[1:2] + target_video.shape[3:]):
        raise ValueError(
            "h3_masked_prefix: previous/target video latent geometry differs: "
            "%s vs %s. Keep chained clips at the same H3 resolution." %
            (tuple(source_video.shape), tuple(target_video.shape))
        )
    return source_video[:1, :, -video_steps:].clone(), video_steps


def _encoded_video_tail(vae, previous_frames, frames, target_video, crop):
    """Encode an imported decoded-video tail when no H3 source latent exists."""
    if getattr(previous_frames, "ndim", 0) != 4:
        raise ValueError(
            "h3_masked_prefix: imported previous frames must be IMAGE "
            "[N,H,W,C]."
        )
    available = int(previous_frames.shape[0])
    if available < int(frames):
        raise ValueError(
            "h3_masked_prefix: imported video has %d frames but the resolved "
            "prefix needs %d." % (available, int(frames))
        )
    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16
    video_tail = _resize(
        previous_frames[available - int(frames):], width, height, crop)
    video_prefix = vae.encode(video_tail)
    if getattr(video_prefix, "ndim", 0) != 5:
        raise ValueError(
            "h3_masked_prefix: video VAE returned %s; expected "
            "[B,C,T,H,W]." %
            (tuple(getattr(video_prefix, "shape", ())),)
        )
    video_steps = int(video_prefix.shape[2])
    covered = _pixel_frames(video_steps)
    if covered != int(frames):
        raise RuntimeError(
            "h3_masked_prefix: %d imported context frames encoded to %d "
            "video steps covering %d frames; refusing a phase-shifted seam." %
            (int(frames), video_steps, covered)
        )
    return video_prefix, video_steps


def _encode_imported_audio(audio_vae, audio, frames):
    if audio_vae is None:
        raise ValueError(
            "h3_masked_prefix: imported-video scene 1 needs the H3 audio VAE "
            "connected to Chain Context."
        )
    if audio is None:
        raise ValueError(
            "h3_masked_prefix: imported-video scene 1 has no context audio. "
            "Reconnect source audio to Existing Video Context."
        )
    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if sample_rate != vae_rate:
        try:
            import torchaudio
        except ImportError as exc:
            raise RuntimeError(
                "h3_masked_prefix: imported audio is %d Hz but the H3 audio "
                "VAE wants %d Hz and torchaudio is unavailable." %
                (sample_rate, vae_rate)
            ) from exc
        waveform = torchaudio.functional.resample(
            waveform, sample_rate, vae_rate)
    wanted = int(round(int(frames) / float(FPS) * vae_rate))
    if int(waveform.shape[-1]) < wanted:
        raise ValueError(
            "h3_masked_prefix: imported context audio is shorter than the "
            "%d-frame masked prefix." % int(frames)
        )
    encoded = audio_vae.encode(waveform[:1, ..., -wanted:].movedim(1, -1))
    if getattr(encoded, "ndim", 0) != 4:
        raise ValueError(
            "h3_masked_prefix: audio VAE returned %s; expected [B,C,2,T]." %
            (tuple(getattr(encoded, "shape", ())),)
        )
    steps = int(round(int(frames) / float(FPS) * AUDIO_HZ))
    if int(encoded.shape[-1]) < steps:
        raise RuntimeError(
            "h3_masked_prefix: %d frames need %d audio steps but the audio "
            "VAE produced %d." % (int(frames), steps, int(encoded.shape[-1]))
        )
    return encoded[:1, ..., -steps:], steps, "imported decoded audio"


def _existing_mask_streams(latent, video, audio):
    mask = latent.get("noise_mask")
    if mask is None:
        return (
            torch.ones(
                (1, 1, int(video.shape[2]), int(video.shape[3]),
                 int(video.shape[4])),
                device=video.device, dtype=torch.float32,
            ),
            torch.ones(
                (1, 1, int(audio.shape[2]), int(audio.shape[3])),
                device=audio.device, dtype=torch.float32,
            ),
        )
    if hasattr(mask, "unbind"):
        parts = list(mask.unbind())
    elif isinstance(mask, (tuple, list)):
        parts = list(mask)
    else:
        raise ValueError(
            "h3_masked_prefix: an existing target noise_mask is not a nested "
            "H3 video/audio mask and cannot be composed safely."
        )
    if len(parts) < 2:
        raise ValueError(
            "h3_masked_prefix: existing target noise_mask has no audio stream."
        )
    video_mask, audio_mask = parts[:2]
    if video_mask.ndim == 4:
        video_mask = video_mask.unsqueeze(0)
    if audio_mask.ndim == 3:
        audio_mask = audio_mask.unsqueeze(0)
    expected_video = (1, 1, int(video.shape[2]), int(video.shape[3]),
                      int(video.shape[4]))
    expected_audio = (1, 1, int(audio.shape[2]), int(audio.shape[3]))
    try:
        video_mask = torch.broadcast_to(video_mask, expected_video).clone()
        audio_mask = torch.broadcast_to(audio_mask, expected_audio).clone()
    except RuntimeError as exc:
        raise ValueError(
            "h3_masked_prefix: existing AV noise-mask shapes %s / %s cannot "
            "broadcast to target %s / %s." %
            (tuple(video_mask.shape), tuple(audio_mask.shape), expected_video,
             expected_audio)
        ) from exc
    return video_mask.float(), audio_mask.float()


def _feather_preserved_prefix(video_mask, audio_mask, video_steps, audio_steps):
    """Apply a narrow, high-denoise handoff at a protected AV tail."""
    video_steps = int(video_steps)
    audio_steps = int(audio_steps)
    video_feather = min(4, max(0, video_steps - 1))
    if video_feather < 1:
        video_mask[:, :, :video_steps] = 0.0
        audio_mask[..., :audio_steps] = 0.0
        return 0, 0
    # Fractional H3 masks are most useful close to full denoise.  Keep the
    # accepted prefix exact until the final four video-latent steps, then
    # give the model a deliberately narrow 0.85..0.95 reconstruction band.
    # Audio uses its own shorter 200 ms ramp instead of inheriting the much
    # wider video-to-audio grid conversion, which used to start the audible
    # handoff roughly 575 ms before the prefix boundary.
    audio_feather = min(max(0, audio_steps - 1), 8)
    video_ramp = torch.linspace(
        0.85, 0.95, video_feather,
        device=video_mask.device, dtype=video_mask.dtype,
    )
    video_hard_steps = video_steps - video_feather
    video_mask[:, :, :video_hard_steps] = 0.0
    video_mask[:, :, video_hard_steps:video_steps] = torch.minimum(
        video_mask[:, :, video_hard_steps:video_steps],
        video_ramp.view(1, 1, video_feather, 1, 1),
    )
    if audio_feather:
        audio_ramp = torch.linspace(
            0.85, 0.95, audio_feather,
            device=audio_mask.device, dtype=audio_mask.dtype,
        )
        audio_hard_steps = audio_steps - audio_feather
        audio_mask[..., :audio_hard_steps] = 0.0
        audio_mask[..., audio_hard_steps:audio_steps] = torch.minimum(
            audio_mask[..., audio_hard_steps:audio_steps],
            audio_ramp.view(1, 1, 1, audio_feather),
        )
    return video_feather, audio_feather


def _audio_feather_preserved_prefix(
    video_mask, audio_mask, video_steps, audio_steps,
):
    """Keep picture exact and release only the final audio-prefix ticks."""
    video_steps = int(video_steps)
    audio_steps = int(audio_steps)
    video_mask[:, :, :video_steps] = 0.0
    audio_feather = min(8, max(0, audio_steps))
    audio_hard_steps = audio_steps - audio_feather
    audio_mask[..., :audio_hard_steps] = 0.0
    if audio_feather:
        indices = torch.arange(
            1, audio_feather + 1,
            device=audio_mask.device, dtype=audio_mask.dtype,
        )
        audio_ramp = 0.5 - 0.5 * torch.cos(
            torch.pi * indices / float(audio_feather))
        audio_mask[..., audio_hard_steps:audio_steps] = torch.minimum(
            audio_mask[..., audio_hard_steps:audio_steps],
            audio_ramp.view(1, 1, 1, audio_feather),
        )
    return audio_feather


def _drop_prefix_guides(conditioning, prefix_frames):
    """Remove target guides that conflict with the preserved latent prefix."""
    out = []
    dropped = []
    for embedding, extra in conditioning:
        metadata = extra.copy()
        kept = []
        for guide in metadata.get("minimax_keyframes") or []:
            position = float(guide.get(
                "resolved_frame_index", guide.get("frame_index", 0)))
            if 0 <= position < int(prefix_frames):
                dropped.append(position)
            else:
                kept.append(guide)
        if "minimax_keyframes" in metadata:
            metadata["minimax_keyframes"] = kept
        out.append([embedding, metadata])
    if dropped:
        _LOG.warning(
            "h3_masked_prefix: dropped %d target guide(s) inside preserved "
            "frames 0..%d; the clean target latent already owns that prefix.",
            len(dropped), int(prefix_frames) - 1,
        )
    return out


def apply_masked_prefix(
    conditioning,
    vae,
    latent,
    previous_frames,
    context_length,
    crop,
    previous_latent=None,
    audio_vae=None,
    previous_audio=None,
    temporal_feather=False,
    audio_only_feather=False,
    preserve_audio_prefix=True,
):
    """Return conditioning, masked target latent, and repeated trim length."""
    _require_h3_mask_support()
    target_video, target_audio, target_frames = _validate_target_streams(latent)
    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16

    if previous_latent is not None:
        source_video = _streams_from_latent(previous_latent)[0]
        if source_video.ndim == 4:
            source_video = source_video.unsqueeze(0)
        if source_video.ndim != 5:
            raise ValueError(
                "h3_masked_prefix: previous video latent must be "
                "[B,C,T,H,W], got %s." % (tuple(source_video.shape),)
            )
        available = _pixel_frames(int(source_video.shape[2]))
        frames = _snap_prefix_length(
            context_length, available, target_frames)
        video_prefix, video_steps = _generated_video_tail(
            previous_latent, frames, target_video)
        video_source = "previous sampled latent"
    else:
        if getattr(previous_frames, "ndim", 0) != 4:
            raise ValueError(
                "h3_masked_prefix: imported previous frames must be IMAGE "
                "[N,H,W,C]."
            )
        available = int(previous_frames.shape[0])
        frames = _snap_prefix_length(
            context_length, available, target_frames)
        video_prefix, video_steps = _encoded_video_tail(
            vae, previous_frames, frames, target_video, crop)
        video_source = "imported decoded frames via video VAE"
    if video_steps >= int(target_video.shape[2]):
        raise ValueError(
            "h3_masked_prefix: video prefix consumes the whole target latent."
        )

    if not bool(preserve_audio_prefix):
        audio_prefix = None
        audio_steps = 0
        audio_source = "open target (generated continuity off)"
    elif previous_latent is not None:
        audio_prefix, audio_steps, overhang = _audio_tail_from_latent(
            previous_latent, frames)
        audio_source = "previous sampled latent"
        if abs(overhang) > 1e-9:
            _LOG.warning(
                "h3_masked_prefix: predecessor audio grid ends %.3f latent "
                "steps from its last video frame; the copied %d-step prefix "
                "is end-aligned. Use 39/90/141/... context frames for an exact "
                "prefix duration.",
                overhang, audio_steps,
            )
    else:
        audio_prefix, audio_steps, audio_source = _encode_imported_audio(
            audio_vae, previous_audio, frames)
    if bool(preserve_audio_prefix):
        expected_audio_steps = int(round(frames / float(FPS) * AUDIO_HZ))
        if audio_steps != expected_audio_steps:
            raise RuntimeError(
                "h3_masked_prefix: %d video frames require %d audio steps, "
                "got %d." % (frames, expected_audio_steps, audio_steps)
            )
        if audio_steps >= int(target_audio.shape[-1]):
            raise ValueError(
                "h3_masked_prefix: audio prefix consumes the whole target "
                "latent.")

    out_video = target_video.clone()
    out_audio = target_audio.clone()
    vp = video_prefix[:1].to(out_video.device, out_video.dtype)
    ap = (audio_prefix[:1].to(out_audio.device, out_audio.dtype)
          if audio_prefix is not None else None)
    if (int(vp.shape[1]) != int(out_video.shape[1])
            or tuple(vp.shape[3:]) != tuple(out_video.shape[3:])):
        raise ValueError(
            "h3_masked_prefix: encoded video prefix shape %s does not match "
            "target %s." % (tuple(vp.shape), tuple(out_video.shape))
        )
    if ap is not None and tuple(ap.shape[1:3]) != tuple(out_audio.shape[1:3]):
        raise ValueError(
            "h3_masked_prefix: audio prefix shape %s does not match target %s."
            % (tuple(ap.shape), tuple(out_audio.shape))
        )
    out_video[:, :, :video_steps] = vp
    if ap is not None:
        out_audio[..., :audio_steps] = ap

    video_mask, audio_mask = _existing_mask_streams(
        latent, out_video, out_audio)
    video_feather_steps = audio_feather_steps = 0
    if bool(audio_only_feather):
        audio_feather_steps = _audio_feather_preserved_prefix(
            video_mask, audio_mask, video_steps, audio_steps)
    elif bool(temporal_feather):
        video_feather_steps, audio_feather_steps = _feather_preserved_prefix(
            video_mask, audio_mask, video_steps, audio_steps)
    else:
        video_mask[:, :, :video_steps] = 0.0
        audio_mask[..., :audio_steps] = 0.0

    import comfy.nested_tensor

    out_latent = latent.copy()
    out_latent["samples"] = comfy.nested_tensor.NestedTensor(
        (out_video, out_audio))
    out_latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
        (video_mask, audio_mask))
    out_conditioning = _drop_prefix_guides(conditioning, frames)

    if not bool(preserve_audio_prefix):
        mask_summary = "audio fully denoisable (generated continuity off)"
    elif audio_only_feather:
        mask_summary = "audio-only half-cosine feather %d audio steps" % (
            audio_feather_steps)
    elif temporal_feather:
        mask_summary = "temporal feather %d video / %d audio steps" % (
            video_feather_steps, audio_feather_steps)
    else:
        mask_summary = "hard prefix mask"
    _LOG.info(
        "h3_masked_prefix: preserved %d target frames = %d video steps / %d "
        "audio steps (%.3fs, video from %s, audio from %s); %s; target %d "
        "frames at %dx%d; trim %d",
        frames, video_steps, audio_steps, frames / float(FPS), video_source,
        audio_source,
        mask_summary,
        target_frames, width, height, frames,
    )
    return out_conditioning, out_latent, frames
