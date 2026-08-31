#!/usr/bin/env python3
"""Regression for runtime smoke 01 workflow surgery."""

from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_patch", ROOT / "tools" / "patch_master_runtime_v1.py")
patcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(patcher)


def inp(name, typ, link=None, widget=False, optional=False):
    value = {"name": name, "localized_name": name, "type": typ, "link": link}
    if widget:
        value["widget"] = {"name": name}
    if optional:
        value["shape"] = 7
    return value


def out(name, typ, links=None):
    return {"name": name, "localized_name": name, "type": typ, "links": links}


def node(nid, typ, inputs=None, outputs=None, title=None, named=None, props=None):
    return {
        "id": nid,
        "type": typ,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "title": title or typ,
        "properties": {"Node name for S&R": typ, **(props or {})},
        "widgets_values": [],
        "widgets_values_named": named or {},
    }


def main():
    binding = {
        "binding_id": "h3-audio-ref-01",
        "label": "AUDIO REF 1 — LOAD AUDIO",
        "role": "audio_reference",
        "node_id": "1",
        "node_type": "LoadAudio",
        "node_title": "AUDIO REF 1 — LOAD AUDIO",
        "output_slot": 0,
        "output_type": "AUDIO",
        "widget_name": "audio",
        "original_value": "",
    }
    loader = node(1, "LoadAudio", outputs=[out("AUDIO", "AUDIO", [1])])
    manager = node(
        10,
        "MiniMaxH3ChainRunManager",
        inputs=[inp("plan", "H3_CHAIN_PLAN"), inp("asset_0", "*", 1, optional=True)],
        named={"asset_bindings_json": json.dumps([binding])},
    )
    manifest = node(30, "ManifestSource", outputs=[out("manifest", "H3_CHAIN_MANIFEST", [2])])
    vae = node(31, "VAE", outputs=[out("VAE", "VAE", [3, 5])])
    config = node(32, "Config", outputs=[out("export_config", "H3_MASTER_EXPORT_CONFIG", [4, 6])])
    final = node(
        20,
        "MiniMaxH3MasterExport",
        inputs=[
            inp("manifest", "H3_CHAIN_MANIFEST", 2),
            inp("video_vae", "VAE", 3),
            inp("export_config", "H3_MASTER_EXPORT_CONFIG", 4),
            inp("filename", "STRING", widget=True),
            inp("source_audio", "AUDIO", optional=True),
        ],
        outputs=[out("video", "VIDEO")],
        title="FINAL MASTER EXPORT",
    )
    recovery = node(
        21,
        "MiniMaxH3MasterExport",
        inputs=[
            inp("manifest", "H3_CHAIN_MANIFEST"),
            inp("video_vae", "VAE", 5),
            inp("export_config", "H3_MASTER_EXPORT_CONFIG", 6),
            inp("filename", "STRING", widget=True),
            inp("source_audio", "AUDIO", optional=True),
        ],
        outputs=[out("video", "VIDEO")],
        title="RECOVERY MASTER EXPORT 1",
    )
    workflow = {
        "nodes": [loader, manager, manifest, vae, config, final, recovery],
        "links": [
            [1, 1, 0, 10, 1, "*"],
            [2, 30, 0, 20, 0, "H3_CHAIN_MANIFEST"],
            [3, 31, 0, 20, 1, "VAE"],
            [4, 32, 0, 20, 2, "H3_MASTER_EXPORT_CONFIG"],
            [5, 31, 0, 21, 1, "VAE"],
            [6, 32, 0, 21, 2, "H3_MASTER_EXPORT_CONFIG"],
        ],
    }

    patched, report = patcher.patch(workflow)
    assert report["status"] == "RUNTIME SMOKE 01 PATCHED / RETEST REQUIRED"
    assert report["detached_run_manager_asset_links"] == 1
    assert report["preserved_asset_bindings"] == 1
    assert report["inactive_safe_recovery_exports"] == 1

    assert manager["inputs"][1]["link"] is None
    assert manager["properties"]["h3_persist_detached_asset_bindings"] is True
    assert 1 not in [link[0] for link in patched["links"]]
    assert loader["outputs"][0]["links"] is None

    assert final["type"] == "MiniMaxH3MasterExport"
    assert final["inputs"][0]["name"] == "manifest"
    assert final["inputs"][0]["link"] == 2

    assert recovery["type"] == "MiniMaxH3MasterRecoveryExport"
    assert [item["name"] for item in recovery["inputs"]] == [
        "video_vae", "export_config", "filename", "manifest", "source_audio"]
    assert recovery["inputs"][0]["link"] == 5
    assert recovery["inputs"][1]["link"] == 6
    assert recovery["inputs"][3]["link"] is None
    assert recovery["inputs"][3]["shape"] == 7
    link5 = next(link for link in patched["links"] if link[0] == 5)
    link6 = next(link for link in patched["links"] if link[0] == 6)
    assert link5[4] == 0
    assert link6[4] == 1

    assert not patcher._validate(patched)
    print("PASS master runtime smoke 01 workflow patch")


if __name__ == "__main__":
    main()
