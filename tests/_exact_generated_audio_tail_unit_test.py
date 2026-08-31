#!/usr/bin/env python3
"""CPU regression for exact-safe generated-audio tail assembly."""

from __future__ import annotations

import importlib.util
import os
import types

import torch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "exact_generated_audio_tail_0637.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "exact_generated_audio_tail_0637_tested", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact_generated_audio_tail_0637.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chain(checkpoints):
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
    )


def main():
    module = _load_module()

    assert module._tail_geometry(
        {"raw_frames": 158, "delivered_frames": 120, "tail_trim_frames": 16},
        where="scene 2",
    ) == (158, 120, 16, 22)

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
    chain = _chain(checkpoints)
    manifest = {
        "compatibility": {"continuation_mode": "guide"},
        "segments": [
            {
                "index": 1,
                "checkpoint": "clip1.safetensors",
                "sample_rate": sr,
                "raw_frames": 124,
                "delivered_frames": 120,
                "tail_trim_frames": 4,
                "continuation_mode": "guide",
            },
            {
                "index": 2,
                "checkpoint": "clip2.safetensors",
                "sample_rate": sr,
                "raw_frames": 158,
                "delivered_frames": 120,
                "tail_trim_frames": 16,
                "continuation_mode": "masked_av",
            },
        ],
    }

    audio = module._generated_audio_exact_safe(chain, manifest)
    waveform = audio["waveform"]
    assert audio["sample_rate"] == sr
    assert tuple(waveform.shape) == (1, 1, 240000)

    # Scene 2 owns its 22-frame incoming head. The private 158-frame raw
    # window is therefore written only from frame 98 through frame 240:
    # 22 head + 120 delivered. The final 16 disposable raw-tail frames never
    # fit inside the final write budget and cannot enter the soundtrack.
    assert torch.all(waveform[..., :98000] == 1.0)
    assert torch.all(waveform[..., 98000:] == 2.0)

    broken = {
        **manifest,
        "segments": [dict(item) for item in manifest["segments"]],
    }
    broken["segments"][1]["checkpoint"] = "clip2-no-overlap.safetensors"
    checkpoints["clip2-no-overlap.safetensors"] = {
        "delivered_audio": torch.full((1, 1, delivered_samples), 3.0),
    }
    try:
        module._generated_audio_exact_safe(chain, broken)
    except ValueError as exc:
        assert "no private Loop Trim audio overlap" in str(exc)
    else:
        raise AssertionError("masked AV without exact overlap must fail closed")

    waveform_key, frames_key, trim_key = module._private_audio_keys(chain)
    incoming_audio = {
        "waveform": torch.zeros((1, 1, delivered_samples)),
        "sample_rate": sr,
        waveform_key: torch.zeros((1, 1, raw_2_samples)),
        frames_key: 158,
        trim_key: 22,
    }

    def exact_trim(audio_value, frames):
        return {
            "waveform": audio_value["waveform"][..., : int(frames * 1000)],
            "sample_rate": audio_value["sample_rate"],
        }

    wrapped_trim = module._wrap_trim_audio_to_frames(exact_trim, chain)
    trimmed = wrapped_trim(incoming_audio, 120)
    assert trimmed[frames_key] == 158
    assert trimmed[trim_key] == 22
    assert trimmed[waveform_key] is incoming_audio[waveform_key]

    captured = {}

    def legacy_save(self, state, images, sampled_latent, audio=None,
                    images_with_overlap=None, denoised_latent=None,
                    prompt=None, extra_pnginfo=None):
        captured["audio"] = audio
        return ("ok",)

    wrapped_save = module._wrap_segment_save(legacy_save, chain)
    state = {
        "index": 2,
        "plan": {"shots": [{}, {
            "raw_frames": 158,
            "delivered_frames": 120,
            "tail_trim_frames": 16,
        }]},
    }
    wrapped_save(
        object(), state, torch.zeros((120, 1, 1, 3)), {},
        audio=incoming_audio,
    )
    # The stock 0.6.37 validator expects raw-delivered (=38). This transient
    # compatibility value lets it persist the full overlap; exact assembly
    # later recomputes the true 22-frame head from tail_trim_frames=16.
    assert captured["audio"][trim_key] == 38
    assert captured["audio"][waveform_key] is incoming_audio[waveform_key]

    print("PASS exact-safe generated-audio tail assembly")


if __name__ == "__main__":
    main()
