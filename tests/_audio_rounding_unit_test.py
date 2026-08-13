#!/usr/bin/env python3
"""Standalone regressions for cumulative H3 audio sample budgeting."""

import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_audio_rounding_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def generated_audio_case(frames, saved_samples):
    loads = iter([
        {"delivered_audio": torch.ones((1, 2, count))}
        for count in saved_samples
    ])
    chain._st_load = lambda _path: next(loads)
    return chain._generated_audio({"segments": [
        {
            "index": index,
            "checkpoint": "clip_%04d.safetensors" % index,
            "sample_rate": 8000,
            "delivered_frames": frame_count,
        }
        for index, frame_count in enumerate(frames, start=1)
    ]})


def main():
    original_st_load = chain._st_load
    original_prelude_audio = chain._prelude_audio
    try:
        trimmed = generated_audio_case([5, 5], [1667, 1667])
        assert trimmed["waveform"].shape[-1] == round(10 / 24 * 8000)

        padded = generated_audio_case([4, 4], [1333, 1333])
        assert padded["waveform"].shape[-1] == round(8 / 24 * 8000)
        assert torch.count_nonzero(padded["waveform"][..., -1:]) == 0

        chain._prelude_audio = lambda _record: {
            "waveform": torch.ones((1, 2, 1667)), "sample_rate": 8000}
        joined = chain._audio_with_prelude(
            {"waveform": torch.ones((1, 2, 1667)), "sample_rate": 8000},
            5, {"frame_count": 5})
        assert joined["waveform"].shape[-1] == round(10 / 24 * 8000)

        one_short = chain._fit_pyav_audio_samples(
            torch.ones((2, 226666)), 226667)
        assert one_short.shape[-1] == 226667
        assert torch.count_nonzero(one_short[..., -1:]) == 0
        try:
            chain._fit_pyav_audio_samples(torch.ones((2, 226665)), 226667)
        except ValueError as exc:
            assert "226665 samples; 226667 are required" in str(exc)
        else:
            raise AssertionError("PyAV accepted an audio deficit above one sample")
    finally:
        chain._st_load = original_st_load
        chain._prelude_audio = original_prelude_audio

    print("H3 audio rounding: cumulative scene and prelude boundaries are exact")


if __name__ == "__main__":
    main()
