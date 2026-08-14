#!/usr/bin/env python3
"""Standalone H3 run discovery and Plan restoration checks."""

import json
import pathlib
import tempfile

from run_manager import RunArchiveManager, _workflow_inputs


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def main():
    old_widgets = [
        '{"shots":[{"prompt":"old"}]}', "old_run", "", 960, 544,
        22, "video", "head", "disabled", "source_track", 22, 15.0,
        20, 0, 18,
    ]
    old_restore = _workflow_inputs({
        "nodes": [{"type": "MiniMaxH3ChainPlan",
                   "widgets_values": old_widgets}],
    }, "old_run")
    assert old_restore["segment_crf"] == 18
    assert old_restore["video_blend_frames"] == 0
    assert old_restore["continuation_mode"] == "guide"

    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        exact = root / "h3_chains" / "variant_exact"
        editor_plan = {
            "prompt_prefix": "Shared.",
            "shots": [{"id": "one", "prompt": "Archived prompt.", "length": 22}],
        }
        write(exact / "plan.json", {
            "format": "h3_chain_plan_archive_v1",
            "run_name": "variant_exact",
            "editor_plan": editor_plan,
            "compatibility": {
                "width": 960, "height": 544, "context_length": 22,
                "generation_fingerprint": "",
            },
        })
        exact_inputs = {
            "plan_json": json.dumps(editor_plan),
            "run_name": "variant_exact",
            "generation_fingerprint": "models-v3",
            "width": 1280,
            "height": 704,
            "context_length": 39,
            "encode_mode": "video",
            "anchor_mode": "head",
            "crop": "center",
            "audio_mode": "generated_audio",
            "audio_context_length": 22,
            "default_duration_seconds": 10.0,
            "default_steps": 30,
            "base_seed": "18446744073709551615",
            "segment_crf": 17,
            "video_blend_frames": 22,
            "continuation_mode": "masked_av",
        }
        write(exact / "api_prompt.json", {
            "12": {"class_type": "MiniMaxH3ChainPlan", "inputs": exact_inputs},
        })
        write(exact / "checkpoints" / "clip_0001.json", {"segment": {}})

        fallback = root / "h3_chains" / "variant_fallback"
        write(fallback / "plan.json", {
            "format": "h3_chain_plan_archive_v1",
            "run_name": "variant_fallback",
            "prompt_prefix": "Fallback shared.",
            "shots": [{
                "id": "fallback", "scene_prompt": "Fallback prompt.",
                "raw_frames": 39, "steps": 20, "seed": 9,
            }],
            "compatibility": {
                "width": 768, "height": 448, "context_length": 5,
                "encode_mode": "frames", "anchor_mode": "before",
                "crop": "disabled", "audio_mode": "source_track",
                "audio_context_length": 5, "generation_fingerprint": "old",
            },
            "segment_crf": 19,
        })

        manager = RunArchiveManager(temporary)
        runs = manager.list_runs()
        assert {item["run_name"] for item in runs} == {
            "variant_exact", "variant_fallback"}
        exact_summary = next(item for item in runs if item["run_name"] == "variant_exact")
        assert exact_summary["scene_count"] == 1
        assert exact_summary["checkpoint_count"] == 1
        assert exact_summary["restorable"]

        loaded = manager.load_run("variant_exact")
        assert json.loads(loaded["plan_inputs"]["plan_json"]) == editor_plan
        assert {key: value for key, value in loaded["plan_inputs"].items()
                if key != "plan_json"} == {
                    key: value for key, value in exact_inputs.items()
                    if key != "plan_json"}
        assert loaded["scene_count"] == 1
        assert loaded["sources"][-1] == "api_prompt.json"
        plan_only = manager.load_plan("variant_exact")
        assert plan_only["plan_inputs"] == loaded["plan_inputs"]
        assert "assets" not in plan_only

        # Connected API inputs are skipped, leaving the effective archived
        # fallback value intact instead of replacing a graph connection.
        linked = dict(exact_inputs)
        linked["generation_fingerprint"] = [99, 0]
        linked["base_seed"] = 18446744073709551615
        write(exact / "api_prompt.json", {
            "12": {"class_type": "MiniMaxH3ChainPlan", "inputs": linked},
        })
        linked_restore = manager.load_run("variant_exact")["plan_inputs"]
        assert linked_restore["generation_fingerprint"] == ""
        assert linked_restore["base_seed"] == "18446744073709551615"

        restored = manager.load_run("variant_fallback")["plan_inputs"]
        assert restored["run_name"] == "variant_fallback"
        assert restored["width"] == 768
        assert restored["anchor_mode"] == "before"
        assert restored["segment_crf"] == 19
        assert restored["video_blend_frames"] == 0
        assert restored["continuation_mode"] == "guide"
        restored_plan = json.loads(restored["plan_json"])
        assert restored_plan["shots"][0]["prompt"] == "Fallback prompt."
        assert restored_plan["shots"][0]["seed"] == "9"

    print("H3 Run Manager: discovery, exact API restoration and Plan fallback pass")


if __name__ == "__main__":
    main()
