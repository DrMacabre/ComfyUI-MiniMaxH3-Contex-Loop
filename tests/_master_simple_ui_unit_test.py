#!/usr/bin/env python3
"""CPU/static regression for the simplified master workflow facades."""

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
    contracts = harness._load("contracts_v05")
    chain = harness._load("chain_nodes")
    harness._load("exact_final_timeline")
    simple = harness._load("master_simple_ui")

    # OFF is a true lazy absence: it preserves the chain and requests no media.
    picture = simple.MiniMaxH3MasterPictureReferenceSlot()
    assert picture.check_lazy_status(False, image=None) == []
    empty, token, status = picture.add(False, "unused", image=None)
    assert chain._tagged_reference_entries(empty) == []
    assert token == chain._reference_fingerprint_output(empty)
    assert "OFF" in status

    # ON requests only the actual media and delegates to the canonical tagged
    # registry implementation rather than introducing another reference format.
    assert picture.check_lazy_status(True, image=None) == ["image"]
    image = torch.zeros((1, 32, 32, 3), dtype=torch.float32)
    refs, _, _ = picture.add(True, "image_ref_1", image=image)
    entries = chain._tagged_reference_entries(refs)
    assert len(entries) == 1
    assert entries[0]["kind"] == "picture"
    assert entries[0]["tag"] == "image_ref_1"

    audio_slot = simple.MiniMaxH3MasterAudioReferenceSlot()
    assert audio_slot.check_lazy_status(False, audio=None) == []
    assert audio_slot.check_lazy_status(True, audio=None) == ["audio"]
    audio = {
        "waveform": torch.zeros((1, 2, 32000), dtype=torch.float32),
        "sample_rate": 32000,
    }
    refs, _, _ = audio_slot.add(
        True, "audio_ref_1", audio=audio, previous=refs)
    entries = chain._tagged_reference_entries(refs)
    assert len(entries) == 2
    assert entries[-1]["kind"] == "audio"
    assert entries[-1]["tag"] == "audio_ref_1"
    assert entries[-1]["timeline_mode"] == "standalone"
    assert not entries[-1].get("align_audio_reference", False)

    video_slot = simple.MiniMaxH3MasterVideoReferenceSlot()
    assert video_slot.check_lazy_status(False, video=None, audio=None) == []
    assert video_slot.check_lazy_status(True, video=None) == ["video"]
    video = torch.zeros((5, 32, 32, 3), dtype=torch.float32)
    refs, _, _ = video_slot.add(
        True, "video_ref_1", video=video, previous=refs)
    entries = chain._tagged_reference_entries(refs)
    assert len(entries) == 3
    assert entries[-1]["kind"] == "video"
    assert entries[-1]["tag"] == "video_ref_1"
    assert entries[-1]["timeline_mode"] == "restart_each_scene"

    # One visible audio mode replaces the four low-level Chain Policy axes.
    mode = simple.MiniMaxH3MasterAudioMode()
    policy, control, _ = mode.build("H3 GENERATED")
    assert policy["version"] == contracts.CHAIN_POLICY_VERSION
    assert policy["audio_policy"]["final_audio"] == "generated"
    assert policy["audio_policy"]["source_reference"] == "off"
    assert policy["audio_policy"]["generated_continuity"] == "on"
    assert control["mode"] == "generated"

    policy, control, _ = mode.build("EXTERNAL / SOURCE")
    assert policy["audio_policy"]["final_audio"] == "source"
    assert policy["audio_policy"]["source_reference"] == "on"
    assert policy["audio_policy"]["generated_continuity"] == "off"
    assert control["mode"] == "source"

    policy, control, _ = mode.build("H3 GENERATED + AUDIO REFERENCES")
    assert policy["audio_policy"]["final_audio"] == "generated"
    assert policy["audio_policy"]["source_reference"] == "off"
    assert control["mode"] == "generated_with_references"

    policy, control, _ = mode.build(
        "H3 GENERATED + EXTERNAL MIX", generated_level=0.5,
        external_level=0.25)
    assert policy["audio_policy"]["final_audio"] == "generated"
    assert control["mode"] == "generated_external_mix"
    assert control["generated_level"] == 0.5
    assert control["external_level"] == 0.25

    # Real DSP mixing is deterministic, stereo-normalized and peak-safe.
    generated = {
        "waveform": torch.ones((1, 2, 16), dtype=torch.float32),
        "sample_rate": 32000,
    }
    external = {
        "waveform": torch.ones((1, 1, 16), dtype=torch.float32),
        "sample_rate": 32000,
    }
    mixed, peak, attenuation = simple._mix_audio(
        generated, external, 0.5, 0.25)
    assert tuple(mixed["waveform"].shape) == (1, 2, 16)
    assert torch.allclose(
        mixed["waveform"], torch.full((1, 2, 16), 0.75))
    assert peak == 0.75
    assert attenuation == 1.0

    hot, peak, attenuation = simple._mix_audio(
        generated, external, 1.0, 1.0)
    assert peak == 2.0
    assert attenuation == 0.5
    assert torch.all(hot["waveform"].abs() <= 1.0)

    # Load the simple export facade against a fake advanced exporter so this
    # regression freezes the profile recipes without invoking ffmpeg.
    fake_export = types.ModuleType(harness.PACKAGE + ".master_video_export_0637")
    captured = {}

    class FakeAdvancedExport:
        def export(self, **kwargs):
            captured.clear()
            captured.update(kwargs)
            return object(), "/tmp/master.fake", "advanced-ok"

    fake_export.MiniMaxH3ChainMasterVideoExport = FakeAdvancedExport
    sys.modules[fake_export.__name__] = fake_export
    export_simple = harness._load("master_export_simple")
    exporter = export_simple.MiniMaxH3MasterExport()

    manifest = {
        "format": "h3_chain_manifest_v3",
        "plan": {"compatibility": {"audio_policy": {
            "version": contracts.AUDIO_POLICY_VERSION,
            "final_audio": "generated",
            "source_reference": "off",
            "generated_continuity": "on",
        }}},
    }
    # Avoid depending on the full manifest helper for this delegation test.
    chain._audio_policy_final = lambda _manifest: "generated"
    _, path, status = exporter.export(
        manifest, object(), profile="DELIVERY / MOBILE", filename="demo")
    assert path == "/tmp/master.fake"
    assert "DELIVERY / MOBILE" in status
    assert captured["video_codec"] == "h264"
    assert captured["bit_depth"] == "8"
    assert captured["quality_mode"] == "crf"
    assert captured["crf"] == 20
    assert captured["audio_source"] == "plan"
    assert captured["blend_schedule"] == "plan"
    assert captured["decode_buffer"] == "disk-backed"
    assert captured["reuse_cache"] is True

    exporter.export(
        manifest, object(), profile="HIGH QUALITY", filename="demo")
    assert captured["video_codec"] == "h265"
    assert captured["bit_depth"] == "10"
    assert captured["crf"] == 16

    exporter.export(
        manifest, object(), profile="LOSSLESS ARCHIVE", filename="demo")
    assert captured["video_codec"] == "ffv1_lossless"
    assert captured["bit_depth"] == "16"
    assert captured["quality_mode"] == "lossless"

    exporter.export(
        manifest, object(), profile="EDITING MASTER", filename="demo")
    assert captured["video_codec"] == "uncompressed_v210"
    assert captured["bit_depth"] == "10"
    assert captured["quality_mode"] == "lossless"

    required = {
        "MiniMaxH3MasterPictureReferenceSlot",
        "MiniMaxH3MasterVideoReferenceSlot",
        "MiniMaxH3MasterAudioReferenceSlot",
        "MiniMaxH3MasterAudioMode",
        "MiniMaxH3MasterAudioRouter",
    }
    assert required.issubset(simple.NODE_CLASS_MAPPINGS)
    assert "MiniMaxH3MasterExport" in export_simple.NODE_CLASS_MAPPINGS

    print("PASS simplified master UI/reference/audio/export contracts")


if __name__ == "__main__":
    main()
