#!/usr/bin/env python3
"""Frame-exact cumulative video blend and Plan compatibility regression."""

import importlib.util
import pathlib
import shutil
import sys
import tempfile
import types

import av
import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_video_blend_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: folder_paths.output_directory
folder_paths.get_temp_directory = lambda: folder_paths.output_directory
folder_paths.get_input_directory = lambda: folder_paths.output_directory
folder_paths.get_annotated_filepath = lambda value: str(value)
folder_paths.output_directory = str(ROOT)
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


def frames(count, rgb):
    value = torch.zeros((count, 32, 32, 3), dtype=torch.float32)
    value[..., 0] = rgb[0]
    value[..., 1] = rgb[1]
    value[..., 2] = rgb[2]
    return value


def decode(path):
    with av.open(str(path), mode="r") as container:
        return [frame.to_ndarray(format="rgb24")
                for frame in container.decode(container.streams.video[0])]


def normalized(context=90, blend=39, anchor="head"):
    return chain._normalize_plan(
        '{"shots":[{"id":"one","prompt":"one","length":124},'
        '{"id":"two","prompt":"two","length":124}]}',
        "blend_test", 64, 64, context, "video", anchor, "disabled",
        "generated_audio", 22, 5.0, 20, 0, 18,
        generation_fingerprint="test", video_blend_frames=blend)


def main():
    plan = normalized()
    assert plan["compatibility"]["context_length"] == 90
    assert plan["compatibility"]["video_blend_frames"] == 39
    assert plan["shots"][1]["delivered_frames"] == 124
    assert "blend=39" in plan["summary"]
    try:
        normalized(context=22, blend=23)
    except ValueError as exc:
        assert "between 0 and context_length" in str(exc)
    else:
        raise AssertionError("blend larger than context was accepted")
    try:
        normalized(context=22, blend=5, anchor="before")
    except ValueError as exc:
        assert "requires anchor_mode=head" in str(exc)
    else:
        raise AssertionError("before-mode blend was accepted")

    with tempfile.TemporaryDirectory() as temporary:
        folder_paths.output_directory = temporary
        root = pathlib.Path(temporary)
        base = root / "base.mp4"
        extension = root / "extension.mp4"
        # The extension contains two regenerated context frames followed by
        # four genuinely delivered frames.
        chain._write_segment_video(frames(5, (1, 0, 0)), str(base), 24, 0)
        overlap = torch.cat((frames(2, (0, 1, 0)),
                             frames(4, (0, 0, 1))), dim=0)
        chain._write_segment_video(overlap, str(extension), 24, 0)
        records = [
            {"path": str(base), "input_frames": 5,
             "delivered_frames": 5, "blend_frames": 0},
            {"path": str(extension), "input_frames": 6,
             "delivered_frames": 4, "blend_frames": 2},
        ]

        pyav_output = root / "pyav.mp4"
        chain._pyav_blend_video(
            records, str(pyav_output), {"title": "blend test"}, 9, 0)
        pyav_frames = decode(pyav_output)
        assert len(pyav_frames) == 9
        # The two join frames contain both old red and regenerated green.
        assert pyav_frames[3][0, 0, 0] > 20
        assert pyav_frames[3][0, 0, 1] > 20
        assert pyav_frames[4][0, 0, 0] > 20
        assert pyav_frames[4][0, 0, 1] > 20
        assert pyav_frames[-1][0, 0, 2] > 200

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            metadata = root / "metadata.txt"
            chain._write_ffmetadata(str(metadata), {"title": "blend test"})
            ffmpeg_output = root / "ffmpeg.mp4"
            chain._ffmpeg_blend_video(
                ffmpeg, records, str(ffmpeg_output), str(metadata), 9, 0)
            assert len(decode(ffmpeg_output)) == 9
            # A first xfade may advertise 1/0 FPS. The second xfade used to
            # reject that intermediate even though every source was CFR.
            chained_output = root / "ffmpeg_three_segments.mp4"
            chained_records = records + [{**records[1]}]
            chain._ffmpeg_blend_video(
                ffmpeg, chained_records, str(chained_output), str(metadata),
                13, 0)
            assert len(decode(chained_output)) == 13

        checkpoint_one = root / "one.safetensors"
        checkpoint_two = root / "two.safetensors"
        checkpoint_one.write_bytes(b"one")
        checkpoint_two.write_bytes(b"two")

        def segment(index, video, checkpoint, delivered, raw, blend_video=None):
            value = {
                "index": index,
                "id": "clip_%04d" % index,
                "segment": str(video),
                "checkpoint": str(checkpoint),
                "raw_frames": raw,
                "delivered_frames": delivered,
                "segment_sha256": chain._file_sha256(str(video)),
                "checkpoint_sha256": chain._file_sha256(str(checkpoint)),
            }
            if blend_video is not None:
                value.update({
                    "blend_segment": str(blend_video),
                    "blend_segment_sha256": chain._file_sha256(
                        str(blend_video)),
                    "blend_frames": raw - delivered,
                })
            return value

        blended_manifest = {
            "format": "h3_chain_manifest_v2",
            "run_name": "assembled_blend",
            "clip_count": 2,
            "total_delivered_frames": 9,
            "compatibility": {
                "audio_mode": "generated_audio", "segment_crf": 0,
                "video_blend_frames": 2,
            },
            "segments": [
                segment(1, base, checkpoint_one, 5, 5),
                segment(2, extension, checkpoint_two, 4, 6, extension),
            ],
        }
        assembled = chain.MiniMaxH3ChainAssemble().assemble(
            blended_manifest, "none", "final", 128)["result"][0]
        assert len(decode(assembled)) == 9

        delivered_two = root / "delivered_two.mp4"
        chain._write_segment_video(
            frames(4, (0, 0, 1)), str(delivered_two), 24, 0)
        hard_manifest = {
            **blended_manifest,
            "run_name": "assembled_hard",
            "compatibility": {
                **blended_manifest["compatibility"],
                "video_blend_frames": 0,
            },
            "segments": [
                segment(1, base, checkpoint_one, 5, 5),
                segment(2, delivered_two, checkpoint_two, 4, 6),
            ],
        }
        hard = chain.MiniMaxH3ChainAssemble().assemble(
            hard_manifest, "none", "final", 128)["result"][0]
        assert len(decode(hard)) == 9

    print("H3 video blend: extended context validation, chained xfade CFR, "
          "and frame-exact cumulative PyAV/ffmpeg assembly pass")


if __name__ == "__main__":
    main()
