#!/usr/bin/env python3
"""Structured scene dependencies isolate generation and assembly changes."""

import importlib.util
import json
import pathlib
import sys
import tempfile
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_scene_dependency_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
nodes = types.ModuleType(PACKAGE + ".nodes")
nodes.MiniMaxH3MotionContext = object
nodes._claim_inline_patch_ownership = lambda: "test"
nodes._prepare_native_guide_conditioning = lambda value: value
nodes._resize = lambda *args: None
nodes._streams_from_latent = lambda *args: None
sys.modules[nodes.__name__] = nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def make_plan(context=5):
    return chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "@actor opens.", "length": 39},
            {"id": "two", "prompt": "@actor continues.", "length": 39},
        ]}),
        "dependency-test", 64, 64, context, "video", "head", "disabled",
        "source_track", context, 1.0, 8, 11, 18, "body:auto:v1", 0,
        "guide")


def audio(values):
    return {"waveform": values.reshape(1, 1, -1), "sample_rate": 48000}


plan = make_plan(5)
samples = round(plan["total_delivered_frames"] / 24 * 48000)
base = torch.linspace(-0.8, 0.8, samples)
changed = base.clone()
# Scene 1 consumes frames 0:39. Scene 2 consumes 34:73; change only after 39.
changed[39 * 2000:] *= -1
audio_a = audio(base)
audio_b = audio(changed)
prepared_a = chain._plan_with_source_audio(plan, audio_a)
prepared_b = chain._plan_with_source_audio(plan, audio_b)

scene1_a = chain._scene_dependency_record(
    prepared_a, 1, chain._canonical_source_reference_dependency(
        prepared_a, 1, None, audio_a))
scene1_b = chain._scene_dependency_record(
    prepared_b, 1, chain._canonical_source_reference_dependency(
        prepared_b, 1, None, audio_b))
assert chain._scene_dependency_diffs(scene1_a, scene1_b) == []

scene2_a = chain._scene_dependency_record(
    prepared_a, 2, chain._canonical_source_reference_dependency(
        prepared_a, 2, None, audio_a))
scene2_b = chain._scene_dependency_record(
    prepared_b, 2, chain._canonical_source_reference_dependency(
        prepared_b, 2, None, audio_b))
audio_diffs = chain._scene_dependency_diffs(scene2_a, scene2_b)
assert any(item["scope"] == "scene_generation"
           and item["field"].endswith("pcm_sha256")
           for item in audio_diffs)
assert all(item["scene"] == 2 and item["regeneration_required"]
           for item in audio_diffs)

locked_policy = chain._contract_compose_chain_policy(
    chain._contract_audio_policy("source", "on", "on", "locked"),
    chain._contract_transition_policy("guide"),
    audio_context_length=22)
locked_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 39},
        {"id": "two", "prompt": "@actor continues.", "length": 39},
    ]}),
    "locked-dependency-test", 64, 64, 5, "video", "head", "disabled",
    "generated_audio", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "guide", locked_policy)
locked_prepared = chain._plan_with_source_audio(locked_plan, audio_a)
locked_source_dependency = chain._canonical_source_reference_dependency(
    locked_prepared, 1, None, audio_a)
assert locked_source_dependency is not None
locked_dependency = chain._scene_dependency_record(
    locked_prepared, 1, locked_source_dependency)
assert locked_dependency["scopes"]["global_generation"][
    "source_audio_target"] == "locked"
assert locked_dependency["scopes"]["scene_generation"][
    "source_reference_window"]["pcm_sha256"]

# Final mux choice and whole-source identity are assembly-only.
assembly_changed = json.loads(json.dumps(scene1_a))
assembly_changed["scopes"]["assembly_only"]["final_audio"] = "generated"
assembly_changed["scopes"]["assembly_only"]["source_audio_fingerprint"] = "x"
assert chain._scene_dependency_diffs(scene1_a, assembly_changed) == []

# A later incoming context does not retroactively redefine scene 1.
long_context = make_plan(22)
prepared_long = chain._plan_with_source_audio(long_context, audio_a)
long_scene1 = chain._scene_dependency_record(
    prepared_long, 1, chain._canonical_source_reference_dependency(
        prepared_long, 1, None, audio_a))
assert chain._scene_dependency_diffs(scene1_a, long_scene1) == []
long_scene2 = chain._scene_dependency_record(
    prepared_long, 2, chain._canonical_source_reference_dependency(
        prepared_long, 2, None, audio_a))
boundary_diffs = chain._scene_dependency_diffs(scene2_a, long_scene2)
assert any(item["scope"] == "incoming_boundary"
           and item["field"] == "context_length"
           for item in boundary_diffs)

formatted = chain._format_dependency_mismatches(boundary_diffs)
assert "scene 2 incoming_boundary.context_length" in formatted
assert chain._scene_dependency_diffs({"version": "legacy"}, scene1_a) == []
assert set(scene1_a["scopes"]) == set(chain.DEPENDENCY_SCOPES)
assert scene1_a["version"] == chain.SCENE_DEPENDENCY_VERSION

masked_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "masked-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "audio_feathered_av")
masked_dependency = chain._scene_dependency_record(masked_plan, 2, None)
assert masked_dependency["scopes"]["incoming_boundary"][
    "masked_audio_contract"] == "raw_source_window_v2"
legacy_masked_dependency = json.loads(json.dumps(masked_dependency))
del legacy_masked_dependency["scopes"]["incoming_boundary"][
    "masked_audio_contract"]
contract_diffs = chain._scene_dependency_diffs(
    legacy_masked_dependency, masked_dependency)
assert contract_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "masked_audio_contract",
    "saved": None,
    "current": "raw_source_window_v2",
    "regeneration_required": True,
}]

detail_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "detail-av-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "tapered_av")
detail_dependency = chain._scene_dependency_record(detail_plan, 2, None)
assert detail_dependency["scopes"]["incoming_boundary"][
    "detail_av_recipe"] == chain.DETAIL_AV_RECIPE
changed_detail_dependency = json.loads(json.dumps(detail_dependency))
changed_detail_dependency["scopes"]["incoming_boundary"][
    "detail_av_recipe"]["alpha"] = 0.40
detail_diffs = chain._scene_dependency_diffs(
    changed_detail_dependency, detail_dependency)
assert detail_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "detail_av_recipe.alpha",
    "saved": 0.4,
    "current": 0.30,
    "regeneration_required": True,
}]

drift_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "@actor opens.", "length": 90},
        {"id": "two", "prompt": "@actor continues.", "length": 90},
    ]}),
    "drift-av-dependency-test", 64, 64, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 20, 11, 18, "body:auto:v1", 0,
    "drift_control_av")
drift_dependency = chain._scene_dependency_record(drift_plan, 2, None)
assert drift_dependency["scopes"]["incoming_boundary"][
    "drift_control_av_recipe"] == chain.DRIFT_CONTROL_AV_RECIPE
changed_drift_dependency = json.loads(json.dumps(drift_dependency))
changed_drift_dependency["scopes"]["incoming_boundary"][
    "drift_control_av_recipe"]["taper_steps"] = 3
drift_diffs = chain._scene_dependency_diffs(
    changed_drift_dependency, drift_dependency)
assert drift_diffs == [{
    "scope": "incoming_boundary",
    "scene": 2,
    "field": "drift_control_av_recipe.taper_steps",
    "saved": 3,
    "current": 4,
    "regeneration_required": True,
}]

# Spatial reset is scheduled on the incoming scene, not inherited globally.
proxy_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "one", "length": 90},
        {"id": "two", "prompt": "two", "length": 90},
        {"id": "three", "prompt": "three", "length": 90},
        {"id": "four", "prompt": "four", "length": 90,
         "context_spatial_proxy": "latent_5_6"},
    ]}),
    "scheduled-proxy-test", 1376, 768, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "masked_av")
assert all("context_spatial_proxy" not in shot
           for shot in proxy_plan["shots"][:3])
assert proxy_plan["shots"][3]["context_spatial_proxy"] == "latent_5_6"
assert chain._context_spatial_proxy_size(1376, 768) == (1152, 640)
scene3_proxy_dependency = chain._scene_dependency_record(proxy_plan, 3, None)
scene4_proxy_dependency = chain._scene_dependency_record(proxy_plan, 4, None)
assert "context_spatial_proxy" not in scene3_proxy_dependency[
    "scopes"]["incoming_boundary"]
assert scene4_proxy_dependency["scopes"]["incoming_boundary"][
    "context_spatial_proxy"] == "latent_5_6"
assert scene4_proxy_dependency["scopes"]["incoming_boundary"][
    "context_spatial_proxy_recipe"] == chain.CONTEXT_SPATIAL_PROXY_RECIPE

native_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": name, "prompt": name, "length": 90}
        for name in ("one", "two", "three", "four")
    ]}),
    "scheduled-proxy-test", 1376, 768, 39, "video", "head", "disabled",
    "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "masked_av")
assert chain._history_hash(proxy_plan, 3) == chain._history_hash(native_plan, 3)
assert chain._history_hash(proxy_plan, 4) != chain._history_hash(native_plan, 4)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(native_plan, 3, None),
    scene3_proxy_dependency) == []
proxy_diffs = chain._scene_dependency_diffs(
    chain._scene_dependency_record(native_plan, 4, None),
    scene4_proxy_dependency)
assert proxy_diffs
assert all(item["scene"] == 4 and item["scope"] == "incoming_boundary"
           and item["regeneration_required"] for item in proxy_diffs)

guide_proxy_plan = chain._normalize_plan(
    json.dumps({"shots": [
        {"id": "one", "prompt": "one", "length": 39},
        {"id": "two", "prompt": "two", "length": 39,
         "context_spatial_proxy": "rgb_5_6"},
    ]}),
    "rgb-proxy-test", 1376, 768, 5, "video", "head", "disabled",
    "source_track", 5, 1.0, 8, 11, 18, "body:auto:v1", 0,
    "guide")
assert guide_proxy_plan["shots"][1]["context_spatial_proxy"] == "rgb_5_6"

for invalid_proxy, mode, expected in (
        ("rgb_5_6", "masked_av", "low-grid 5/6"),
        ("latent_5_6", "guide", "latent 5/6")):
    try:
        chain._normalize_plan(
            json.dumps({"shots": [
                {"id": "one", "prompt": "one", "length": 90},
                {"id": "two", "prompt": "two", "length": 90,
                 "context_spatial_proxy": invalid_proxy},
            ]}),
            "invalid-proxy", 64, 64, 39, "video", "head", "disabled",
            "source_track", 39, 1.0, 8, 11, 18, "body:auto:v1", 0,
            mode)
    except ValueError as exc:
        assert expected in str(exc)
    else:
        raise AssertionError("incompatible context spatial proxy was accepted")

print("H3 scene dependencies: scene-local PCM, boundary isolation, assembly exclusion, and structured diffs pass")


# Preflight exposes the same field-level mismatch against saved metadata.
with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    chain._output_root = lambda: str(root)
    resume_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "saved prompt", "length": 22},
            {"id": "two", "prompt": "next prompt", "length": 22},
        ]}),
        "dependency-resume", 64, 64, 5, "video", "head", "disabled",
        "generated_audio", 5, 1.0, 8, 9, 18, "body:auto:v1", 0,
        "guide")
    resume_plan = chain._plan_with_source_audio(resume_plan, None)
    saved_dependency = chain._scene_dependency_record(resume_plan, 1, None)
    paths = chain._artifact_paths(resume_plan, 1)
    pathlib.Path(paths["segment"]).parent.mkdir(parents=True)
    pathlib.Path(paths["checkpoint"]).parent.mkdir(parents=True)
    pathlib.Path(paths["segment"]).write_bytes(b"video")
    pathlib.Path(paths["checkpoint"]).write_bytes(b"checkpoint")
    prompt_path = pathlib.Path(paths["segment"]).with_suffix(".prompt.txt")
    prompt_path.write_text("saved prompt", encoding="utf-8")
    history = chain._history_hash(resume_plan, 1)
    segment = {
        "index": 1,
        "segment": chain._relative_output_path(paths["segment"]),
        "checkpoint": chain._relative_output_path(paths["checkpoint"]),
        "prompt_file": chain._relative_output_path(str(prompt_path)),
        "segment_sha256": chain._file_sha256(paths["segment"]),
        "checkpoint_sha256": chain._file_sha256(paths["checkpoint"]),
        "prompt_file_sha256": chain._file_sha256(str(prompt_path)),
        "prompt_hash": resume_plan["shots"][0]["prompt_hash"],
        "history_hash": history,
    }
    pathlib.Path(paths["metadata"]).write_text(json.dumps({
        "history_hash": history,
        "compatibility": resume_plan["compatibility"],
        "scene_dependency": saved_dependency,
        "segment": segment,
    }), encoding="utf-8")
    changed_plan = json.loads(json.dumps(resume_plan))
    changed_plan["shots"][0]["prompt"] = "changed prompt"
    changed_plan["shots"][0]["prompt_hash"] = chain.hashlib.sha256(
        b"changed prompt").hexdigest()
    diagnostic = {"errors": [], "warnings": []}
    resume = chain._preflight_resume(
        changed_plan, 2, True, diagnostic)
    assert resume["eligible"] is False
    mismatch = resume["predecessors"][0]["mismatches"][0]
    assert mismatch == {
        "scope": "scene_generation", "scene": 1,
        "field": "prompt_hash",
        "saved": resume_plan["shots"][0]["prompt_hash"],
        "current": changed_plan["shots"][0]["prompt_hash"],
        "regeneration_required": True,
    }

print("H3 structured resume preflight: field-level saved/current mismatch pass")
