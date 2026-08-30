#!/usr/bin/env python3
"""Regression for deferred Source Timeline resume PCM boundary drift."""

import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "resume_source_pcm_canonical_0637",
    ROOT / "resume_source_pcm_canonical_0637.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def sample_boundary_from_frames(frame_position, sample_rate, fps=24):
    return int(round(int(frame_position) / float(fps) * int(sample_rate)))


def validate_audio(audio, _label):
    return audio["waveform"], int(audio["sample_rate"])


def validate_timeline(timeline, require_runtime=False):
    return timeline


def legacy_source_timeline_scene_audio(timeline, source_start, source_end):
    audio = timeline["audio"]
    if audio["kind"] != "deferred_tensor":
        return {"route": "delegated"}
    waveform = audio["value"]["waveform"]
    sample_rate = int(audio["value"]["sample_rate"])
    start = int(round(int(source_start) / 24.0 * sample_rate))
    end = int(round((
        int(source_start) / 24.0
        + (int(source_end) - int(source_start)) / 24.0
    ) * sample_rate))
    return {
        "waveform": waveform[..., start:end],
        "sample_rate": sample_rate,
    }


def main():
    chain = types.SimpleNamespace(
        FPS=24,
        sample_boundary_from_frames=sample_boundary_from_frames,
        _validate_audio=validate_audio,
        _validate_source_timeline=validate_timeline,
        _source_timeline_scene_audio=legacy_source_timeline_scene_audio,
    )

    sample_rate = 44100
    total = sample_boundary_from_frames(4000, sample_rate)
    timeline = {
        "extent": {"frame_count": 4000},
        "audio": {
            "kind": "deferred_tensor",
            "aligned_to_timeline_origin": True,
            "value": {
                "waveform": torch.arange(
                    total, dtype=torch.float32).reshape(1, 1, -1),
                "sample_rate": sample_rate,
            },
        },
    }

    # This is the floating-point associativity failure seen in runtime: the
    # legacy start+duration expression rounds the same 80-frame window one
    # sample longer than independent absolute frame boundaries.
    start, end = 3143, 3223
    before = chain._source_timeline_scene_audio(timeline, start, end)
    assert before["waveform"].shape[-1] == 147001

    assert patch.activate_resume_source_pcm_canonical(chain) == patch.BUILD
    after = chain._source_timeline_scene_audio(timeline, start, end)
    assert after["waveform"].shape[-1] == 147000

    exact_start = sample_boundary_from_frames(start, sample_rate)
    exact_end = sample_boundary_from_frames(end, sample_rate)
    assert torch.equal(
        after["waveform"],
        timeline["audio"]["value"]["waveform"][..., exact_start:exact_end],
    )

    wrapped = chain._source_timeline_scene_audio
    assert patch.activate_resume_source_pcm_canonical(chain) == patch.BUILD
    assert chain._source_timeline_scene_audio is wrapped

    other = {"audio": {"kind": "external_path"}}
    assert chain._source_timeline_scene_audio(other, 1, 2) == {
        "route": "delegated"}

    print("H3 resume PCM canonicalization: exact deferred frame boundaries PASS")


if __name__ == "__main__":
    main()
