#!/usr/bin/env python3
"""Freeze the 0.5 contracts and the public 0.4 compatibility surface."""

import ast
import importlib.util
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = json.loads((
    ROOT / "tests" / "fixtures" / "v0_4_public_contract.json"
).read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location(
    "h3_contracts_v05", ROOT / "contracts_v05.py")
contracts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contracts)


def class_node(module, name):
    return next(item for item in module.body
                if isinstance(item, ast.ClassDef) and item.name == name)


def literal_string_tuple(value):
    assert isinstance(value, (ast.Tuple, ast.List))
    return [ast.literal_eval(item) for item in value.elts]


def return_names(module, name):
    node = class_node(module, name)
    assignment = next(item for item in node.body
                      if isinstance(item, ast.Assign)
                      and any(isinstance(target, ast.Name)
                              and target.id == "RETURN_NAMES"
                              for target in item.targets))
    return literal_string_tuple(assignment.value)


def plan_required_input_order(module):
    node = class_node(module, "MiniMaxH3ChainPlan")
    method = next(item for item in node.body
                  if isinstance(item, ast.FunctionDef)
                  and item.name == "INPUT_TYPES")
    returned = next(item.value for item in ast.walk(method)
                    if isinstance(item, ast.Return))
    assert isinstance(returned, ast.Dict)
    outer = {ast.literal_eval(key): value
             for key, value in zip(returned.keys, returned.values)}
    required = outer["required"]
    assert isinstance(required, ast.Dict)
    return [ast.literal_eval(key) for key in required.keys]


def method_input_order(module, class_name, group):
    node = class_node(module, class_name)
    method = next(item for item in node.body
                  if isinstance(item, ast.FunctionDef)
                  and item.name == "INPUT_TYPES")
    returned = next(item.value for item in ast.walk(method)
                    if isinstance(item, ast.Return))
    assert isinstance(returned, ast.Dict)
    outer = {ast.literal_eval(key): value
             for key, value in zip(returned.keys, returned.values)}
    values = outer[group]
    assert isinstance(values, ast.Dict)
    return [ast.literal_eval(key) for key in values.keys]


def main():
    assert FIXTURE["format"] == "h3_v0_4_public_contract_fixture_v1"
    assert contracts.SOURCE_TIMELINE_VERSION == "h3_source_timeline_v1"
    assert contracts.AUDIO_POLICY_VERSION == "h3_audio_policy_v1"
    assert contracts.TRANSITION_POLICY_VERSION == "h3_transition_policy_v1"
    assert contracts.SCENE_DEPENDENCY_VERSION == "h3_scene_dependency_v1"
    assert contracts.PREFLIGHT_VERSION == "h3_preflight_v1"
    assert contracts.CONTEXT_SPATIAL_PROXY_MODES == (
        "off", "rgb_5_6", "latent_5_6")
    assert contracts.CONTEXT_SPATIAL_PROXY_RECIPE[
        "version"] == "h3_context_spatial_proxy_v1"
    dependency_shape = contracts.scene_dependency_shape()
    assert dependency_shape["version"] == contracts.SCENE_DEPENDENCY_VERSION
    assert tuple(dependency_shape["scopes"]) == contracts.DEPENDENCY_SCOPES

    for legacy, expected in FIXTURE["legacy_audio_modes"].items():
        migrated = contracts.migrate_legacy_audio_mode(legacy)
        assert migrated.pop("version") == contracts.AUDIO_POLICY_VERSION
        assert migrated == expected
    try:
        contracts.migrate_legacy_audio_mode("ambiguous")
    except ValueError as exc:
        assert "Unknown legacy H3 audio mode" in str(exc)
    else:
        raise AssertionError("unknown legacy audio mode was accepted")

    for final_audio in contracts.FINAL_AUDIO_POLICIES:
        for source_reference in contracts.SOURCE_REFERENCE_POLICIES:
            for continuity in contracts.GENERATED_CONTINUITY_POLICIES:
                policy = contracts.audio_policy(
                    final_audio, source_reference, continuity)
                assert policy == {
                    "version": contracts.AUDIO_POLICY_VERSION,
                    "final_audio": final_audio,
                    "source_reference": source_reference,
                    "generated_continuity": continuity,
                }
    assert contracts.paired_audio_policy(True) == "embedded"
    assert contracts.paired_audio_policy(False) == "off"
    assert contracts.paired_audio_policy("embedded") == "embedded"
    try:
        contracts.audio_policy("copied", "off", "on")
    except ValueError as exc:
        assert "final-audio" in str(exc)
    else:
        raise AssertionError("unknown final-audio policy was accepted")
    try:
        contracts.paired_audio_policy("timeline")
    except ValueError as exc:
        assert "paired-audio" in str(exc)
    else:
        raise AssertionError("unknown paired-audio policy was accepted")

    expected_presets = {
        "cut": ("guide", 0),
        "guide": ("guide", 22),
        "tone_guide": ("tone_carry_guide", 22),
        "latent_guide": ("latent_guide", 22),
        "detail_guide": ("tapered_guide", 22),
        "detail_av": ("tapered_av", 39),
        "hard_av": ("masked_av", 39),
        "soft_av": ("audio_feathered_av", 39),
        "audio_feather_av": ("audio_feathered_av", 39),
    }
    for name, (mode, context) in expected_presets.items():
        resolved = contracts.transition_preset(name)
        assert resolved["preset"] == name
        assert resolved["continuation_mode"] == mode
        assert resolved["context_length"] == context
        resolved["context_length"] = 999
        assert contracts.transition_preset(name)["context_length"] == context
        policy = contracts.transition_policy(name)
        assert policy["continuation_mode"] == mode
        assert policy["context_length"] == context
        assert policy["expert_override"] is False
    expert = contracts.transition_policy(
        "guide", expert_override=True,
        continuation_mode="feathered_av", context_length=39)
    assert expert["preset"] == "guide"
    assert expert["continuation_mode"] == "feathered_av"
    assert expert["context_length"] == 39
    assert expert["expert_override"] is True
    migrated_expert = contracts.transition_policy(
        "soft_av", expert_override=True,
        continuation_mode="feathered_av_rgb", context_length=39)
    assert migrated_expert["continuation_mode"] == "feathered_av"
    assert migrated_expert["context_length"] == 39
    try:
        contracts.transition_policy(
            "guide", expert_override=True,
            continuation_mode="masked_av", context_length=1)
    except ValueError as exc:
        assert "exact shared" in str(exc)
    else:
        raise AssertionError("one-frame AV transition was accepted")
    try:
        contracts.transition_policy(
            "guide", expert_override=True,
            continuation_mode="audio_feathered_av", context_length=1)
    except ValueError as exc:
        assert "exact shared" in str(exc)
    else:
        raise AssertionError("one-frame audio-feather AV transition was accepted")
    try:
        contracts.transition_policy(
            "detail_av", expert_override=True,
            continuation_mode="tapered_av", context_length=90)
    except ValueError as exc:
        assert "exactly 39" in str(exc)
    else:
        raise AssertionError("90-frame Detail AV transition was accepted")
    try:
        contracts.transition_policy(
            "guide", expert_override=True,
            continuation_mode="latent_guide", context_length=1)
    except ValueError as exc:
        assert "at least 5" in str(exc)
    else:
        raise AssertionError("one-frame Latent Guide transition was accepted")
    shape = contracts.source_timeline_shape()
    assert shape["version"] == contracts.SOURCE_TIMELINE_VERSION
    assert set(shape) == {
        "version", "video", "audio", "origin", "fingerprints", "recovery"
    }
    assert set(contracts.DEPENDENCY_SCOPES) == {
        "global_generation", "scene_generation", "incoming_boundary",
        "assembly_only",
    }

    source = (ROOT / "chain_nodes.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    assert plan_required_input_order(module) == FIXTURE[
        "plan_required_input_order"]
    loop_optional = method_input_order(
        module, "MiniMaxH3ChainLoopStart", "optional")
    assert loop_optional[:4] == FIXTURE["loop_start_optional_input_order"]
    assert loop_optional[4:] == ["source_timeline"]
    appended_outputs = {
        "MiniMaxH3ChainCurrent": ["video_blend_frames"],
    }
    for node_name, output_names in FIXTURE["positional_outputs"].items():
        observed = return_names(module, node_name)
        assert observed[:len(output_names)] == output_names, node_name
        assert observed[len(output_names):] == appended_outputs.get(
            node_name, []), node_name
    for format_name in FIXTURE["checkpoint_formats"]:
        assert format_name in source, format_name

    print("v0.5 contracts and v0.4 compatibility fixture passed")


if __name__ == "__main__":
    main()
