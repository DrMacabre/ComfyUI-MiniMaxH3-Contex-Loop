#!/usr/bin/env python3
"""0.5 preflight is model-free, structured, and shared by Studio/Start."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_preflight_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda: "test"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def make_plan(run_name):
    policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("source", "on", "off"),
        chain._contract_transition_policy(
            "guide", expert_override=True,
            continuation_mode="guide", context_length=5),
        audio_context_length=5)
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "Opening action.", "length": 22},
            {"id": "two", "prompt": "Continuation action.", "length": 22},
        ]}),
        run_name, 64, 64, 5, "video", "head", "disabled",
        "source_track", 5, 1.0, 8, 7, 18, "stack:auto:v1", 0,
        "guide", policy)


def deferred_timeline(frames):
    sample_rate = 48000
    samples = round(frames / 24 * sample_rate)
    audio = {
        "waveform": torch.linspace(-0.5, 0.5, samples).reshape(1, 1, -1),
        "sample_rate": sample_rate,
    }
    audio_hash = chain._audio_fingerprint(audio)
    timeline_hash = chain._fingerprint({"audio": audio_hash, "frames": frames})
    return {
        "version": chain.SOURCE_TIMELINE_VERSION,
        "kind": "source_timeline",
        "fps": 24,
        "origin": {"source_fps": 24.0, "skip_first_frames": 0,
                   "skip_seconds": 0.0},
        "extent": {"frame_count": frames,
                   "duration_seconds": frames / 24.0},
        "video": None,
        "audio": {"kind": "deferred_tensor", "value": audio,
                  "sample_rate": sample_rate, "channels": 1,
                  "duration_seconds": frames / 24.0,
                  "timeline_offset_seconds": 0.0,
                  "content_sha256": audio_hash},
        "fingerprints": {"video": "", "audio": audio_hash,
                         "timeline": timeline_hash},
        "recovery": {"video_path": "", "audio_path": "",
                     "deferred_audio_requires_materialization": True},
    }


def semantic_plan(prompt):
    policy = chain._contract_compose_chain_policy(
        chain._contract_audio_policy("generated", "off", "on"),
        chain._contract_transition_policy("cut"),
        audio_context_length=0)
    return chain._normalize_plan(
        json.dumps({"shots": [{
            "id": "semantic", "prompt": prompt, "length": 124,
        }]}),
        "semantic_preflight", 64, 64, 1, "video", "head", "disabled",
        "generated_audio", 0, 5.0, 8, 7, 18, "stack:auto:v1", 0,
        "guide", policy)


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    plan = make_plan("preflight")
    timeline = deferred_timeline(39)

    prepared, report = chain._preflight_chain(
        plan, source_timeline=timeline)
    assert report["ok"] is True
    assert report["status"] == "warning"  # isolated test lacks Comfy runtime
    assert report["source"]["required_frames"] == 39
    assert report["source"]["last_complete_scene"] == 2
    assert [scene["overlap_trim_frames"] for scene in report["scenes"]] == [0, 5]
    assert report["scenes"][1]["source_start_frame"] == 17
    assert prepared["compatibility"]["source_timeline_fingerprint"] == (
        timeline["fingerprints"]["timeline"])
    assert not root.exists() or not any(root.iterdir())

    studio = chain.MiniMaxH3ChainPlanStudio().passthrough(
        plan, source_timeline=timeline)
    assert studio["result"][0] is plan and studio["result"][2] is True
    assert json.loads(studio["result"][4])["version"] == chain.PREFLIGHT_VERSION
    assert "h3_plan_studio_source_timeline" in studio["ui"]

    short = deferred_timeline(30)
    _prepared, failed = chain._preflight_chain(
        plan, source_timeline=short)
    assert failed["ok"] is False
    assert failed["source"]["shortfall_frames"] == 9
    assert failed["source"]["last_complete_scene"] == 1
    issue = next(item for item in failed["errors"]
                 if item["code"] == "source_audio_too_short")
    assert issue["action"]

    materialized = []
    original = chain._materialize_source_timeline_audio
    chain._materialize_source_timeline_audio = (
        lambda *args, **kwargs: materialized.append(True))
    try:
        try:
            chain.MiniMaxH3ChainLoopStart().start(
                plan, 1, source_timeline=short)
        except ValueError as exc:
            assert "source_audio_too_short" in str(exc)
        else:
            raise AssertionError("Loop Start accepted failed preflight")
    finally:
        chain._materialize_source_timeline_audio = original
    assert materialized == []

    tagged_picture = chain.MiniMaxH3TaggedPictureReference().add(
        torch.zeros((1, 32, 32, 3)), "replacement")[0]
    _prepared, semantic = chain._preflight_chain(
        semantic_plan(
            "Use @replacement and #replacement[0.00s] plus "
            "#replacement[4.75s]."),
        tagged_references=tagged_picture)
    assert semantic["ok"] is True
    assert semantic["scenes"][0]["semantic_anchors"] == [
        {"tag": "replacement", "timestamp_seconds": 0.0},
        {"tag": "replacement", "timestamp_seconds": 4.75},
    ]
    assert semantic["scenes"][0]["references"][0]["tag"] == "replacement"

    dedicated_draft = chain.MiniMaxH3SemanticPictureAnchor().add(
        torch.zeros((1, 32, 32, 3)), "semantic_only")[0]
    dedicated_bundle = chain.MiniMaxH3SemanticAnchorBundle().bundle(
        dedicated_draft, "512", "timestamped_video",
        references=tagged_picture)[0]
    _prepared, dedicated = chain._preflight_chain(
        semantic_plan("Use @replacement and #semantic_only[0.00s]."),
        tagged_references=tagged_picture,
        semantic_anchors=dedicated_bundle)
    assert dedicated["ok"] is True
    assert dedicated["references"]["semantic_route"] == "bundle"
    assert dedicated["references"]["registered_semantic_tags"] == [
        "semantic_only"]
    assert [item["tag"] for item in dedicated["scenes"][0]["references"]] == [
        "replacement"]

    _prepared, semantic_only = chain._preflight_chain(
        semantic_plan("Use #semantic_only[0.00s]."),
        semantic_anchors=dedicated_bundle)
    assert semantic_only["ok"] is True
    assert semantic_only["references"]["route"] == "none"
    assert semantic_only["references"]["semantic_route"] == "bundle"
    assert semantic_only["references"]["registered_tags"] == []
    assert semantic_only["references"]["registered_semantic_tags"] == [
        "semantic_only"]

    _prepared, unknown_anchor = chain._preflight_chain(
        semantic_plan("Use #missing[1.00s]."),
        tagged_references=tagged_picture)
    assert any(item["code"] == "unresolved_semantic_anchor"
               for item in unknown_anchor["errors"])

    _prepared, late_anchor = chain._preflight_chain(
        semantic_plan("Use #replacement[9.00s]."),
        tagged_references=tagged_picture)
    assert any(item["code"] == "semantic_anchor_out_of_range"
               for item in late_anchor["errors"])

print("H3 preflight: exact timing, source shortfall, semantic anchors, Studio report, and early Loop Start block pass")
