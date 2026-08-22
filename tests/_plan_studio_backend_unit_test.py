#!/usr/bin/env python3
"""Standalone saved-segment discovery checks for Plan Studio."""

import asyncio
import importlib.util
import json
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_plan_studio_backend_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.output_directory = str(ROOT)
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

server = types.ModuleType("server")
server.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules["server"] = server

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


class Request:
    query = {"run_name": "studio"}


async def check():
    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        run = pathlib.Path(temporary) / "h3_chains" / "studio"
        segments = run / "segments"
        checkpoints = run / "checkpoints"
        reviews = run / "reviews"
        segments.mkdir(parents=True)
        checkpoints.mkdir(parents=True)
        reviews.mkdir(parents=True)

        video_hash = "abcdef1234567890"
        segment = segments / "clip_0001.revision.mp4"
        generated_audio = run / "generated_audio" / "clip_0001.revision.wav"
        checkpoint = checkpoints / "clip_0001.revision.safetensors"
        segment.write_bytes(b"video")
        generated_audio.parent.mkdir(parents=True)
        generated_audio.write_bytes(b"audio")
        checkpoint.write_bytes(b"checkpoint")
        (checkpoints / "clip_0001.json").write_text(json.dumps({
            "segment": {
                "index": 1,
                "id": "intro",
                "segment": str(segment.relative_to(temporary)),
                "generated_audio": str(generated_audio.relative_to(temporary)),
                "checkpoint": str(checkpoint.relative_to(temporary)),
                "segment_sha256": video_hash,
                "raw_frames": 362,
                "delivered_frames": 340,
            },
        }), encoding="utf-8")

        first = await chain._list_saved_checkpoints(Request())
        first_payload = json.loads(first.text)
        assert first_payload["checkpoints"][0]["ready"] is True
        assert first_payload["checkpoints"][0]["delivered_frames"] == 340
        assert first_payload["checkpoints"][0]["audio"]["filename"] == (
            generated_audio.name)
        assert "preview_video" not in first_payload["checkpoints"][0]

        preview = reviews / (
            "clip_0001.%s.audiohash.review.mp4" % video_hash[:12])
        preview.write_bytes(b"synchronized preview")
        second = await chain._list_saved_checkpoints(Request())
        item = json.loads(second.text)["checkpoints"][0]
        assert item["video"]["filename"] == segment.name
        assert item["audio"]["filename"] == generated_audio.name
        assert item["preview_video"]["filename"] == preview.name

        motion_file = pathlib.Path(temporary) / "motion.mp4"
        motion_file.write_bytes(b"motion source")
        descriptor = {
            "version": chain.LAZY_MOTION_SOURCE_VERSION,
            "kind": "lazy_motion_path",
            "path": str(motion_file),
            "skip_seconds": 2.0,
            "file_sha256": "1" * 64,
            "frame_count": 1000,
            "audio": None,
        }
        references = chain._append_tagged_reference(
            None, kind="video", tag="motion", value=descriptor,
            content_hash="2" * 64, timeline_mode="sequential")
        references = chain._decorate_motion_reference(
            references, "<Subject 1>", "walk cycle", "384")
        plan = {
            "run_name": "studio",
            "shots": [{
                "index": 1, "id": "intro", "delivered_frames": 340,
            }],
        }
        report = {"scenes": [{
            "index": 1, "id": "intro", "references": [{
                "tag": "motion", "kind": "video",
                "semantic_role": "motion",
                "window": {
                    "mode": "sequential", "start_frame": 100,
                    "end_frame": 462, "frame_count": 362,
                },
            }],
        }]}
        source_payload = chain._register_plan_studio_source_previews(
            plan, report, references, None)
        assert source_payload["token"]
        source_scene = source_payload["scenes"][0]
        assert source_scene["delivered_frames"] == 340
        assert source_scene["references"][0]["compare_offset_frames"] == 22
        record = chain._PLAN_STUDIO_SOURCE_PREVIEWS[
            source_payload["token"]]["records"]["1:0"]
        assert record["video_seek_seconds"] == 2.0 + 100 / 24

        captured = []
        original_usable = chain._usable_ffmpeg
        original_run = chain._run_ffmpeg
        try:
            chain._usable_ffmpeg = lambda: "/fake/ffmpeg"

            def fake_run(command, timeout_seconds=None):
                captured.append((command, timeout_seconds))
                pathlib.Path(command[-1]).write_bytes(b"preview mp4")

            chain._run_ffmpeg = fake_run
            cached = pathlib.Path(
                chain._build_plan_studio_source_preview(record))
        finally:
            chain._usable_ffmpeg = original_usable
            chain._run_ffmpeg = original_run
        assert cached.read_bytes() == b"preview mp4"
        command = captured[0][0]
        assert "fps=24" in command[command.index("-vf") + 1]
        assert command[command.index("-t") + 1] == "15.083333333"


if __name__ == "__main__":
    asyncio.run(check())
    print("H3 Plan Studio backend: saved segment and synchronized preview discovery pass")
