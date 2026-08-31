#!/usr/bin/env python3
"""Synthetic graph regression for tools/build_master_workflow.py."""

from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "master_workflow_builder", ROOT / "tools" / "build_master_workflow.py")
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(builder)


def inp(name, typ, link=None, widget=False, optional=False):
    value = {"name": name, "localized_name": name, "type": typ, "link": link}
    if widget:
        value["widget"] = {"name": name}
    if optional:
        value["shape"] = 7
    return value


def out(name, typ, links=None):
    return {"name": name, "localized_name": name, "type": typ, "links": links}


def node(nid, typ, inputs, outputs, title=None, widgets=None, named=None, binding=None):
    props = {"Node name for S&R": typ}
    if binding:
        props["h3_asset_binding_ids"] = {"0": binding}
    return {
        "id": nid, "type": typ, "pos": [nid * 10, 0], "size": [320, 120],
        "flags": {}, "order": nid, "mode": 0, "inputs": inputs,
        "outputs": outputs, "title": title or typ, "properties": props,
        "widgets_values": widgets or [], "widgets_values_named": named or {},
    }


def make_workflow():
    nodes = []
    links = []
    lid = 1

    def connect(origin, oslot, target, tslot, typ):
        nonlocal lid
        links.append([lid, origin["id"], oslot, target["id"], tslot, typ])
        origin["outputs"][oslot]["links"] = list(origin["outputs"][oslot].get("links") or []) + [lid]
        target["inputs"][tslot]["link"] = lid
        lid += 1

    vae = node(3, "VAELoader", [inp("vae_name", "COMBO", widget=True)],
               [out("VAE", "VAE")], "H3 Video VAE", ["video_vae"], {"vae_name": "video_vae"})
    nodes.append(vae)
    for i in range(1, 10):
        loader = node(
            100 + i, "LoadImage",
            [inp("image", "COMBO", widget=True), inp("upload", "IMAGEUPLOAD", widget=True)],
            [out("IMAGE", "IMAGE"), out("MASK", "MASK")],
            "OLD IMAGE %d" % i, ["old.png", "image"],
            {"image": "old.png", "upload": "image"}, "h3-ref-slot-%02d" % i)
        nodes.append(loader)

    source_audio = node(
        1951, "LoadAudio",
        [inp("audio", "COMBO", widget=True), inp("audioUI", "AUDIO_UI", widget=True),
         inp("upload", "AUDIOUPLOAD", widget=True)], [out("AUDIO", "AUDIO")],
        "AUDIO INPUT — OLD", ["old.wav", None, None],
        {"audio": "old.wav", "upload": None}, "h3-source-audio-01")
    nodes.append(source_audio)

    old_ref = node(
        1952, "MiniMaxH3TaggedAudioReference",
        [inp("audio", "AUDIO"), inp("previous", "H3_TAGGED_REFERENCES", optional=True),
         inp("tag", "STRING", widget=True)],
        [out("references", "H3_TAGGED_REFERENCES"), out("reference_fingerprint", "STRING")],
        "OLD AUDIO REF", ["audio_ref"], {"tag": "audio_ref"})
    nodes.append(old_ref)

    plan = node(
        1700, "MiniMaxH3ChainPlan",
        [inp("chain_policy", "H3_CHAIN_POLICY", optional=True),
         inp("plan_json", "STRING", widget=True), inp("run_name", "STRING", widget=True),
         inp("generation_fingerprint", "STRING", optional=True)],
        [out("plan", "H3_CHAIN_PLAN")], "OLD PLAN",
        [json.dumps({"shots": [{"id": "old", "prompt": "old creative prompt"}]}), "old_run"],
        {"plan_json": json.dumps({"shots": [{"id": "old", "prompt": "old creative prompt"}]}),
         "run_name": "old_run"})
    nodes.append(plan)

    loop_start = node(
        1701, "MiniMaxH3ChainLoopStart",
        [inp("plan", "H3_CHAIN_PLAN"), inp("source_audio", "AUDIO", optional=True),
         inp("external_context", "H3_EXTERNAL_CONTEXT", optional=True)],
        [out("flow", "H3_CHAIN_FLOW"), out("state", "H3_CHAIN_STATE")])
    nodes.append(loop_start)

    current = node(
        1702, "MiniMaxH3ChainCurrent", [inp("flow", "H3_CHAIN_FLOW")],
        [out("state", "H3_CHAIN_STATE"), out("source_audio_slice", "AUDIO")])
    nodes.append(current)

    ref2va = node(
        110, "MiniMaxH3TaggedReferenceToVideo",
        [inp("vae", "VAE"), inp("references", "H3_TAGGED_REFERENCES"),
         inp("state", "H3_CHAIN_STATE", optional=True)],
        [out("positive", "CONDITIONING"), out("latent", "LATENT")])
    nodes.append(ref2va)

    context = node(
        1703, "MiniMaxH3ChainContext", [inp("latent", "LATENT")],
        [out("latent", "LATENT")])
    nodes.append(context)

    decoded_audio = node(
        2009, "VAEDecodeAudio", [inp("samples", "LATENT"), inp("vae", "VAE")],
        [out("AUDIO", "AUDIO")])
    nodes.append(decoded_audio)
    trim = node(
        132, "MiniMaxH3LoopTrim", [inp("latent", "LATENT"), inp("audio", "AUDIO")],
        [out("latent", "LATENT"), out("audio", "AUDIO")])
    nodes.append(trim)

    loop_end = node(
        1705, "MiniMaxH3ChainLoopEnd", [inp("segment", "H3_CHAIN_SEGMENT", optional=True)],
        [out("manifest", "H3_CHAIN_MANIFEST")])
    nodes.append(loop_end)
    manifest_load = node(
        1800, "MiniMaxH3ChainManifestLoad", [inp("manifest_path", "STRING", widget=True)],
        [out("manifest", "H3_CHAIN_MANIFEST")], widgets=[""], named={"manifest_path": ""})
    nodes.append(manifest_load)
    assemble = node(
        1801, "MiniMaxH3ChainAssemble", [inp("manifest", "H3_CHAIN_MANIFEST")],
        [out("video", "VIDEO")])
    nodes.append(assemble)

    manager = node(
        1949, "MiniMaxH3ChainRunManager",
        [inp("plan", "H3_CHAIN_PLAN"), inp("asset_0", "*", optional=True),
         inp("archive_images", "BOOLEAN", widget=True),
         inp("archive_audio", "BOOLEAN", widget=True),
         inp("archive_video", "BOOLEAN", widget=True),
         inp("asset_bindings_json", "STRING", widget=True)],
        [out("plan", "H3_CHAIN_PLAN")], widgets=[True, True, False, "[]"],
        named={"archive_images": True, "archive_audio": True,
               "archive_video": False, "asset_bindings_json": "[]"})
    nodes.append(manager)

    old_policy = node(
        2007, "MiniMaxH3ChainPolicy",
        [inp("incoming_transition", "COMBO", widget=True)],
        [out("chain_policy", "H3_CHAIN_POLICY")])
    nodes.append(old_policy)

    connect(vae, 0, ref2va, 0, "VAE")
    connect(ref2va, 1, context, 0, "LATENT")
    connect(plan, 0, loop_start, 0, "H3_CHAIN_PLAN")
    connect(plan, 0, manager, 0, "H3_CHAIN_PLAN")
    connect(loop_start, 0, current, 0, "H3_CHAIN_FLOW")
    connect(decoded_audio, 0, trim, 1, "AUDIO")
    connect(source_audio, 0, old_ref, 0, "AUDIO")
    connect(old_ref, 0, ref2va, 1, "H3_TAGGED_REFERENCES")
    connect(old_ref, 1, plan, 3, "STRING")
    connect(old_policy, 0, plan, 0, "H3_CHAIN_POLICY")
    connect(manifest_load, 0, assemble, 0, "H3_CHAIN_MANIFEST")

    return {
        "last_node_id": 2009,
        "last_link_id": lid - 1,
        "nodes": nodes,
        "links": links,
        "groups": [{"id": 1, "title": "OLD GROUP", "bounding": [0, 0, 100, 100],
                    "color": "#000000", "flags": {}}],
        "config": {}, "extra": {}, "version": 0.4,
    }


def main():
    migrated, report = builder.migrate(make_workflow())
    assert report["status"] == "STRUCTURE VERIFIED / RUNTIME INCONCLUSIVE"
    assert report["picture_refs"] == 9
    assert report["video_refs"] == 3
    assert report["audio_refs"] == 3
    assert report["recovery_master_exports"] == 1
    assert report["source_audio_lazy"] is True
    assert report["source_video_audio_independent"] is True
    assert report["shared_export_profile"] is True

    types = [n["type"] for n in migrated["nodes"]]
    assert types.count("MiniMaxH3MasterPictureReferenceSlot") == 9
    assert types.count("MiniMaxH3MasterVideoReferenceSlot") == 3
    assert types.count("MiniMaxH3MasterAudioReferenceSlot") == 3
    assert "MiniMaxH3TaggedAudioReference" not in types
    assert "MiniMaxH3ChainPolicy" not in types
    assert types.count("MiniMaxH3MasterExportProfile") == 1
    assert types.count("MiniMaxH3MasterExport") == 2

    titles = {n.get("title") for n in migrated["nodes"]}
    assert "SOURCE VIDEO" in titles
    assert "SOURCE / EXTERNAL AUDIO" in titles
    assert "AUDIO MODE" in titles
    assert "CONTINUATION MODE" in titles
    assert "SOURCE VIDEO MODE" in titles
    assert "EXPORT PROFILE — ONE CONTROL FOR ALL OUTPUTS" in titles

    plan = next(n for n in migrated["nodes"] if n["type"] == "MiniMaxH3ChainPlan")
    assert plan["widgets_values_named"]["run_name"] == "h3_master"
    assert "old creative prompt" not in plan["widgets_values_named"]["plan_json"]

    group_titles = [g["title"] for g in migrated["groups"]]
    for title in builder.GROUP_ORDER:
        assert title in group_titles

    # Every group id should be LiteGraph-compatible numeric, unique, and every
    # link must point to a real node/slot (the builder's own validation already
    # enforces the latter before returning).
    group_ids = [g["id"] for g in migrated["groups"]]
    assert all(isinstance(value, int) for value in group_ids)
    assert len(group_ids) == len(set(group_ids))

    print("PASS deterministic Default H3 master workflow migration")


if __name__ == "__main__":
    main()
