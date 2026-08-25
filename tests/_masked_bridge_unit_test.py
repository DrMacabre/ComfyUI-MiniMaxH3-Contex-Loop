#!/usr/bin/env python3
"""CPU regression for the two-ended H3 AV bridge target and masks."""

import importlib.util
import os
import sys
import types

import torch
import torch.nn.functional as functional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "h3_bridge_test_pkg"


class NestedTensor:
    def __init__(self, parts):
        self.parts = tuple(parts)

    def unbind(self):
        return self.parts


def _install_stubs():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [ROOT]
    sys.modules[PACKAGE] = package

    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    nested = types.ModuleType("comfy.nested_tensor")
    nested.NestedTensor = NestedTensor
    comfy.nested_tensor = nested
    sys.modules["comfy"] = comfy
    sys.modules["comfy.nested_tensor"] = nested

    nodes = types.ModuleType("%s.nodes" % PACKAGE)
    nodes.FPS = 24
    nodes.AUDIO_HZ = 40
    frame_per_token = (1, 4, 4, 4, 4)
    nodes._pixel_frames = lambda count: sum(
        frame_per_token[index % 5] for index in range(int(count)))

    def resize(images, width, height, _crop):
        work = images[..., :3].movedim(-1, 1)
        work = functional.interpolate(
            work, size=(height, width), mode="bilinear", align_corners=False)
        return work.movedim(1, -1)

    nodes._resize = resize
    sys.modules[nodes.__name__] = nodes

    support = types.ModuleType("%s.masking_support" % PACKAGE)
    support.require_h3_mask_support = lambda _purpose: None
    sys.modules[support.__name__] = support
    return nodes


def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "%s.masked_bridge" % PACKAGE,
        os.path.join(ROOT, "masked_bridge.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VideoVAE:
    def encode(self, frames):
        count = int(frames.shape[0])
        steps = 2 if count <= 5 else ((count - 5) // 17) * 5 + 2
        value = float(frames.mean())
        return torch.full((1, 24, steps, 2, 4), value)


class AudioVAE:
    audio_sample_rate = 32000

    def encode(self, audio):
        steps = round(int(audio.shape[1]) / self.audio_sample_rate * 40)
        return torch.full((1, 32, 2, steps), float(audio.mean()))


def main():
    nodes = _install_stubs()
    bridge = _load_bridge()
    assert nodes._pixel_frames(57) == 192

    target_video = torch.zeros((1, 24, 57, 2, 4))
    target_audio = torch.zeros((1, 32, 2, 320))
    target = {"samples": NestedTensor((target_video, target_audio))}
    start_frames = torch.full((100, 32, 64, 3), 0.2)
    end_frames = torch.full((100, 32, 64, 3), 0.8)
    start_audio = {
        "waveform": torch.full(
            (1, 2, round(100 / 24 * 32000)), 0.3),
        "sample_rate": 32000,
    }
    end_audio = {
        "waveform": torch.full(
            (1, 2, round(100 / 24 * 32000)), 0.7),
        "sample_rate": 32000,
    }
    input_types = bridge.MiniMaxH3ContexMaskedAVBridge.INPUT_TYPES()
    assert "start_audio" not in input_types["required"]
    assert "end_audio" not in input_types["required"]
    assert {"start_audio", "end_audio"} <= set(input_types["optional"])

    output, middle, protected = (
        bridge.MiniMaxH3ContexMaskedAVBridge().prepare(
            target,
            VideoVAE(),
            AudioVAE(),
            start_frames,
            start_audio,
            end_frames,
            end_audio,
            24.0,
            24.0,
            39,
            "disabled",
        ))
    assert middle == 114
    assert protected == 39
    video, audio = output["samples"].unbind()
    video_mask, audio_mask = output["noise_mask"].unbind()
    assert torch.allclose(
        video[:, :, :12], torch.full_like(video[:, :, :12], 0.2))
    assert not torch.count_nonzero(video[:, :, 12:-12])
    assert torch.allclose(
        video[:, :, -12:], torch.full_like(video[:, :, -12:], 0.8))
    assert torch.allclose(
        audio[..., :65], torch.full_like(audio[..., :65], 0.3))
    assert not torch.count_nonzero(audio[..., 65:-65])
    assert torch.allclose(
        audio[..., -65:], torch.full_like(audio[..., -65:], 0.7))
    assert not torch.count_nonzero(video_mask[:, :, :12])
    assert torch.all(video_mask[:, :, 12:-12] == 1)
    assert not torch.count_nonzero(video_mask[:, :, -12:])
    assert not torch.count_nonzero(audio_mask[..., :65])
    assert torch.all(audio_mask[..., 65:-65] == 1)
    assert not torch.count_nonzero(audio_mask[..., -65:])
    assert not torch.count_nonzero(target_video)
    assert not torch.count_nonzero(target_audio)

    generated_start, _, _ = (
        bridge.MiniMaxH3ContexMaskedAVBridge().prepare(
            target, VideoVAE(), AudioVAE(), start_frames, None,
            end_frames, end_audio, 24.0, 24.0, 39, "disabled"))
    _generated_video, generated_audio = generated_start["samples"].unbind()
    _generated_video_mask, generated_audio_mask = (
        generated_start["noise_mask"].unbind())
    assert not torch.count_nonzero(generated_audio[..., :65])
    assert torch.all(generated_audio_mask[..., :65] == 1)
    assert torch.allclose(
        generated_audio[..., -65:],
        torch.full_like(generated_audio[..., -65:], 0.7))
    assert not torch.count_nonzero(generated_audio_mask[..., -65:])

    try:
        bridge.MiniMaxH3ContexMaskedAVBridge().prepare(
            target, VideoVAE(), AudioVAE(), start_frames, start_audio,
            end_frames, end_audio, 24.0, 24.0, 40, "disabled")
    except ValueError as exc:
        assert "exact H3 video run" in str(exc)
    else:
        raise AssertionError("a 40-frame bridge endpoint must be rejected")

    print(
        "masked bridge: 192 target frames, 39+39 protected, 114 generated; "
        "12 video and optional 65-step audio windows protected independently")


if __name__ == "__main__":
    main()
