#!/usr/bin/env python3
"""Standalone regression test for non-destructive scene regeneration."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import wave

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_segment_revision_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
folder_paths.output_directory = str(ROOT)
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


class FakeImages:
    shape = (5, 1, 1, 3)

    def __getitem__(self, _key):
        return self


class FakeBlendImages(FakeImages):
    shape = (7, 1, 1, 3)


def main():
    with tempfile.TemporaryDirectory() as tempdir:
        folder_paths.output_directory = tempdir
        chain._compact_latent = lambda _latent: {"samples": [b"video", b"audio"]}
        chain._write_run_archives = lambda *_args, **_kwargs: {}
        chain._archive_media_metadata = lambda _archives: {}

        def save_checkpoint(_tensors, path, metadata=None):
            pathlib.Path(path).write_bytes(
                json.dumps(metadata or {}, sort_keys=True).encode("utf-8"))

        def save_video(_images, path, *_args, **_kwargs):
            pathlib.Path(path).write_bytes(
                ("video:" + pathlib.Path(path).name).encode("utf-8"))

        chain._st_save = save_checkpoint
        chain._write_segment_video = save_video

        plan = {
            "run_name": "revision_test",
            "plan_hash": "plan",
            "prompt_prefix": "",
            "segment_crf": 18,
            "compatibility": {
                "audio_mode": "source_track",
                "context_length": 2,
                "video_blend_frames": 2,
            },
            "shots": [{
                "id": "scene_one",
                "prompt": "first take",
                "scene_prompt": "first take",
                "prompt_hash": "prompt-hash",
                "seed": 1,
                "steps": 5,
                "raw_frames": 7,
                "delivered_frames": 5,
                "generation_start_frame": 0,
            }],
        }
        state = {"plan": plan, "index": 1}
        generated_audio = {
            "waveform": torch.zeros(
                (1, 2, round(5 / chain.FPS * 8000)), dtype=torch.float32),
            "sample_rate": 8000,
        }
        saver = chain.MiniMaxH3ChainSegmentSave()
        try:
            saver.save(state, FakeImages(), object(), generated_audio)
        except ValueError as exc:
            assert "images_with_overlap" in str(exc)
        else:
            raise AssertionError("enabled blending accepted no overlap input")
        first_result = saver.save(
            state, FakeImages(), object(), generated_audio,
            FakeBlendImages())
        first = first_result["result"][0]
        first_paths = {
            key: pathlib.Path(chain._absolute_output_path(first[key]))
            for key in ("segment", "checkpoint", "prompt_file",
                        "revision_metadata", "generated_audio",
                        "blend_segment")
        }
        assert all(path.is_file() for path in first_paths.values())
        assert first_result["ui"]["images"] == [
            chain._video_output_item(str(first_paths["segment"]))]
        assert first_result["ui"]["animated"] == (True,)
        assert first["generated_audio_sha256"] == chain._file_sha256(
            str(first_paths["generated_audio"]))
        assert first["scene_dependency"]["version"] == (
            chain.SCENE_DEPENDENCY_VERSION)
        assert set(first["scene_dependency"]["scopes"]) == set(
            chain.DEPENDENCY_SCOPES)
        with wave.open(str(first_paths["generated_audio"]), "rb") as audio_file:
            assert audio_file.getnchannels() == 2
            assert audio_file.getframerate() == 8000
            assert audio_file.getnframes() == round(5 / chain.FPS * 8000)

        plan["shots"][0].update({
            "prompt": "second take",
            "scene_prompt": "second take",
            "prompt_hash": "replacement-hash",
            "seed": 2,
        })
        second_result = saver.save(
            state, FakeImages(), object(), generated_audio,
            FakeBlendImages())
        second = second_result["result"][0]
        assert second["revision"] != first["revision"]
        assert second["supersedes"] == first["revision_metadata"]
        assert second["generated_audio"] != first["generated_audio"]
        assert second["blend_segment"] != first["blend_segment"]
        assert second["blend_frames"] == 2
        assert all(path.is_file() for path in first_paths.values())
        assert second_result["ui"]["images"] == [chain._video_output_item(
            chain._absolute_output_path(second["segment"]))]
        assert second_result["ui"]["animated"] == (True,)

        current = json.loads(pathlib.Path(
            chain._absolute_output_path(second["metadata"])
        ).read_text(encoding="utf-8"))
        archived = json.loads(first_paths["revision_metadata"].read_text(
            encoding="utf-8"))
        assert current["segment"]["revision"] == second["revision"]
        assert current["segment"]["prompt"] == "second take"
        assert current["scene_dependency"] == second["scene_dependency"]
        assert archived["segment"]["revision"] == first["revision"]
        assert archived["segment"]["prompt"] == "first take"

    print("H3 segment revisions: regeneration advances the active pointer and "
          "retains the previous take's video, checkpoint, prompt, and WAV")


if __name__ == "__main__":
    main()
