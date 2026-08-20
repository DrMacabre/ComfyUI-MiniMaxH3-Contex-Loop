#!/usr/bin/env python3
"""Independent 0.5 audio axes preserve exact 0.4 mode behavior."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_audio_policy_unit"

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
    "shots": [{"id": "one", "prompt": "One stable scene.", "length": 22}],
})


def make_plan(audio_mode="generated_audio", policy=None):
    combined = None
    if policy is not None:
        combined = chain._contract_compose_chain_policy(
            policy, chain._contract_transition_policy("guide"),
            audio_context_length=22)
    return chain._normalize_plan(
        PLAN_JSON, "audio-policy-test", 64, 64, 22,
        "video", "head", "disabled", audio_mode, 22,
        1.0, 8, 7, 18, "model-stack", 0, "guide", combined)


legacy_expected = {
    "source_track": ("source", "on", "off"),
    "generated_audio": ("generated", "off", "on"),
    "source_plus_timeline": ("source", "on", "on"),
}
for mode, expected in legacy_expected.items():
    plan = make_plan(mode)
    assert "audio_policy" not in plan["compatibility"]
    assert plan["compatibility"]["audio_mode"] == mode
    resolved = chain._resolved_audio_policy(plan)
    assert (
        resolved["final_audio"], resolved["source_reference"],
        resolved["generated_continuity"]) == expected

default_policy = chain._contract_audio_policy("generated", "off", "on")
default_status = chain._audio_policy_summary({"audio_policy": default_policy})
assert default_policy == {
    "version": chain.AUDIO_POLICY_VERSION,
    "final_audio": "generated",
    "source_reference": "off",
    "generated_continuity": "on",
}
assert "final=generated/ref=off/carry=on" in default_status

custom_policy = chain._contract_audio_policy("source", "off", "on")
custom_status = chain._audio_policy_summary({"audio_policy": custom_policy})
custom = make_plan("generated_audio", custom_policy)
assert custom["compatibility"]["audio_mode"] == "custom"
assert custom["compatibility"]["audio_policy"] == custom_policy
assert chain._audio_policy_final(custom) == "source"
assert not chain._audio_policy_uses_source_reference(custom)
assert chain._audio_policy_uses_generated_continuity(custom)
assert chain._audio_policy_requires_source(custom)
assert "audio=final=source/ref=off/carry=on" in custom["summary"]

silent_policy = chain._contract_audio_policy("none", "off", "on")
silent = make_plan("source_track", silent_policy)
assert silent["compatibility"]["audio_mode"] == "custom"
assert chain._audio_policy_final(silent) == "none"
assert not chain._audio_policy_requires_source(silent)
prepared_silent = chain._plan_with_source_audio(silent, None)
assert prepared_silent["compatibility"]["source_audio_hash"] == "none"

source_audio = {
    "waveform": chain.torch.linspace(-0.5, 0.5, 30000).reshape(1, 1, -1),
    "sample_rate": 24000,
}
try:
    chain._plan_with_source_audio(custom, None)
except ValueError as exc:
    assert "final=source" in str(exc)
    assert "requires source_audio" in str(exc)
else:
    raise AssertionError("source final policy accepted missing source audio")
prepared_custom = chain._plan_with_source_audio(custom, source_audio)
assert prepared_custom["compatibility"]["source_audio_hash"] == (
    chain._audio_fingerprint(source_audio))

reference_policy = chain._contract_audio_policy("none", "on", "off")
reference_plan = make_plan("generated_audio", reference_policy)
prepared_reference = chain._plan_with_source_audio(
    reference_plan, source_audio)
chain.PromptHistoryStore = lambda _root: types.SimpleNamespace(
    mark_executed=lambda *_args, **_kwargs: None)
state = {"plan": prepared_reference, "index": 1}
current = chain.MiniMaxH3ChainCurrent().current(state, source_audio)["result"]
assert current[12] is not None
assert tuple(current[12]["waveform"].shape) == (1, 1, 22000)

silent_state = {"plan": prepared_silent, "index": 1}
silent_current = chain.MiniMaxH3ChainCurrent().current(
    silent_state, None)["result"]
assert silent_current[12] is None

off_reference = chain._append_tagged_reference(
    None, kind="video", tag="motion", value="video",
    content_hash="video-hash", paired_audio_policy="off")
assert off_reference["entries"][0]["paired_audio_policy"] == "off"
assert chain._reference_entry_contract(
    off_reference["entries"][0])["paired_audio_policy"] == "off"
embedded_reference = chain._append_tagged_reference(
    None, kind="video", tag="motion_av", value="video",
    content_hash="video-hash", audio="audio", audio_hash="audio-hash",
    paired_audio_policy="embedded")
assert embedded_reference["entries"][0]["paired_audio_policy"] == "embedded"
try:
    chain._append_tagged_reference(
        None, kind="video", tag="broken", value="video",
        content_hash="video-hash", paired_audio_policy="embedded")
except ValueError as exc:
    assert "requires paired audio" in str(exc)
else:
    raise AssertionError("embedded paired-audio policy accepted no audio")

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()
assert plan_inputs["required"]["audio_mode"][1]["default"] == (
    "generated_audio")
assert "audio_policy" not in plan_inputs["optional"]
assert "MiniMaxH3AudioPolicy" not in chain.CHAIN_NODE_CLASS_MAPPINGS

print(
    "audio policy: exact legacy migration, independent final/reference/carry "
    "axes, source requirements, Current Shot slicing, paired-reference policy, "
    "new defaults, and one-wire-only Plan surface pass")
