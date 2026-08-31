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
    nodes = harness._load("nodes")
    contracts = harness._load("contracts_v05")
    chain = harness._load("chain_nodes")
    harness._load("masked_context")
    harness._load("exact_final_timeline")
    harness._load("source_av_target")
    simple = harness._load("master_simple_ui")
    video_simple = harness._load("master_video_mode")

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

    # Video refs accept one native VIDEO connection. The slot itself performs
    # 24 fps normalization and pairs embedded audio; there is no prep/audio
    # switch exposed to the master-workflow user.
    video_slot = simple.MiniMaxH3MasterVideoReferenceSlot()
    assert video_slot.check_lazy_status(False, video=None) == []
    assert video_slot.check_lazy_status(True, video=None) == ["video"]
    native_video = object()
    video_frames = torch.zeros((5, 32, 32, 3), dtype=torch.float32)
    embedded_audio = {
        "waveform": torch.ones((1, 2, 7000), dtype=torch.float32),
        "sample_rate": 32000,
    }
    original_resolve = chain._resolve_video_inputs
    original_indices = chain._external_video_frame_indices
    chain._resolve_video_inputs = lambda source_video, *_args: (
        video_frames, embedded_audio, 24.0, "native VIDEO")
    chain._external_video_frame_indices = lambda count, fps: torch.arange(count)
    try:
        refs, _, video_status = video_slot.add(
            True, "video_ref_1", video=native_video, previous=refs)
    finally:
        chain._resolve_video_inputs = original_resolve
        chain._external_video_frame_indices = original_indices
    entries = chain._tagged_reference_entries(refs)
    assert len(entries) == 3
    assert entries[-1]["kind"] == "video"
    assert entries[-1]["tag"] == "video_ref_1"
    assert entries[-1]["timeline_mode"] == "restart_each_scene"
    assert entries[-1].get("audio") is not None
    assert "embedded audio" in video_status

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

    # Source-video behavior is also one visible semantic mode. Audio routing is
    # intentionally absent from this selector and remains owned by Master Audio.
    video_mode = video_simple.MiniMaxH3MasterVideoMode()
    control, status = video_mode.build("H3 GENERATION")
    assert control["mode"] == "generate"
    assert status == "H3 GENERATION"
    control, _ = video_mode.build("CONTINUE SOURCE VIDEO")
    assert control["mode"] == "continue"
    control, _ = video_mode.build("EDIT SOURCE VIDEO")
    assert control["mode"] == "edit"
    assert set(control) == {"version", "mode", "label"}

    existing = video_simple.MiniMaxH3MasterExistingVideoRouter()
    generate_control, _ = video_mode.build("H3 GENERATION")
    assert existing.check_lazy_status(
        {}, generate_control, source_video=None) == []
    context, status = existing.prepare({}, generate_control, source_video=None)
    assert context is None
    assert "inactive" in status

    edit = video_simple.MiniMaxH3MasterSourceVideoTarget()
    latent = {"samples": object()}
    assert edit.check_lazy_status(
        {}, latent, object(), generate_control, source_video=None) == []
    untouched, status = edit.prepare(
        {}, latent, object(), generate_control, source_video=None)
    assert untouched is latent
    assert "inactive" in status

    edit_control, _ = video_mode.build("EDIT SOURCE VIDEO")
    assert edit.check_lazy_status(
        {}, latent, object(), edit_control, source_video=None) == ["source_video"]

    # Exact-final edit target must repeat-pad only the hidden raw H3 tail, never
    # consume source-picture frames belonging to the next delivered scene.
    video_steps = 37
    audio_steps = 207
    raw_frames = nodes._pixel_frames(video_steps)
    assert raw_frames == 124
    target_video = torch.zeros((1, 16, video_steps, 2, 4))
    target_audio = torch.zeros((1, 32, 2, audio_steps))
    target_latent = {
        "samples": harness.NestedTensor((target_video, target_audio)),
    }
    source_frames = torch.arange(
        200, dtype=torch.float32).reshape(200, 1, 1, 1).expand(
            200, 32, 64, 3).clone()
    state = {
        "index": 1,
        "plan": {"shots": [{
            "generation_start_frame": 10,
            "raw_frames": raw_frames,
            "tail_trim_frames": 4,
        }]},
    }

    chain._resolve_video_inputs = lambda source_video, *_args: (
        source_frames, None, 24.0, "test")
    video_simple._canonical_indices = lambda count, fps, device: torch.arange(
        count, device=device)
    video_simple._resize = lambda frames, *_args: frames

    class VideoVAE:
        def __init__(self):
            self.seen = None

        def encode(self, frames):
            self.seen = frames.detach().clone()
            return target_video.clone()

    vae = VideoVAE()
    output, status = video_simple._edit_source_frames(
        state, object(), target_latent, vae)
    out_video, out_audio = output["samples"].unbind()
    assert torch.equal(out_video, target_video)
    assert torch.equal(out_audio, target_audio)
    assert int(vae.seen.shape[0]) == raw_frames
    # 120 delivered/source frames are consumed: 10..129. The four hidden raw
    # tail frames all repeat source frame 129; frame 130 is never borrowed.
    assert torch.all(vae.seen[-5] == 129.0)
    assert torch.all(vae.seen[-4:] == 129.0)
    assert "audio target untouched" in status

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
    assert {
        "MiniMaxH3MasterVideoMode",
        "MiniMaxH3MasterExistingVideoRouter",
        "MiniMaxH3MasterSourceVideoTarget",
    }.issubset(video_simple.NODE_CLASS_MAPPINGS)
    assert "MiniMaxH3MasterExport" in export_simple.NODE_CLASS_MAPPINGS

    print("PASS simplified master UI/reference/audio/video/export contracts")


if __name__ == "__main__":
    main()
