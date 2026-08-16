#!/usr/bin/env python3
"""Semantic incoming-transition presets resolve to generation fields."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_transition_policy_unit"

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
shared_nodes._claim_inline_patch_ownership = lambda: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


PLAN_JSON = json.dumps({
    "shots": [
        {"id": "one", "prompt": "First scene.", "length": 73},
        {"id": "two", "prompt": "Second scene.", "length": 73},
    ],
})


def make_plan(policy=None, *, encode_mode="video", anchor_mode="head",
              context_length=22, continuation_mode="guide"):
    return chain._normalize_plan(
        PLAN_JSON, "transition-policy-test", 64, 64, context_length,
        encode_mode, anchor_mode, "disabled", "generated_audio", 22,
        3.0, 8, 7, 18, "model-stack", 0, continuation_mode,
        None, policy)


node = chain.MiniMaxH3TransitionPolicy()
expected = {
    "cut": ("guide", 0),
    "guide": ("guide", 22),
    "hard_av": ("masked_av", 39),
    "soft_av": ("feathered_av", 39),
}
for preset, (mode, context) in expected.items():
    policy, output_mode, output_context, status = node.build(preset)
    assert policy["preset"] == preset
    assert policy["continuation_mode"] == mode
    assert policy["context_length"] == context
    assert policy["expert_override"] is False
    assert output_mode == mode and output_context == context
    assert "tested preset" in status

legacy = make_plan(None, context_length=39, continuation_mode="masked_av")
assert "transition_policy" not in legacy["compatibility"]
assert legacy["compatibility"]["context_length"] == 39
assert legacy["compatibility"]["continuation_mode"] == "masked_av"
assert chain._transition_policy_summary(legacy) == "hard_av/masked_av/39f"

cut_policy = node.build("cut")[0]
cut = make_plan(cut_policy)
assert cut["compatibility"]["context_length"] == 0
assert cut["compatibility"].get("continuation_mode", "guide") == "guide"
assert cut["compatibility"]["transition_policy"] == cut_policy
assert chain._plan_context_storage_length(cut) == 0
assert cut["shots"][1]["generation_start_frame"] == 73
assert cut["shots"][1]["delivered_frames"] == 73
assert cut["total_delivered_frames"] == 146
assert "context=0/guide" in cut["summary"]
assert "transition=cut/guide/0f" in cut["summary"]

hard_policy = node.build("hard_av")[0]
hard = make_plan(hard_policy, context_length=22, continuation_mode="guide")
assert hard["compatibility"]["context_length"] == 39
assert hard["compatibility"]["continuation_mode"] == "masked_av"
assert hard["shots"][1]["generation_start_frame"] == 34
assert hard["shots"][1]["delivered_frames"] == 34
assert hard["total_delivered_frames"] == 107

expert, expert_mode, expert_context, expert_status = node.build(
    "guide", True, "feathered_av", 56)
assert expert_mode == "feathered_av" and expert_context == 56
assert expert["preset"] == "guide"
assert expert["expert_override"] is True
assert "expert override" in expert_status
expert_plan = make_plan(expert)
assert expert_plan["compatibility"]["context_length"] == 56
assert expert_plan["compatibility"]["continuation_mode"] == "feathered_av"

try:
    node.build("guide", True, "masked_av", 1)
except ValueError as exc:
    assert "at least 5" in str(exc)
else:
    raise AssertionError("one-frame hard AV expert override was accepted")

try:
    make_plan(hard_policy, anchor_mode="before")
except ValueError as exc:
    assert "anchor_mode=head" in str(exc)
else:
    raise AssertionError("hard AV preset accepted before anchoring")

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert plan_inputs["optional"]["transition_policy"][0] == (
    chain.TRANSITION_POLICY_TYPE)
assert node.RETURN_TYPES == (
    chain.TRANSITION_POLICY_TYPE, "STRING", "INT", "STRING")
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3TransitionPolicy"] is chain.MiniMaxH3TransitionPolicy

legacy_adapter = chain.MiniMaxH3Legacy04PolicyAdapter()
legacy_audio, legacy_transition, legacy_status = legacy_adapter.build(
    "source_plus_timeline", "feathered_av", 56)
assert legacy_audio == chain.migrate_legacy_audio_mode("source_plus_timeline")
assert legacy_transition["continuation_mode"] == "feathered_av"
assert legacy_transition["context_length"] == 56
assert legacy_transition["expert_override"] is True
assert "legacy 0.4" in legacy_status
matched_audio, matched_transition, _ = legacy_adapter.build(
    "generated_audio", "masked_av", 39)
assert matched_audio == chain.migrate_legacy_audio_mode("generated_audio")
assert matched_transition["preset"] == "hard_av"
assert matched_transition["expert_override"] is False
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3Legacy04PolicyAdapter"] is (
        chain.MiniMaxH3Legacy04PolicyAdapter)
assert len(legacy_adapter.OUTPUT_TOOLTIPS) == len(legacy_adapter.RETURN_TYPES)
assert all(legacy_adapter.OUTPUT_TOOLTIPS)

print(
    "transition policy: Cut/Guide/Hard AV/Feathered AV presets, expert "
    "overrides, zero-context delivery, AV safety validation, legacy fallback "
    "and adapter, Plan resolution, and typed node registration pass")
