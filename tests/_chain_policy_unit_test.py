#!/usr/bin/env python3
"""The compact policy is one wire with identical resolved Plan semantics."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_chain_policy_unit"

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


def make_plan(*, audio=None, transition=None, combined=None,
              audio_context_length=22):
    return chain._normalize_plan(
        PLAN_JSON, "compact-policy-test", 64, 64, 22,
        "video", "head", "disabled", "generated_audio",
        audio_context_length,
        3.0, 8, 7, 18, "model-stack", 0, "guide",
        audio, transition, combined)


node = chain.MiniMaxH3ChainPolicy()
required = node.INPUT_TYPES()["required"]
assert tuple(required["incoming_transition"][0]) == (
    "cut", "guide", "hard_av", "soft_av")
assert "audio_context_length" not in required
combined, status = node.build("soft_av", "source", "on", "off")
assert combined["version"] == chain.CHAIN_POLICY_VERSION
assert combined["audio_policy"] == chain._contract_audio_policy(
    "source", "on", "off")
assert combined["transition_policy"] == chain._contract_transition_policy(
    "soft_av")
assert combined["audio_context_length"] == 39
assert "Soft AV" in status
assert "final=source/ref=on/carry=off" in status
assert "source timeline required" in status
assert "audio context automatic (39f)" in status

separate_plan = make_plan(
    audio=combined["audio_policy"],
    transition=combined["transition_policy"], audio_context_length=39)
combined_plan = make_plan(combined=combined)
assert combined_plan["compatibility"] == separate_plan["compatibility"]
assert combined_plan["plan_hash"] == separate_plan["plan_hash"]
assert "chain_policy" not in combined_plan["compatibility"]

try:
    make_plan(
        audio=combined["audio_policy"],
        transition=combined["transition_policy"],
        combined=combined)
except ValueError as exc:
    assert "either chain_policy" in str(exc)
    assert "not both" in str(exc)
else:
    raise AssertionError("Plan accepted compact and separate policies together")

legacy = chain.MiniMaxH3Legacy04PolicyAdapter()
legacy_result = legacy.build(
    "source_plus_timeline", "feathered_av", 39, 33)
assert legacy.RETURN_NAMES[:3] == (
    "audio_policy", "transition_policy", "status")
assert legacy.RETURN_NAMES[3:] == (
    "chain_policy", "audio_context_length")
assert legacy_result[3]["audio_policy"] == legacy_result[0]
assert legacy_result[3]["transition_policy"] == legacy_result[1]
assert legacy_result[3]["audio_context_length"] == 33
assert legacy_result[4] == 33
legacy_plan = make_plan(combined=legacy_result[3])
assert legacy_plan["compatibility"]["audio_context_length"] == 33
assert legacy_plan["compatibility"]["continuation_mode"] == "feathered_av"

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert plan_inputs["optional"]["chain_policy"][0] == chain.CHAIN_POLICY_TYPE
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3ChainPolicy"] is chain.MiniMaxH3ChainPolicy
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3ChainPolicy"] == "MiniMax H3 Chain Policy"

print(
    "compact chain policy: primary semantic choices, one-wire Plan input, "
    "exact separate-policy compatibility hash, conflict rejection, and "
    "expanded legacy/expert adapter pass")
