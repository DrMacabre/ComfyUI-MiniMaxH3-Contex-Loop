#!/usr/bin/env python3
"""CPU checks for tapered scene-one VAE-delta latent color carry."""

import importlib.util
import os
import sys
import types

import torch
import torch.nn.functional as functional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "h3_latent_color_test_pkg"


def _load(name):
    path = os.path.join(ROOT, "%s.py" % name)
    spec = importlib.util.spec_from_file_location(
        "%s.%s" % (PACKAGE, name), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AffineRoundTripVAE:
    """Tiny temporal resize VAE with a deliberate shared encode bias."""

    def __init__(self):
        self.decode_calls = 0
        self.encode_calls = 0

    def decode(self, latent):
        self.decode_calls += 1
        decoded = functional.interpolate(
            latent[:, :3].float(), size=(39, latent.shape[3], latent.shape[4]),
            mode="trilinear", align_corners=True)
        return decoded[0].permute(1, 2, 3, 0).contiguous()

    def encode(self, images):
        self.encode_calls += 1
        source = images[..., :3].permute(3, 0, 1, 2).unsqueeze(0).float()
        # The fixed +0.25 represents a lossy/biased VAE round trip. It must
        # cancel when corrected and baseline encodes are subtracted.
        return functional.interpolate(
            source, size=(12, images.shape[1], images.shape[2]),
            mode="trilinear", align_corners=True) + 0.25


def main():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [ROOT]
    sys.modules[PACKAGE] = package
    contracts = _load("contracts_v05")
    carry = _load("latent_color_carry")

    weights = carry.temporal_delta_weights(12)
    assert tuple(weights.shape) == (12,)
    assert float(weights[0]) == 0.0
    assert float(weights[-1]) == 1.0
    assert torch.all(weights[1:] >= weights[:-1])

    anchor = {
        "version": "h3_latent_color_stats_v1",
        "luma_percentiles": [100.0, 100.0, 100.0],
        "saturation_percentiles": [80.0, 80.0, 80.0],
        "sampled_frames": 12,
    }
    redder = {
        "version": "h3_latent_color_stats_v1",
        "luma_percentiles": [112.0, 112.0, 112.0],
        "saturation_percentiles": [120.0, 120.0, 120.0],
        "sampled_frames": 12,
    }
    brightness, saturation = carry.scene_color_transform(anchor, redder)
    assert abs(brightness - (-6.0 / 255.0)) < 1e-9
    assert abs(saturation - 0.94) < 1e-9

    # A neutral scene must skip all VAE work.
    prefix = torch.full((1, 3, 12, 4, 5), 0.5, dtype=torch.float32)
    neutral_vae = AffineRoundTripVAE()
    neutral, summary = carry.apply_delta_vae_color_carry(
        prefix, neutral_vae, anchor, anchor)
    assert torch.equal(neutral, prefix)
    assert not summary["applied"]
    assert neutral_vae.decode_calls == 0
    assert neutral_vae.encode_calls == 0

    # Delta-VAE carry changes only the disposable copy. The first temporal
    # step is exact, the last receives the full bounded correction, and the
    # shared +0.25 encoder bias is absent from the result.
    vae = AffineRoundTripVAE()
    corrected, summary = carry.apply_delta_vae_color_carry(
        prefix, vae, anchor, redder)
    assert summary["applied"]
    assert vae.decode_calls == 1
    assert vae.encode_calls == 2
    assert torch.equal(corrected[:, :, 0], prefix[:, :, 0])
    assert torch.all(corrected[:, :, -1] < prefix[:, :, -1])
    assert float(torch.max(torch.abs(corrected - prefix))) < 0.10
    assert torch.equal(prefix, torch.full_like(prefix, 0.5))

    # Tensor stats see increased saturation without relying on PyAV/NumPy.
    gray = torch.full((39, 16, 16, 3), 0.5)
    warm = gray.clone()
    warm[..., 0] = 0.75
    gray_stats = carry.tensor_scene_color_stats(gray)
    warm_stats = carry.tensor_scene_color_stats(warm)
    assert gray_stats["version"] == "h3_latent_color_stats_v1"
    assert warm_stats["saturation_percentiles"][1] > (
        gray_stats["saturation_percentiles"][1])

    assert contracts.LATENT_COLOR_CARRY_RECIPE["audio"] == "unchanged"
    assert contracts.transition_preset("color_drift_av") == {
        "version": contracts.TRANSITION_POLICY_VERSION,
        "preset": "color_drift_av",
        "continuation_mode": "color_stable_drift_av",
        "context_length": 39,
        "label": "Color-Stable Drift AV continuation (experimental)",
    }
    print(
        "latent color carry: delta-VAE bias cancellation, temporal taper, "
        "bounded transform, stats, and preset passed")


if __name__ == "__main__":
    main()
