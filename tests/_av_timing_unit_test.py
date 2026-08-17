#!/usr/bin/env python3
"""CPU regressions for exact H3 PCM boundaries and time-conformance."""

import importlib.util
import pathlib

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "h3_av_timing_unit", ROOT / "av_timing.py")
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)


def main():
    short = torch.ones((1, 2, 346_400), dtype=torch.float32)
    conformed = timing.conform_waveform_length(
        short, 346_667, "260-frame test")
    assert tuple(conformed.shape) == (1, 2, 346_667)
    assert torch.all(conformed > 0.98)

    long = torch.linspace(-1.0, 1.0, 165_600).reshape(1, 1, -1)
    contracted = timing.conform_waveform_length(
        long, 165_333, "124-frame test")
    assert tuple(contracted.shape) == (1, 1, 165_333)
    assert torch.isfinite(contracted).all()

    try:
        timing.conform_waveform_length(
            torch.ones((1, 1, 100)), 200, "bad wiring")
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("large audio mismatch was silently conformed")

    start = 0.3 / 32_000.0
    first = timing.sample_boundary_from_seconds(start, 32_000)
    last = timing.sample_boundary_from_seconds(start + 124 / 24.0, 32_000)
    assert first == 0
    assert last - first == 165_334
    assert timing.sample_boundary_from_frames(124, 32_000) == 165_333

    print("H3 AV timing: small grid drift is conformed without silence; absolute boundaries are exact")


if __name__ == "__main__":
    main()
