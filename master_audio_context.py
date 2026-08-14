"""Exact master-audio masking with an optional previous-video prefix.

This is the timeline-audio specialization of the general H3 masked-target
path: the target audio stream is replaced with one exact master-audio interval
and protected for the complete raw clip. Continuations may additionally
protect the final native H3 run from the preceding decoded video.

The design is adapted from seitanism's GPL-3.0
ComfyUI-H3-Motion-Context-MultiRef Update 4 implementation.  This pack keeps a
distinct public node id and reuses its shared native-first mask capability
gate so both packs can be installed together.
"""

from __future__ import annotations

import logging

import torch

from .masked_context import _snap_prefix_length, _validate_target_streams
from .masking_support import require_h3_mask_support
from .nodes import AUDIO_HZ, FPS, _pixel_frames, _resize


_LOG = logging.getLogger("minimax_h3_context_loop.master_audio_context")


def _cfr_index_map(frame_count, source_fps, device):
    source_fps = float(source_fps)
    if source_fps <= 0.0:
        raise ValueError("h3_master_audio_mask: source_fps must be positive.")
    count = int(frame_count)
    if count < 1:
        raise ValueError("h3_master_audio_mask: source video has no frames.")
    output_count = max(1, int(round(count * float(FPS) / source_fps)))
    if output_count == count and abs(source_fps - float(FPS)) < 1e-6:
        return torch.arange(count, device=device, dtype=torch.long)
    index = torch.arange(output_count, device=device, dtype=torch.float64)
    time = (index + 0.5) / float(FPS)
    source = torch.round(time * source_fps - 0.5).to(torch.long)
    return source.clamp_(0, count - 1)


def _stereo_first_batch(waveform):
    if getattr(waveform, "ndim", 0) != 3:
        raise ValueError(
            "h3_master_audio_mask: master audio waveform must be [B,C,L], "
            "got %s." %
            (tuple(getattr(waveform, "shape", ())),)
        )
    waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels == 1:
        return waveform.repeat(1, 2, 1)
    if channels == 2:
        return waveform
    raise ValueError(
        "h3_master_audio_mask: master audio has %d channels; downmix it to stereo "
        "before this node." % channels
    )


def _resample(waveform, source_rate, target_rate):
    source_rate = int(source_rate)
    target_rate = int(target_rate)
    if source_rate == target_rate:
        return waveform
    try:
        import torchaudio
    except ImportError as exc:
        raise RuntimeError(
            "h3_master_audio_mask: master audio is %d Hz but the H3 audio VAE needs "
            "%d Hz and torchaudio is unavailable." %
            (source_rate, target_rate)
        ) from exc
    return torchaudio.functional.resample(waveform, source_rate, target_rate)


def _fit_audio_slice(waveform, samples):
    wanted = int(samples)
    available = int(waveform.shape[-1])
    if available > wanted:
        return waveform[..., :wanted]
    if available < wanted:
        _LOG.warning(
            "h3_master_audio_mask: master-audio slice is %d samples short; padding "
            "silence at the tail.", wanted - available)
        return torch.nn.functional.pad(waveform, (0, wanted - available))
    return waveform


class MiniMaxH3ContexMasterAudioMaskedAV:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT", {
                    "tooltip": "Target AV latent from the stock MiniMax H3 "
                               "conditioning node.",
                }),
                "audio_vae": ("VAE", {
                    "tooltip": "MiniMax H3 audio VAE used to encode the exact "
                               "master-audio slice into the target latent.",
                }),
                "master_audio": ("AUDIO", {
                    "tooltip": "Full prerecorded audio timeline (music, "
                               "dialogue, narration, or effects). The exact "
                               "current interval is inserted into the target "
                               "and fully protected.",
                }),
                "clip_start_seconds": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 99999.0,
                    "step": 0.001,
                    "tooltip": "Start of this raw H3 clip on the master-audio "
                               "timeline.",
                }),
                "context_length": ("INT", {
                    "default": 39, "min": 0, "max": 9999,
                    "tooltip": "Previous-video prefix request. Native runs "
                               "such as 5, 22, 39, 56... are used; 0 disables "
                               "video prefixing when source_frames is absent.",
                }),
                "source_fps": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 240.0,
                    "step": 0.001,
                }),
                "crop": (["disabled", "center"], {"default": "disabled"}),
            },
            "optional": {
                "vae": ("VAE", {
                    "tooltip": "MiniMax H3 video VAE; required when previous "
                               "source_frames are connected.",
                }),
                "source_frames": ("IMAGE", {
                    "tooltip": "Previous decoded clip. Its final native H3 "
                               "context run becomes the protected video prefix.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "INT", "AUDIO")
    RETURN_NAMES = ("latent", "trim_frames", "clip_audio")
    OUTPUT_TOOLTIPS = (
        "Sampler target with exact protected master audio and optional "
        "protected previous-video prefix.",
        "Actual protected visual prefix length; trim this many decoded frames.",
        "Exact master-audio interval represented by this raw target.",
    )
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/contex_loop/masking"
    DESCRIPTION = (
        "Insert an exact master-audio interval into the complete H3 audio "
        "target and protect it from denoising; optionally preserve a previous "
        "decoded-video prefix while generating only future video rows."
    )

    def prepare(
        self,
        latent,
        audio_vae,
        master_audio,
        clip_start_seconds=0.0,
        context_length=39,
        source_fps=24.0,
        crop="disabled",
        vae=None,
        source_frames=None,
    ):
        require_h3_mask_support("exact master-audio latent masking")
        target_video, target_audio, target_frames = _validate_target_streams(
            latent)

        expected_audio_steps = int(round(
            target_frames / float(FPS) * AUDIO_HZ))
        vae_rate = int(getattr(audio_vae, "audio_sample_rate", 32000))
        if not isinstance(master_audio, dict):
            raise ValueError(
                "h3_master_audio_mask: master_audio is not a Comfy AUDIO.")
        waveform = _stereo_first_batch(master_audio.get("waveform"))
        waveform = _resample(
            waveform, int(master_audio.get("sample_rate", 0)), vae_rate)

        start_seconds = float(clip_start_seconds)
        if start_seconds < 0.0:
            raise ValueError(
                "h3_master_audio_mask: clip_start_seconds must be >= 0.")
        start_sample = int(round(start_seconds * vae_rate))
        wanted_samples = int(round(
            target_frames / float(FPS) * vae_rate))
        audio_slice = _fit_audio_slice(
            waveform[..., start_sample:start_sample + wanted_samples],
            wanted_samples,
        )
        encoded_audio = audio_vae.encode(audio_slice.movedim(1, -1))
        if getattr(encoded_audio, "ndim", 0) != 4:
            raise ValueError(
                "h3_master_audio_mask: audio VAE returned %s; expected "
                "[B,C,2,T]." %
                (tuple(getattr(encoded_audio, "shape", ())),)
            )
        if int(encoded_audio.shape[-1]) < expected_audio_steps:
            raise RuntimeError(
                "h3_master_audio_mask: target requires %d audio steps but the audio "
                "VAE produced %d." %
                (expected_audio_steps, int(encoded_audio.shape[-1]))
            )
        if int(encoded_audio.shape[-1]) > expected_audio_steps:
            _LOG.warning(
                "h3_master_audio_mask: audio VAE produced %d steps for a %d-step "
                "target; retaining the leading aligned interval.",
                int(encoded_audio.shape[-1]), expected_audio_steps)
            encoded_audio = encoded_audio[..., :expected_audio_steps]

        out_video = target_video.clone()
        out_audio = target_audio.clone()
        encoded_audio = encoded_audio[:1].to(
            device=out_audio.device, dtype=out_audio.dtype)
        if tuple(encoded_audio.shape) != tuple(out_audio.shape):
            raise ValueError(
                "h3_master_audio_mask: encoded master audio shape %s does not match "
                "target %s." %
                (tuple(encoded_audio.shape), tuple(out_audio.shape))
            )
        out_audio.copy_(encoded_audio)

        prefix_frames = 0
        video_steps = 0
        if source_frames is not None:
            if vae is None:
                raise ValueError(
                    "h3_master_audio_mask: connect the video VAE when source_frames "
                    "is connected.")
            if (getattr(source_frames, "ndim", 0) != 4
                    or int(source_frames.shape[0]) < 1):
                raise ValueError(
                    "h3_master_audio_mask: source_frames must be IMAGE "
                    "[N,H,W,C].")
            if int(context_length) <= 0:
                raise ValueError(
                    "h3_master_audio_mask: context_length must be positive when "
                    "source_frames is connected.")
            indices = _cfr_index_map(
                int(source_frames.shape[0]), source_fps,
                source_frames.device)
            prefix_frames = _snap_prefix_length(
                context_length, int(indices.numel()), target_frames)
            tail = source_frames.index_select(0, indices[-prefix_frames:])
            width = int(target_video.shape[4]) * 16
            height = int(target_video.shape[3]) * 16
            prefix = vae.encode(_resize(tail, width, height, crop))
            if getattr(prefix, "ndim", 0) != 5:
                raise ValueError(
                    "h3_master_audio_mask: video VAE returned %s; expected "
                    "[B,C,T,H,W]." %
                    (tuple(getattr(prefix, "shape", ())),)
                )
            video_steps = int(prefix.shape[2])
            covered = _pixel_frames(video_steps)
            if covered != prefix_frames:
                raise RuntimeError(
                    "h3_master_audio_mask: %d source frames encoded to %d video "
                    "steps covering %d frames; refusing a shifted seam." %
                    (prefix_frames, video_steps, covered)
                )
            if video_steps >= int(out_video.shape[2]):
                raise ValueError(
                    "h3_master_audio_mask: video prefix consumes the complete "
                    "target.")
            prefix = prefix[:1].to(
                device=out_video.device, dtype=out_video.dtype)
            if (int(prefix.shape[1]) != int(out_video.shape[1])
                    or tuple(prefix.shape[3:]) != tuple(out_video.shape[3:])):
                raise ValueError(
                    "h3_master_audio_mask: video prefix shape %s does not match "
                    "target %s." %
                    (tuple(prefix.shape), tuple(out_video.shape))
                )
            out_video[:, :, :video_steps] = prefix

        video_mask = torch.ones(
            (1, 1, int(out_video.shape[2]), int(out_video.shape[3]),
             int(out_video.shape[4])),
            device=out_video.device, dtype=torch.float32)
        if video_steps:
            video_mask[:, :, :video_steps] = 0.0
        audio_mask = torch.zeros(
            (1, 1, int(out_audio.shape[2]), int(out_audio.shape[3])),
            device=out_audio.device, dtype=torch.float32)

        import comfy.nested_tensor

        output = latent.copy()
        output["samples"] = comfy.nested_tensor.NestedTensor(
            (out_video, out_audio))
        output["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (video_mask, audio_mask))
        clip_audio = {"waveform": audio_slice, "sample_rate": vae_rate}
        _LOG.info(
            "h3_master_audio_mask: target %d frames / %.3fs; master "
            "%.3f..%.3fs "
            "encoded to %d fully protected audio steps; video prefix %d "
            "frames / %d steps.",
            target_frames, target_frames / float(FPS), start_seconds,
            start_seconds + target_frames / float(FPS),
            expected_audio_steps, prefix_frames, video_steps)
        return output, prefix_frames, clip_audio


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ContexMasterAudioMaskedAV": (
        MiniMaxH3ContexMasterAudioMaskedAV),
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ContexMasterAudioMaskedAV": (
        "MiniMax H3 Masking · Master Audio + Video Prefix"),
}
