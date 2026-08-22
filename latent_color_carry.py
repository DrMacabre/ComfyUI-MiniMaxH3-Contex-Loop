"""Scene-one color stabilization for disposable H3 continuation latents.

The sampled predecessor checkpoint remains immutable.  For the small video
prefix copied into the next target, this module decodes once, applies a weak
scene-one exposure/saturation correction in RGB, and encodes both the original
and corrected RGB.  Adding only ``E(corrected) - E(original)`` to the sampled
latent cancels the ordinary VAE round-trip bias instead of replacing the
sampled latent with a re-encode.

The delta is spatially low-passed and temporally tapered from zero at the old
edge of the overlap to full strength beside the generated future.  Audio is
never accepted by this module and therefore cannot be altered accidentally.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import torch
import torch.nn.functional as functional

from .contracts_v05 import LATENT_COLOR_CARRY_RECIPE


_STATS_VERSION = "h3_latent_color_stats_v1"


def _validated_stats(value: Any, usage: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != _STATS_VERSION:
        raise ValueError("%s has no compatible scene-color statistics." % usage)
    luma = tuple(float(item) for item in value.get("luma_percentiles", ()))
    saturation = tuple(
        float(item) for item in value.get("saturation_percentiles", ()))
    if len(luma) != 3 or len(saturation) != 3:
        raise ValueError("%s scene-color statistics are malformed." % usage)
    if not all(math.isfinite(item) for item in (*luma, *saturation)):
        raise ValueError("%s scene-color statistics are not finite." % usage)
    return {
        "version": _STATS_VERSION,
        "luma_percentiles": list(luma),
        "saturation_percentiles": list(saturation),
        "sampled_frames": int(value.get("sampled_frames", 0)),
    }


def tensor_scene_color_stats(frames: Any) -> dict[str, Any]:
    """Measure robust center-weighted luma/saturation from an IMAGE tensor."""
    if not torch.is_tensor(frames) or frames.ndim != 4:
        raise ValueError(
            "H3 latent color carry expected IMAGE [frames,H,W,C], got %s." %
            (tuple(getattr(frames, "shape", ())),))
    if int(frames.shape[0]) < 1 or int(frames.shape[-1]) < 3:
        raise ValueError("H3 latent color carry received an empty RGB image.")

    count, height, width = (int(frames.shape[index]) for index in range(3))
    frame_step = max(1, count // 24)
    y0, y1 = int(height * 0.12), max(int(height * 0.92), 1)
    x0, x1 = int(width * 0.20), max(int(width * 0.80), 1)
    sample = frames[::frame_step, y0:y1:4, x0:x1:4, :3]
    if not int(sample.numel()):
        sample = frames[::frame_step, ::4, ::4, :3]
    rgb = torch.clamp(sample.detach().float(), 0.0, 1.0).mul_(255.0)
    luma = (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 +
            rgb[..., 2] * 0.0722)
    maximum = torch.amax(rgb, dim=-1)
    minimum = torch.amin(rgb, dim=-1)
    saturation = torch.where(
        maximum > 0.0,
        (maximum - minimum) / torch.clamp(maximum, min=1.0) * 255.0,
        torch.zeros_like(maximum))
    valid = (luma >= 20.0) & (luma <= 235.0)
    if int(torch.count_nonzero(valid).item()) >= 64:
        luma = luma[valid]
        saturation = saturation[valid]
    luma_quantiles = torch.tensor(
        (0.10, 0.50, 0.90), device=luma.device, dtype=torch.float32)
    saturation_quantiles = torch.tensor(
        (0.25, 0.50, 0.75), device=saturation.device,
        dtype=torch.float32)
    luma_values = torch.quantile(luma.reshape(-1), luma_quantiles)
    saturation_values = torch.quantile(
        saturation.reshape(-1), saturation_quantiles)
    return {
        "version": _STATS_VERSION,
        "luma_percentiles": [
            float(item) for item in luma_values.detach().cpu().tolist()],
        "saturation_percentiles": [
            float(item)
            for item in saturation_values.detach().cpu().tolist()],
        "sampled_frames": len(range(0, count, frame_step)),
    }


def _coherent_delta(values: tuple[float, ...], minimum: float) -> float:
    positive = tuple(item for item in values if item > 0.0)
    negative = tuple(item for item in values if item < 0.0)
    selected = positive if len(positive) >= 2 else (
        negative if len(negative) >= 2 else ())
    if not selected:
        return 0.0
    value = float(statistics.median(selected))
    return value if abs(value) >= float(minimum) else 0.0


def scene_color_transform(
    anchor: Any,
    current: Any,
    recipe: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Return a weak normalized brightness offset and saturation multiplier."""
    settings = dict(LATENT_COLOR_CARRY_RECIPE if recipe is None else recipe)
    target = _validated_stats(anchor, "H3 latent color anchor")
    source = _validated_stats(current, "H3 latent color source")
    target_luma = tuple(float(item) for item in target["luma_percentiles"])
    source_luma = tuple(float(item) for item in source["luma_percentiles"])
    luma_shift = _coherent_delta(tuple(
        target_value - source_value
        for target_value, source_value in zip(target_luma, source_luma)), 1.0)
    strength = float(settings["strength"])
    maximum_luma = float(settings["max_luma_shift_code_values"])
    luma_shift = max(
        -maximum_luma, min(maximum_luma, luma_shift * strength))

    target_saturation = tuple(
        float(item) for item in target["saturation_percentiles"])
    source_saturation = tuple(
        float(item) for item in source["saturation_percentiles"])
    ratios = tuple(
        target_value / max(source_value, 1.0) - 1.0
        for target_value, source_value in zip(
            target_saturation, source_saturation))
    saturation_delta = _coherent_delta(ratios, 0.02) * strength
    maximum_saturation = float(settings["max_saturation_change"])
    saturation_delta = max(
        -maximum_saturation,
        min(maximum_saturation, saturation_delta))
    return luma_shift / 255.0, 1.0 + saturation_delta


def apply_rgb_color_transform(
    frames: torch.Tensor,
    brightness: float,
    saturation: float,
) -> torch.Tensor:
    """Apply a Rec.709 luma-preserving saturation and exposure adjustment."""
    if not torch.is_tensor(frames) or frames.ndim != 4:
        raise ValueError("H3 latent color carry VAE returned invalid IMAGE.")
    result = frames.detach().contiguous().clone()
    rgb = torch.clamp(result[..., :3].float(), 0.0, 1.0)
    luma = (rgb[..., 0:1] * 0.2126 + rgb[..., 1:2] * 0.7152 +
            rgb[..., 2:3] * 0.0722)
    corrected = luma + (rgb - luma) * float(saturation)
    corrected = torch.clamp(corrected + float(brightness), 0.0, 1.0)
    result[..., :3] = corrected.to(
        device=result.device, dtype=result.dtype)
    return result


def temporal_delta_weights(steps: int) -> torch.Tensor:
    """Return a zero-to-one smoothstep taper over latent time."""
    count = int(steps)
    if count < 2:
        raise ValueError(
            "H3 latent color carry requires at least two video steps.")
    position = torch.linspace(0.0, 1.0, count, dtype=torch.float32)
    return position.square().mul_(3.0 - 2.0 * position)


def _spatial_lowpass(delta: torch.Tensor, kernel_size: int) -> torch.Tensor:
    kernel = int(kernel_size)
    if kernel <= 1:
        return delta
    if kernel % 2 != 1:
        raise ValueError(
            "H3 latent color carry spatial kernel must be odd.")
    radius = kernel // 2
    padded = functional.pad(
        delta.float(), (radius, radius, radius, radius, 0, 0),
        mode="replicate")
    return functional.avg_pool3d(
        padded, kernel_size=(1, kernel, kernel), stride=1).to(
            device=delta.device, dtype=delta.dtype)


def apply_delta_vae_color_carry(
    video_prefix: Any,
    vae: Any,
    anchor_stats: Any,
    current_stats: Any,
    recipe: dict[str, Any] | None = None,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Apply a tapered VAE-delta color correction to one video-only prefix."""
    settings = dict(LATENT_COLOR_CARRY_RECIPE if recipe is None else recipe)
    if not torch.is_tensor(video_prefix) or video_prefix.ndim != 5:
        raise ValueError(
            "H3 latent color carry expected [B,C,T,H,W], got %s." %
            (tuple(getattr(video_prefix, "shape", ())),))
    if not video_prefix.is_floating_point() or int(video_prefix.shape[0]) != 1:
        raise ValueError(
            "H3 latent color carry supports one floating-point video batch.")
    steps = int(video_prefix.shape[2])
    expected_steps = int(settings["video_steps"])
    if steps != expected_steps:
        raise ValueError(
            "H3 latent color carry recipe requires %d video steps, got %d." %
            (expected_steps, steps))

    brightness, saturation = scene_color_transform(
        anchor_stats, current_stats, settings)
    summary = {
        "version": str(settings["version"]),
        "applied": False,
        "brightness": float(brightness),
        "saturation": float(saturation),
        "video_steps": steps,
        "audio": "unchanged",
    }
    if abs(brightness) < (0.5 / 255.0) and abs(saturation - 1.0) < 0.005:
        return video_prefix.detach().contiguous().clone(), summary

    decoded = vae.decode(video_prefix)
    if not torch.is_tensor(decoded):
        raise ValueError(
            "H3 latent color carry video VAE returned %r instead of IMAGE." %
            type(decoded))
    if decoded.ndim == 5:
        decoded = decoded.reshape(
            -1, decoded.shape[-3], decoded.shape[-2], decoded.shape[-1])
    if decoded.ndim != 4 or int(decoded.shape[-1]) < 3:
        raise ValueError(
            "H3 latent color carry video VAE returned image shape %s." %
            (tuple(decoded.shape),))
    expected_frames = int(settings["context_frames"])
    if int(decoded.shape[0]) != expected_frames:
        raise ValueError(
            "H3 latent color carry decoded %d frames; recipe requires %d." %
            (int(decoded.shape[0]), expected_frames))

    baseline = vae.encode(decoded)
    corrected_rgb = apply_rgb_color_transform(
        decoded, brightness, saturation)
    corrected = vae.encode(corrected_rgb)
    expected_shape = tuple(video_prefix.shape)
    if (not torch.is_tensor(baseline) or not torch.is_tensor(corrected)
            or tuple(baseline.shape) != expected_shape
            or tuple(corrected.shape) != expected_shape):
        raise ValueError(
            "H3 latent color carry VAE round-trip shapes %s / %s do not "
            "match prefix %s." %
            (tuple(getattr(baseline, "shape", ())),
             tuple(getattr(corrected, "shape", ())), expected_shape))

    device, dtype = video_prefix.device, video_prefix.dtype
    delta = corrected.to(device=device, dtype=dtype) - baseline.to(
        device=device, dtype=dtype)
    delta = _spatial_lowpass(
        delta, int(settings["spatial_lowpass_kernel"]))
    weights = temporal_delta_weights(steps).to(device=device, dtype=dtype)
    corrected_prefix = video_prefix.detach().contiguous().clone()
    corrected_prefix.add_(
        delta * weights.view(1, 1, steps, 1, 1))
    summary["applied"] = True
    summary["delta_rms"] = float(
        delta.detach().float().square().mean().sqrt().cpu().item())
    return corrected_prefix, summary


__all__ = [
    "apply_delta_vae_color_carry",
    "apply_rgb_color_transform",
    "scene_color_transform",
    "temporal_delta_weights",
    "tensor_scene_color_stats",
]
