#!/usr/bin/env python3
"""CPU regression for boundary-exact generated-audio continuity."""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import torch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "exact_generated_audio_continuity_0637.py")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "exact_generated_audio_continuity_0637_tested", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact_generated_audio_continuity_0637.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeVAE:
    def encode(self, images):
        assert int(images.shape[0]) == 39
        return torch.zeros((1, 2, 12, 1, 1), dtype=torch.float32)


def main():
    module = _load_module()

    raw_video = torch.zeros((1, 2, 72, 1, 1), dtype=torch.float32)
    raw_audio = torch.arange(405, dtype=torch.float32).reshape(1, 1, 1, 405)
    checkpoint = {"video": raw_video, "audio": raw_audio}
    captured = {}

    def original_apply(self, state, conditioning, vae, latent, **kwargs):
        captured["state"] = state
        captured["kwargs"] = kwargs
        return ("ok",)

    chain = types.SimpleNamespace(
        FPS=24,
        _st_load=lambda path: checkpoint,
        _absolute_output_path=lambda path: path,
        _resize=lambda images, width, height, crop: images,
        _streams_from_latent=lambda latent: latent["samples"],
        _shot_context_length=lambda shot, default: int(shot.get("context_length", default)),
        _shot_audio_context_length=lambda shot, default, context: int(
            shot.get("audio_context_length", default or context)),
        _audio_policy_uses_generated_continuity=lambda cfg, shot=None: bool(
            shot.get("generated_continuity", True)),
        _audio_policy_locks_source_audio=lambda cfg, shot=None: False,
        _resume_context_predecessors=lambda plan, index: {"audio": index - 1},
    )

    state = {
        "index": 2,
        "previous_latent_timeline_exact": False,
        "previous_latent": None,
        "previous_frames": torch.zeros((39, 1, 1, 3), dtype=torch.float32),
        "segments": [{
            "index": 1,
            "checkpoint": "clip1.safetensors",
            "raw_frames": 243,
            "delivered_frames": 240,
            "tail_trim_frames": 3,
        }],
        "plan": {
            "compatibility": {
                "context_length": 39,
                "audio_context_length": 39,
                "crop": "center",
            },
            "shots": [
                {},
                {
                    "context_length": 39,
                    "audio_context_length": 39,
                    "generated_continuity": True,
                },
            ],
        },
    }
    target = {
        "samples": [
            torch.zeros((1, 2, 20, 1, 1), dtype=torch.float32),
            torch.zeros((1, 1, 1, 100), dtype=torch.float32),
        ]
    }

    wrapped = module._wrap_context_apply(original_apply, chain)
    result = wrapped(
        object(), state, "conditioning", FakeVAE(), target,
        audio_vae="audio-vae", visual_cond_noise_aug=0.999,
    )
    assert result == ("ok",)

    safe = captured["state"]
    assert safe is not state
    assert safe["previous_latent_timeline_exact"] is True
    assert safe["_exact_generated_continuity_boundary"] is True
    video, audio = safe["previous_latent"]["samples"]
    assert tuple(video.shape) == (1, 2, 12, 1, 1)
    assert tuple(audio.shape) == (1, 1, 1, 65)

    # RAW scene 1 is 243 frames -> 405 audio steps. Exact delivery stops at
    # frame 240 -> step 400. The 39-frame context is 65 steps, therefore the
    # safe carrier MUST be [335:400], never the RAW-tail [340:405].
    assert float(audio[..., 0].item()) == 335.0
    assert float(audio[..., -1].item()) == 399.0
    assert 400.0 not in audio
    assert 404.0 not in audio
    assert captured["kwargs"]["visual_cond_noise_aug"] == 0.999

    # Generated continuity OFF must not synthesize anything; the existing exact
    # wrapper remains responsible for its ordinary RGB fallback.
    captured.clear()
    off_state = dict(state)
    off_state["plan"] = {
        **state["plan"],
        "shots": [dict(state["plan"]["shots"][0]), {
            **state["plan"]["shots"][1],
            "generated_continuity": False,
        }],
    }
    wrapped(object(), off_state, "conditioning", FakeVAE(), target)
    assert captured["state"] is off_state
    assert captured["state"]["previous_latent_timeline_exact"] is False
    assert captured["state"]["previous_latent"] is None

    assert module._pixel_frames(72) == 243
    assert module._pixel_frames(12) == 39
    assert module._audio_steps(240, 24) == 400
    assert module._audio_steps(39, 24) == 65

    print("PASS exact padded-scene generated-audio continuity")


if __name__ == "__main__":
    main()
