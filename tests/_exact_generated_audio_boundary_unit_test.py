#!/usr/bin/env python3
"""CPU regression for exact-boundary generated-audio assembly."""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "exact_generated_audio_boundary_0637.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "exact_generated_audio_boundary_0637_tested", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact_generated_audio_boundary_0637.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _chain(checkpoints, carry):
    return types.SimpleNamespace(
        AUDIO_WITH_OVERLAP_WAVEFORM_KEY="_h3_audio_with_overlap_waveform",
        AUDIO_WITH_OVERLAP_FRAMES_KEY="_h3_audio_with_overlap_frames",
        AUDIO_TRIM_FRAMES_KEY="_h3_audio_trim_frames",
        MASKED_CONTINUATION_MODES=frozenset(("masked_av",)),
        FPS=24,
        torch=torch,
        _st_load=lambda path: checkpoints[path],
        _absolute_output_path=lambda path: path,
        sample_boundary_from_frames=lambda frame, rate, fps=24: int(
            round(int(frame) / float(fps) * int(rate))),
        migrate_continuation_mode=lambda value: str(value),
        _audio_policy_uses_generated_continuity=lambda manifest, segment=None: bool(carry),
    )


def _manifest():
    return {
        "compatibility": {"continuation_mode": "guide"},
        "segments": [
            {
                "index": 1,
                "checkpoint": "clip1.safetensors",
                "sample_rate": 24000,
                "raw_frames": 124,
                "delivered_frames": 120,
                "tail_trim_frames": 4,
                "continuation_mode": "guide",
            },
            {
                "index": 2,
                "checkpoint": "clip2.safetensors",
                "sample_rate": 24000,
                "raw_frames": 158,
                "delivered_frames": 120,
                "tail_trim_frames": 16,
                "continuation_mode": "masked_av",
            },
        ],
    }


def main():
    module = _load_module()
    sr = 24000
    delivered_samples = 120000
    raw_2_samples = 158000
    checkpoints = {
        "clip1.safetensors": {
            "delivered_audio": torch.ones((1, 1, delivered_samples)),
        },
        "clip2.safetensors": {
            "delivered_audio": torch.full((1, 1, delivered_samples), 3.0),
            "audio_with_overlap": torch.full((1, 1, raw_2_samples), 2.0),
        },
    }

    # Master policy: generated continuity OFF. Scene 2 must begin at frame 120,
    # never 22 frames early. The short post-boundary interpolation may alter
    # only the first 5 ms of scene 2.
    chain = _chain(checkpoints, carry=False)
    audio = module._generated_audio_boundary_safe(chain, _manifest())
    waveform = audio["waveform"]
    assert tuple(waveform.shape) == (1, 1, 240000)
    assert torch.all(waveform[..., :120000] == 1.0)
    assert float(waveform[..., 120000].item()) == 1.0
    ramp_samples = int(round(sr * module.DECLICK_MILLISECONDS / 1000.0))
    assert ramp_samples == 120
    assert torch.all(waveform[..., 120000 + ramp_samples:] == 3.0)
    assert float(waveform[..., 120000 + ramp_samples - 1].item()) == 3.0

    # OFF does not require private overlap at all; delivered checkpoint audio is
    # authoritative and stays exact.
    checkpoints["clip2-no-overlap.safetensors"] = {
        "delivered_audio": torch.full((1, 1, delivered_samples), 3.0),
    }
    no_overlap = _manifest()
    no_overlap["segments"][1]["checkpoint"] = "clip2-no-overlap.safetensors"
    audio2 = module._generated_audio_boundary_safe(chain, no_overlap)
    assert torch.all(audio2["waveform"][..., :120000] == 1.0)

    # Advanced policy: genuine generated continuity ON keeps the existing
    # private-overlap ownership. Tail padding is still excluded from the write.
    carry_chain = _chain(checkpoints, carry=True)
    carry_audio = module._generated_audio_boundary_safe(carry_chain, _manifest())
    carry_wave = carry_audio["waveform"]
    assert torch.all(carry_wave[..., :98000] == 1.0)
    assert torch.all(carry_wave[..., 98000:] == 2.0)

    try:
        module._generated_audio_boundary_safe(carry_chain, no_overlap)
    except ValueError as exc:
        assert "no private Loop Trim audio overlap" in str(exc)
    else:
        raise AssertionError("generated continuity ON without overlap must fail closed")

    print("PASS exact generated-audio boundary ownership")


if __name__ == "__main__":
    main()
