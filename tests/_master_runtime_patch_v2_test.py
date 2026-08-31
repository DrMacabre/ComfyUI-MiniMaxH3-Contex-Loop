#!/usr/bin/env python3
"""Regression for runtime smoke 02 master metadata patch."""

from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_patch_v2", ROOT / "tools" / "patch_master_runtime_v2.py")
patcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(patcher)


def main():
    loader = {
        "id": 101,
        "type": "LoadAudio",
        "title": "AUDIO REF 1 — LOAD AUDIO",
        "inputs": [],
        "outputs": [{"name": "AUDIO", "type": "AUDIO", "links": [8]}],
        "widgets_values": [""],
        "properties": {"Node name for S&R": "LoadAudio"},
    }
    binding = {
        "binding_id": "h3-audio-ref-01",
        "label": "OLD PROJECT AUDIO",
        "role": "audio_reference",
        "node_id": "101",
        "node_type": "LoadAudio",
        "node_title": "OLD PROJECT AUDIO",
        "output_slot": 0,
        "output_type": "AUDIO",
        "widget_name": "audio",
        "original_value": "old.wav",
    }
    manager = {
        "id": 200,
        "type": "MiniMaxH3ChainRunManager",
        "inputs": [{"name": "plan", "type": "H3_CHAIN_PLAN", "link": None}],
        "outputs": [],
        "widgets_values": [],
        "widgets_values_named": {
            "asset_bindings_json": json.dumps([binding]),
        },
        "properties": {
            "Node name for S&R": "MiniMaxH3ChainRunManager",
            "h3_persist_detached_asset_bindings": True,
        },
    }
    workflow = {"nodes": [loader, manager], "links": []}

    patched, report = patcher.patch(workflow)
    assert patched is workflow
    assert report["status"] == "RUNTIME SMOKE 02 PATCHED / RETEST REQUIRED"
    assert report["detached_asset_templates"] == 1
    assert report["active_asset_bindings"] == 0
    assert report["inactive_blank_assets_omitted"] == 1
    assert report["master_generated_audio_latent_carry"] == "off"
    assert report["exact_final_timeline_guard"] == "unchanged / fail-closed"

    templates = manager["properties"]["h3_detached_asset_templates"]
    assert len(templates) == 1
    assert templates[0]["label"] == "AUDIO REF 1 — LOAD AUDIO"
    assert templates[0]["original_value"] == ""
    assert loader["properties"]["h3_asset_binding_ids"]["0"] == "h3-audio-ref-01"
    assert json.loads(manager["widgets_values_named"]["asset_bindings_json"]) == []

    # A real selected file remains active.
    loader["widgets_values"][0] = "voice.wav"
    patched, report = patcher.patch(workflow)
    assert report["active_asset_bindings"] == 1
    active = json.loads(manager["widgets_values_named"]["asset_bindings_json"])
    assert active[0]["original_value"] == "voice.wav"

    print("PASS master runtime smoke 02 metadata patch")


if __name__ == "__main__":
    main()
