#!/usr/bin/env python3
"""CPU-only regression for MASTER disposable masked-audio head protection."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "disposable_audio_head_0637_tested",
    ROOT / "disposable_audio_head_0637.py",
)
patch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(patch)


class FakeTensor:
    def __init__(self, shape, fill=0.0, token=None):
        self.shape = tuple(shape)
        self.ndim = len(self.shape)
        self.values = [float(fill)] * int(self.shape[-1])
        self.token = token

    def copy(self):
        out = FakeTensor(self.shape, token=self.token)
        out.values = list(self.values)
        return out

    def __setitem__(self, key, value):
        if not isinstance(key, tuple) or len(key) != 2 or key[0] is not Ellipsis:
            raise AssertionError("unexpected FakeTensor assignment %r" % (key,))
        span = key[1]
        if not isinstance(span, slice):
            raise AssertionError("expected trailing slice assignment")
        start, stop, step = span.indices(len(self.values))
        if step != 1:
            raise AssertionError("unexpected slice step")
        for index in range(start, stop):
            self.values[index] = float(value)


class FakeNestedTensor:
    def __init__(self, tensors):
        self.tensors = list(tensors)

    def unbind(self):
        return list(self.tensors)


comfy = types.ModuleType("comfy")
nested = types.ModuleType("comfy.nested_tensor")
nested.NestedTensor = FakeNestedTensor
comfy.nested_tensor = nested
sys.modules.setdefault("comfy", comfy)
sys.modules.setdefault("comfy.nested_tensor", nested)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, *args):
        self.messages.append(args)


def _make_latent(audio_fill=7.0, audio_mask_fill=1.0):
    video = FakeTensor((1, 16, 7, 4, 4), token="video")
    audio = FakeTensor((1, 32, 2, 100), fill=audio_fill, token="audio")
    video_mask = FakeTensor((1, 1, 7, 4, 4), fill=1.0, token="video-mask")
    audio_mask = FakeTensor((1, 1, 2, 100), fill=audio_mask_fill, token="audio-mask")
    return {
        "samples": FakeNestedTensor((video, audio)),
        "noise_mask": FakeNestedTensor((video_mask, audio_mask)),
    }


def _masked_module():
    logger = FakeLogger()

    def streams(latent):
        return latent["samples"].unbind()

    def masks(latent, _video, _audio):
        video_mask, audio_mask = latent["noise_mask"].unbind()
        return video_mask.copy(), audio_mask.copy()

    def apply_masked_prefix(
            conditioning=None, latent=None, preserve_audio_prefix=True,
            trim_frames=22, locked_source=False):
        out = latent.copy()
        video, audio = latent["samples"].unbind()
        if locked_source:
            audio_mask_fill = 0.0
        else:
            audio_mask_fill = 1.0
        video_mask = FakeTensor((1, 1, 7, 4, 4), fill=1.0)
        audio_mask = FakeTensor((1, 1, 2, 100), fill=audio_mask_fill)
        if preserve_audio_prefix:
            # Simulate the existing genuine generated-audio carry policy.
            for index in range(65):
                audio_mask.values[index] = 0.0
        out["samples"] = latent["samples"]
        out["noise_mask"] = FakeNestedTensor((video_mask, audio_mask))
        return conditioning, out, int(trim_frames)

    return types.SimpleNamespace(
        FPS=24,
        AUDIO_HZ=40.0,
        _LOG=logger,
        _streams_from_latent=streams,
        _existing_mask_streams=masks,
        apply_masked_prefix=apply_masked_prefix,
    )


def main():
    assert patch._guard_steps(22, 100, 24, 40.0) == 37
    assert patch._guard_steps(39, 100, 24, 40.0) == 65
    assert patch._guard_steps(5, 100, 24, 40.0) == 9
    assert patch._guard_steps(0, 100, 24, 40.0) == 0
    assert patch._guard_steps(120, 80, 24, 40.0) == 80

    masked = _masked_module()
    assert patch.activate_disposable_audio_head(masked) == patch.BUILD
    wrapped = masked.apply_masked_prefix
    assert patch.activate_disposable_audio_head(masked) == patch.BUILD
    assert masked.apply_masked_prefix is wrapped

    # Generated continuity OFF: the hidden 22-frame head becomes protected for
    # ceil(22*40/24)=37 audio ticks, but the audio latent samples are untouched.
    source = _make_latent(audio_fill=7.0)
    samples_before = source["samples"]
    _cond, guarded, trim = masked.apply_masked_prefix(
        conditioning="scene", latent=source,
        preserve_audio_prefix=False, trim_frames=22)
    assert trim == 22
    assert guarded["samples"] is samples_before
    _video_mask, audio_mask = guarded["noise_mask"].unbind()
    assert audio_mask.values[:37] == [0.0] * 37
    assert audio_mask.values[37:] == [1.0] * 63
    _video, audio_samples = guarded["samples"].unbind()
    assert audio_samples.values == [7.0] * 100

    # Generated continuity ON is a strict no-op: existing predecessor-audio
    # ownership/masks must not be altered by this overlay.
    carry_source = _make_latent(audio_fill=8.0)
    _cond, carried, trim = masked.apply_masked_prefix(
        conditioning="scene", latent=carry_source,
        preserve_audio_prefix=True, trim_frames=39)
    assert trim == 39
    _video_mask, carry_mask = carried["noise_mask"].unbind()
    assert carry_mask.values[:65] == [0.0] * 65
    assert carry_mask.values[65:] == [1.0] * 35
    _video, carry_audio = carried["samples"].unbind()
    assert carry_audio.values == [8.0] * 100

    # Locked/source audio is already protected.  Applying the disposable-head
    # guard remains idempotent and never changes source samples or timing.
    locked_source = _make_latent(audio_fill=9.0, audio_mask_fill=0.0)
    _cond, locked, trim = masked.apply_masked_prefix(
        conditioning="scene", latent=locked_source,
        preserve_audio_prefix=False, trim_frames=22, locked_source=True)
    assert trim == 22
    _video_mask, locked_mask = locked["noise_mask"].unbind()
    assert locked_mask.values == [0.0] * 100
    _video, locked_audio = locked["samples"].unbind()
    assert locked_audio.values == [9.0] * 100

    print("PASS MASTER disposable audio head guard")


if __name__ == "__main__":
    main()
