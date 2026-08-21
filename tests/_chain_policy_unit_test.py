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


def make_plan(*, combined=None, audio_context_length=22):
    return chain._normalize_plan(
        PLAN_JSON, "compact-policy-test", 64, 64, 22,
        "video", "head", "disabled", "generated_audio",
        audio_context_length,
        3.0, 8, 7, 18, "model-stack", 0, "guide",
        combined)


node = chain.MiniMaxH3ChainPolicy()
required = node.INPUT_TYPES()["required"]
assert tuple(required["incoming_transition"][0]) == (
    "cut", "guide", "hard_av", "soft_av")
assert "audio_context_length" not in required
assert list(required)[-1] == "lock_source_audio"
assert required["lock_source_audio"][0] == "BOOLEAN"
assert required["lock_source_audio"][1]["default"] is False
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

locked, locked_status = node.build(
    "soft_av", "source", "on", "on", True)
assert locked["audio_policy"] == chain._contract_audio_policy(
    "source", "off", "off", "locked")
assert "final=source/ref=off/carry=off/target=locked" in locked_status
assert "source timeline required" in locked_status

combined_plan = make_plan(combined=combined)
assert "chain_policy" not in combined_plan["compatibility"]

legacy = chain.MiniMaxH3Legacy04PolicyAdapter()
legacy_combined, legacy_status = legacy.build(
    "source_plus_timeline", "feathered_av", 39, 33)
assert legacy.RETURN_NAMES == ("chain_policy", "status")
assert legacy_combined["audio_policy"] == chain.migrate_legacy_audio_mode(
    "source_plus_timeline")
assert legacy_combined["transition_policy"]["continuation_mode"] == (
    "feathered_av")
assert legacy_combined["audio_context_length"] == 33
assert "legacy / expert" in legacy_status
legacy_plan = make_plan(combined=legacy_combined)
assert legacy_plan["compatibility"]["audio_context_length"] == 33
assert legacy_plan["compatibility"]["continuation_mode"] == "feathered_av"

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert plan_inputs["optional"]["chain_policy"][0] == chain.CHAIN_POLICY_TYPE
assert "audio_policy" not in plan_inputs["optional"]
assert "transition_policy" not in plan_inputs["optional"]
assert chain.CHAIN_NODE_CLASS_MAPPINGS[
    "MiniMaxH3ChainPolicy"] is chain.MiniMaxH3ChainPolicy
assert chain.CHAIN_NODE_DISPLAY_NAME_MAPPINGS[
    "MiniMaxH3ChainPolicy"] == "MiniMax H3 Chain Policy"

print(
    "compact chain policy: primary semantic choices, one-wire Plan input, "
    "canonical compatibility records, and one-output 0.4 legacy/expert "
    "adapter pass")
