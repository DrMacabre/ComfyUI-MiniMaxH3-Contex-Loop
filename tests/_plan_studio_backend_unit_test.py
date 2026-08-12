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
        checkpoint = checkpoints / "clip_0001.revision.safetensors"
        segment.write_bytes(b"video")
        checkpoint.write_bytes(b"checkpoint")
        (checkpoints / "clip_0001.json").write_text(json.dumps({
            "segment": {
                "index": 1,
                "id": "intro",
                "segment": str(segment.relative_to(temporary)),
                "checkpoint": str(checkpoint.relative_to(temporary)),
                "segment_sha256": video_hash,
            },
        }), encoding="utf-8")

        first = await chain._list_saved_checkpoints(Request())
        first_payload = json.loads(first.text)
        assert first_payload["checkpoints"][0]["ready"] is True
        assert "preview_video" not in first_payload["checkpoints"][0]

        preview = reviews / (
            "clip_0001.%s.audiohash.review.mp4" % video_hash[:12])
        preview.write_bytes(b"synchronized preview")
        second = await chain._list_saved_checkpoints(Request())
        item = json.loads(second.text)["checkpoints"][0]
        assert item["video"]["filename"] == segment.name
        assert item["preview_video"]["filename"] == preview.name


if __name__ == "__main__":
    asyncio.run(check())
    print("H3 Plan Studio backend: saved segment and synchronized preview discovery pass")
