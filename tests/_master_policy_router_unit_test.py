#!/usr/bin/env python3
"""CPU regression for simplified master transition/source-audio routing."""

import os
import sys
import types

import torch

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _masked_prefix_unit_test as harness  # noqa: E402


def main():
    harness._install_comfy_stubs()
    package = types.ModuleType(harness.PACKAGE)
    package.__path__ = [harness.ROOT]
    sys.modules[harness.PACKAGE] = package
    harness._load("patch_layout")
    harness._load("patch_payload")
    harness._load("nodes")
    harness._load("contracts_v05")
    harness._load("chain_nodes")
    harness._load("exact_final_timeline")
    simple = harness._load("master_simple_ui")
    policy = harness._load("master_policy_router")

    transition = policy.MiniMaxH3MasterTransitionMode()
    guide, _ = transition.build("NEW SHOT / GUIDE")
    hard, _ = transition.build("CONTINUE / MASKED AV")
    soft, _ = transition.build("SOFT AV CONTINUE")
    cut, _ = transition.build("CUT / INDEPENDENT")
    assert guide["preset"] == "guide"
    assert hard["preset"] == "hard_av"
    assert soft["preset"] == "soft_av"
    assert cut["preset"] == "cut"

    audio = simple.MiniMaxH3MasterAudioMode()
    generated_policy_unused, generated, _ = audio.build("H3 GENERATED")
    source_policy_unused, source, _ = audio.build("EXTERNAL / SOURCE")
    refs_policy_unused, refs, _ = audio.build(
        "H3 GENERATED + AUDIO REFERENCES")
    mix_policy_unused, mix, _ = audio.build(
        "H3 GENERATED + EXTERNAL MIX")
    assert generated_policy_unused["transition_policy"]["preset"] == "guide"

    router = policy.MiniMaxH3MasterChainPolicyRouter()
    combined, _ = router.build(generated, hard)
    assert combined["transition_policy"]["preset"] == "hard_av"
    assert combined["transition_policy"]["continuation_mode"] == "masked_av"
    assert combined["transition_policy"]["context_length"] == 39
    assert combined["audio_policy"]["final_audio"] == "generated"
    assert combined["audio_policy"]["generated_continuity"] == "on"

    combined, _ = router.build(source, guide)
    assert combined["transition_policy"]["preset"] == "guide"
    assert combined["audio_policy"]["final_audio"] == "source"
    assert combined["audio_policy"]["source_reference"] == "on"
    assert combined["audio_policy"]["generated_continuity"] == "off"

    for control in (refs, mix):
        combined, _ = router.build(control, cut)
        assert combined["transition_policy"]["preset"] == "cut"
        assert combined["audio_policy"]["final_audio"] == "generated"
        assert combined["audio_policy"]["source_reference"] == "off"

    gate = policy.MiniMaxH3MasterSourceAudioGate()
    assert gate.check_lazy_status(generated, source_audio=None) == []
    value, status = gate.route(generated, source_audio=None)
    assert value is None
    assert "inactive" in status
    assert gate.check_lazy_status(source, source_audio=None) == ["source_audio"]
    full_audio = {
        "waveform": torch.ones((1, 2, 32000), dtype=torch.float32),
        "sample_rate": 32000,
    }
    value, status = gate.route(source, source_audio=full_audio)
    assert value is full_audio
    assert "active" in status

    required = {
        "MiniMaxH3MasterTransitionMode",
        "MiniMaxH3MasterChainPolicyRouter",
        "MiniMaxH3MasterSourceAudioGate",
    }
    assert required.issubset(policy.NODE_CLASS_MAPPINGS)
    print("PASS simplified master continuation/source-audio policy routing")


if __name__ == "__main__":
    main()
