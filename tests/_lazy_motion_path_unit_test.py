#!/usr/bin/env python3
"""Path-backed motion decoding stays scene-local and Plan-aware."""

import importlib.util
from fractions import Fraction
import pathlib
import sys
import tempfile
import types

import av
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_lazy_motion_path_unit"

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
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def write_fixture(path, frame_count=12, source_fps=24):
    width = height = 64
    sample_rate = 48000
    sample_count = round(frame_count / source_fps * sample_rate)
    container = av.open(str(path), mode="w")
    video = container.add_stream("libx264rgb", rate=source_fps)
    video.width = width
    video.height = height
    video.pix_fmt = "rgb24"
    video.options = {"crf": "0", "preset": "ultrafast"}
    audio = container.add_stream("pcm_f32le", rate=sample_rate)
    audio.layout = "mono"
    try:
        for index in range(frame_count):
            array = np.full(
                (height, width, 3), index * 7, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, source_fps)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)

        waveform = np.linspace(
            -0.75, 0.75, sample_count, dtype=np.float32).reshape(1, -1)
        for start in range(0, sample_count, 2048):
            stop = min(sample_count, start + 2048)
            frame = av.AudioFrame.from_ndarray(
                waveform[:, start:stop], format="fltp", layout="mono")
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for packet in audio.encode(frame):
                container.mux(packet)
        for packet in audio.encode():
            container.mux(packet)
    finally:
        container.close()


with tempfile.TemporaryDirectory() as temporary:
    path = pathlib.Path(temporary) / "motion.mkv"
    write_fixture(path)
    node = chain.MiniMaxH3TaggedMotionReferencePath()
    references, fingerprint, status, preview_source = node.add(
        str(path), "performance", "<Subject 1>",
        "the exact body movement and action timing", "source", True,
        "performance_audio", "sequential")
    assert len(fingerprint) == 64
    assert "lazy motion" in status
    entry = references["entries"][0]
    assert chain._is_lazy_motion_descriptor(entry["value"])
    assert entry["semantic_role"] == "motion"
    assert entry["audio_tag"] == "performance_audio"

    plan = {
        "compatibility": {"continuation_mode": "masked_av"},
        "shots": [
            {"raw_frames": 7, "delivered_frames": 7,
             "generation_start_frame": 0,
             "prompt": "Begin @performance."},
            {"raw_frames": 7, "delivered_frames": 5,
             "generation_start_frame": 5,
             "prompt": "Continue @performance."},
        ],
    }
    video, audio, detail = chain._scheduled_video_reference_slice(
        entry, {"index": 2, "plan": plan}, 2, 2, 7)
    assert tuple(video.shape) == (5, 64, 64, 3)
    assert abs(float(video[0, 0, 0, 0]) - 49 / 255) < 1e-6
    assert abs(float(video[-1, 0, 0, 0]) - 77 / 255) < 1e-6
    assert tuple(audio["waveform"].shape) == (1, 1, 10000)
    assert audio["sample_rate"] == 48000
    assert detail == (
        "@performance sequential delivered frames 7:12 (origin scene 1)")

    preview = chain.MiniMaxH3LazyMotionScenePreview()
    no_video, no_audio, no_plan_status = preview.preview(
        preview_source, 2, None)
    assert no_video is None and no_audio is None
    assert "No Plan" in no_plan_status
    preview_video, preview_audio, preview_status = preview.preview(
        preview_source, 2, plan)
    assert tuple(preview_video.shape) == (5, 64, 64, 3)
    assert tuple(preview_audio["waveform"].shape) == (1, 1, 10000)
    assert "Scene 2/2" in preview_status

    inactive_plan = {
        **plan,
        "shots": [plan["shots"][0], {
            **plan["shots"][1], "prompt": "No reference in this scene.",
        }],
    }
    blocked_video, blocked_audio, inactive_status = preview.preview(
        preview_source, 2, inactive_plan)
    assert blocked_video is None and blocked_audio is None
    assert "does not activate" in inactive_status

    path_25 = pathlib.Path(temporary) / "motion_25fps.mkv"
    write_fixture(path_25, frame_count=30, source_fps=25)
    refs_25, _, status_25, _ = node.add(
        str(path_25), "performance_25", "<Subject 1>",
        "the exact body movement and action timing", "source", True,
        "performance_25_audio", "sequential")
    entry_25 = refs_25["entries"][0]
    descriptor_25 = entry_25["value"]
    assert descriptor_25["source_fps"] == 25
    assert descriptor_25["fps"] == 24
    assert descriptor_25["frame_count"] == 29, descriptor_25
    assert "25 -> 24 fps scene-local" in status_25
    converted = chain._decode_lazy_motion_video(
        descriptor_25, 20, 25)
    assert tuple(converted.shape) == (5, 64, 64, 3)
    expected_source_indices = [20, 21, 22, 23, 25]
    for target_index, source_index in enumerate(expected_source_indices):
        expected = source_index * 7 / 255
        assert abs(float(converted[target_index, 0, 0, 0]) - expected) < 1e-6
    converted_audio = chain._decode_lazy_motion_audio(
        descriptor_25, 20, 25)
    assert tuple(converted_audio["waveform"].shape) == (1, 1, 10000)
    tail_video = chain._decode_lazy_motion_video(descriptor_25, 24, 29)
    tail_audio = chain._decode_lazy_motion_audio(descriptor_25, 24, 29)
    assert tuple(tail_video.shape) == (5, 64, 64, 3)
    assert tuple(tail_audio["waveform"].shape) == (1, 1, 10000)
    assert np.allclose(
        tail_audio["waveform"].numpy()[..., -400:], 0.0)

print(
    "lazy motion path: file fingerprinting, scene-only CFR-to-24 AV decode, "
    "delivered masked timing, no-Plan blocking, and scene counter preview pass")
