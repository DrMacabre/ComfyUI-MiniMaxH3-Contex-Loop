"""Unit coverage for the H3 0.6.37 latent-native master export profiles."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "minimax_h3_master_export_test"

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

chain_nodes = types.ModuleType(PACKAGE + ".chain_nodes")
chain_nodes.MANIFEST_TYPE = "H3_CHAIN_MANIFEST"
sys.modules[PACKAGE + ".chain_nodes"] = chain_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".master_video_export_0637",
    ROOT / "master_video_export_0637.py",
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def resolved(codec, depth, quality="lossless", crf=18):
    config = module._normalize_export(codec, str(depth), quality, crf)
    return config, module._codec_layout(config)


def expect_error(codec, depth, quality="lossless"):
    try:
        resolved(codec, depth, quality)
    except ValueError:
        return
    raise AssertionError(
        "expected invalid master export combination %s/%s/%s" %
        (codec, depth, quality))


config, layout = resolved("h264", 8, "crf")
assert layout["encoder"] == "libx264"
assert layout["pix_fmt"] == "yuv420p"
assert layout["extension"] == ".mp4"
assert config["crf"] == 18

_, layout = resolved("h264", 10, "crf")
assert layout["encoder"] == "libx264"
assert layout["pix_fmt"] == "yuv420p10le"
assert layout["input_depth"] == 16

_, layout = resolved("h264", 8, "lossless")
assert layout["encoder"] == "libx264rgb"
assert layout["pix_fmt"] == "rgb24"

_, layout = resolved("h264", 10, "lossless")
assert layout["encoder"] == "libx264"
assert layout["pix_fmt"] == "yuv444p10le"
assert "0" in layout["options"]

_, layout = resolved("h265", 8, "crf")
assert layout["encoder"] == "libx265"
assert layout["pix_fmt"] == "yuv420p"
assert "hvc1" in layout["options"]

_, layout = resolved("h265", 10, "lossless")
assert layout["encoder"] == "libx265"
assert layout["pix_fmt"] == "yuv444p10le"
assert "lossless=1" in layout["options"]

for depth, pix_fmt in ((8, "gbrp"), (10, "gbrp10le"), (16, "gbrp16le")):
    config, layout = resolved("ffv1_lossless", depth, "crf", 40)
    assert config["quality_mode"] == "lossless"
    assert layout["encoder"] == "ffv1"
    assert layout["pix_fmt"] == pix_fmt
    assert layout["extension"] == ".mkv"

config, layout = resolved("uncompressed_rgb", 8, "crf")
assert config["quality_mode"] == "lossless"
assert layout["encoder"] == "rawvideo"
assert layout["pix_fmt"] == "rgb24"
assert layout["extension"] == ".mov"

config, layout = resolved("uncompressed_v210", 10, "crf")
assert config["quality_mode"] == "lossless"
assert layout["encoder"] == "v210"
assert layout["pix_fmt"] == "yuv422p10le"
assert layout["extension"] == ".mov"

for codec in ("h264", "h265"):
    expect_error(codec, 16)
expect_error("uncompressed_rgb", 10)
expect_error("uncompressed_rgb", 16)
expect_error("uncompressed_v210", 8)
expect_error("uncompressed_v210", 16)

print("master video export profile tests: PASS")
