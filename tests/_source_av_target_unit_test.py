#!/usr/bin/env python3
"""CPU regression for frame-locked loop source AV target construction."""

import importlib.util
import os
import sys
import types

import torch
import torch.nn.functional as functional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "h3_source_av_target_test_pkg"


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

    def resize(images, width, height, _crop):
        work = images[..., :3].movedim(-1, 1)
        work = functional.interpolate(
            work, size=(height, width), mode="bilinear", align_corners=False)
        return work.movedim(1, -1)

    nodes._resize = resize
    sys.modules[nodes.__name__] = nodes

    context = types.ModuleType("%s.masked_context" % PACKAGE)

    def validate_target(latent, strict_audio_grid=True):
        video, audio = latent["samples"].unbind()
        # 37 H3 video steps represent the exact 124-frame run used below.
        frames = 124 if int(video.shape[2]) == 37 else -1
        assert not strict_audio_grid
        return video, audio, frames

    context._validate_target_streams = validate_target
    sys.modules[context.__name__] = context


def _load_node():
    spec = importlib.util.spec_from_file_location(
        "%s.source_av_target" % PACKAGE,
        os.path.join(ROOT, "source_av_target.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VideoVAE:
    def encode(self, frames):
        assert int(frames.shape[0]) == 124
        return torch.full((1, 24, 37, 2, 4), float(frames.mean()))


class FloorAudioVAE:
    audio_sample_rate = 32000

    def __init__(self):
        self.encoded_sample_counts = []

    def encode(self, audio):
        samples = int(audio.shape[1])
        self.encoded_sample_counts.append(samples)
        # This floor behavior is the former LTX concat failure: exact picture
        # duration yields 206 steps, while the stock 124-frame target has 207.
        steps = int(samples / self.audio_sample_rate * 40)
        return torch.full((1, 32, 2, steps), float(audio.mean()))


def main():
    _install_stubs()
    module = _load_node()

    target_video = torch.zeros((1, 24, 37, 2, 4))
    target_audio = torch.zeros((1, 32, 2, 207))
    latent = {"samples": NestedTensor((target_video, target_audio))}
    source_frames = torch.linspace(0.0, 1.0, 200).reshape(
        200, 1, 1, 1).expand(200, 32, 64, 3).clone()
    source_samples = round(200 / 24 * 32000)
    source_audio = {
        "waveform": torch.linspace(0.0, 1.0, source_samples).reshape(
            1, 1, source_samples).repeat(1, 2, 1),
        "sample_rate": 32000,
    }
    state = {
        "index": 1,
        "plan": {"shots": [{
            "generation_start_frame": 17,
            "raw_frames": 124,
        }]},
    }
    audio_vae = FloorAudioVAE()
    output, scene_frames, scene_audio, status = (
        module.MiniMaxH3ContexLoopSourceAVTarget().prepare(
            state, latent, VideoVAE(), audio_vae, source_frames,
            source_audio, 24.0, "disabled"))

    video, audio = output["samples"].unbind()
    assert tuple(video.shape) == tuple(target_video.shape)
    assert tuple(audio.shape) == tuple(target_audio.shape)
    assert int(scene_frames.shape[0]) == 124
    assert int(scene_audio["waveform"].shape[-1]) == round(124 / 24 * 32000)
    assert audio_vae.encoded_sample_counts == [165600]
    assert "source frames 17..140" in status
    assert "207 audio steps" in status
    assert not torch.count_nonzero(target_video)
    assert not torch.count_nonzero(target_audio)
    assert set(module.NODE_CLASS_MAPPINGS) == {
        "MiniMaxH3ContexLoopSourceAVTarget"}

    print(
        "loop source AV target: 124 picture frames use the stock 207-step "
        "audio grid; frame-derived source slicing replaces misaligned LTX "
        "AV concat/separate")


if __name__ == "__main__":
    main()
