#!/usr/bin/env python3
"""CPU regression for exact master-audio latent masking."""

import os
import sys
import types

import torch


TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)

import _masked_prefix_unit_test as harness  # noqa: E402


def main():
    harness._install_comfy_stubs()
    package = types.ModuleType(harness.PACKAGE)
    package.__path__ = [harness.ROOT]
    sys.modules[harness.PACKAGE] = package
    harness._load("patch_layout")
    harness._load("patch_payload")
    nodes = harness._load("nodes")
    harness._load("masked_context")
    audio_context = harness._load("master_audio_context")
    audio_context.require_h3_mask_support = lambda _operation: True

    target_frames = 141
    video_steps = 42
    audio_steps = 235
    assert nodes._pixel_frames(video_steps) == target_frames
    target_video = torch.zeros((1, 16, video_steps, 2, 4))
    target_audio = torch.zeros((1, 32, 2, audio_steps))
    latent = {
        "samples": harness.NestedTensor((target_video, target_audio)),
    }

    previous_frames = torch.rand((120, 32, 64, 3))
    master_audio = {
        "waveform": torch.rand((1, 2, 32_000 * 30)),
        "sample_rate": 32_000,
    }

    class VideoVAE:
        def encode(self, frames):
            count = int(frames.shape[0])
            steps = max(1, (count - 5) // 17 * 5 + 2)
            return torch.full((1, 16, steps, 2, 4), 0.25)

    class AudioVAE:
        audio_sample_rate = 32_000

        def encode(self, waveform):
            steps = round(int(waveform.shape[1]) / 32_000 * 40)
            return torch.full((1, 32, 2, steps), 0.5)

    output, prefix, clip_audio = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=3.25,
            context_length=39,
            source_fps=24.0,
            crop="disabled",
            vae=VideoVAE(),
            source_frames=previous_frames,
        ))
    video, audio = output["samples"].unbind()
    video_mask, audio_mask = output["noise_mask"].unbind()
    assert prefix == 39
    assert torch.allclose(
        video[:, :, :12], torch.full_like(video[:, :, :12], 0.25))
    assert not torch.count_nonzero(video[:, :, 12:])
    assert torch.allclose(audio, torch.full_like(audio, 0.5))
    assert not torch.count_nonzero(video_mask[:, :, :12])
    assert torch.all(video_mask[:, :, 12:] == 1.0)
    assert not torch.count_nonzero(audio_mask)
    assert clip_audio["sample_rate"] == 32_000
    assert int(clip_audio["waveform"].shape[-1]) == round(
        target_frames / 24 * 32_000)

    first, first_prefix, _ = (
        audio_context.MiniMaxH3ContexMasterAudioMaskedAV().prepare(
            latent,
            AudioVAE(),
            master_audio,
            clip_start_seconds=0.0,
            context_length=0,
        ))
    first_video_mask, first_audio_mask = first["noise_mask"].unbind()
    assert first_prefix == 0
    assert torch.all(first_video_mask == 1.0)
    assert not torch.count_nonzero(first_audio_mask)

    assert (
        "MiniMaxH3ContexMasterAudioMaskedAV"
        in audio_context.NODE_CLASS_MAPPINGS)
    assert (
        "MiniMaxH3ContexSongMaskedAVContext"
        not in audio_context.NODE_CLASS_MAPPINGS)
    assert (
        "MiniMaxH3SongMaskedAVContext"
        not in audio_context.NODE_CLASS_MAPPINGS)
    print(
        "master-audio masking: exact timeline slice, complete protected audio, "
        "39-frame protected video continuation, and clip-1 video generation "
        "pass")


if __name__ == "__main__":
    main()
