#!/usr/bin/env python3
"""Focused mixed-policy checkpoint branch activation regression."""

import asyncio
import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPERS_PATH = ROOT / "tests" / "_checkpoint_revision_unit_test.py"
spec = importlib.util.spec_from_file_location(
    "h3_checkpoint_activation_helpers", HELPERS_PATH)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


async def check():
    with tempfile.TemporaryDirectory() as temporary:
        helpers.folder_paths.output_directory = temporary
        run = pathlib.Path(temporary) / "h3_chains" / "mixed_policy"
        first = "a" * 32
        second = "b" * 32
        first_meta, _ = helpers.write_revision(
            run, 1, first, 1001, active=True, run_name="mixed_policy")
        helpers.write_revision(
            run, 2, second, 1002, predecessor=first_meta,
            run_name="mixed_policy", compatibility={
                "context_length": 39,
                "audio_context_length": 39,
                "audio_mode": "generated_audio",
            })
        selection = {
            "run_name": "mixed_policy",
            "resume_scene": 3,
            "revisions": [
                {"scene": 1, "revision": first},
                {"scene": 2, "revision": second},
            ],
        }

        strict = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest(selection))
        assert strict.status == 400
        assert "different Plan compatibility" in json.loads(
            strict.text)["error"]
        assert not (run / "checkpoints" / "clip_0002.json").exists()

        promoted = await helpers.chain._restore_checkpoint_revisions(
            helpers.JsonRequest({**selection, "activate_only": True}))
        assert promoted.status == 200
        assert json.loads(promoted.text)["activate_only"] is True
        assert json.loads((
            run / "checkpoints" / "clip_0002.json").read_text())[
                "segment"]["revision"] == second
        graph = helpers.chain.CheckpointGraphManager(
            temporary).graph("mixed_policy")
        assert [item["revision"] for item in graph["revisions"]
                if item["active"]] == [first, second]
        assert graph["branches"][0]["active"] is True


if __name__ == "__main__":
    asyncio.run(check())
    print("H3 checkpoint activation: mixed historical policies pass")
