"""Schedule-matched video-prefix masks for experimental H3 AV continuation.

Hard AV recursively feeds an exactly protected predecessor latent into every
scene.  That is excellent for a single seam, but repeated clean conditioning
can accumulate contrast and texture errors.  Drift-Control AV keeps the saved
predecessor immutable and instead gives the disposable carried video prefix a
small, scheduler-matched amount of the sampler's existing noise at every model
evaluation.

The dynamic mask is installed in two places which must agree:

* ComfyUI's inpaint sampler uses it to mix the current noisy state with the
  clean carried latent before and after the model call.
* An apply-model wrapper gives the same mask to H3 before BaseModel computes
  its per-row timestep conditioning.  Without this second path H3 would still
  label the prefix as clean conditioning while receiving a noisy input.

Audio is deliberately untouched.  Its hard/open behavior remains owned by the
normal Audio Policy and masked-prefix construction.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable

import torch

from .contracts_v05 import DRIFT_CONTROL_AV_RECIPE


_LOG = logging.getLogger("minimax_h3_context_loop.drift_control_av")
_WRAPPER_KEY = "h3_context_loop_drift_control_av"
_MODEL_OPTION_MARKER = "h3_context_loop_drift_control_av_recipe"


def _schedule_values(sigmas: Any) -> tuple[float, ...]:
    """Return finite, non-negative schedule values in descending order."""
    if torch.is_tensor(sigmas):
        values: Iterable[Any] = sigmas.detach().float().reshape(-1).cpu()
    else:
        values = sigmas or ()
    normalized = []
    for value in values:
        number = float(value)
        if math.isfinite(number) and number >= 0.0:
            normalized.append(number)
    # Some custom samplers expose duplicate stage values.  Only the next
    # strictly lower scheduler level is meaningful for the ratio.
    return tuple(sorted(set(normalized), reverse=True))


def next_schedule_sigma(current_sigma: float, sigmas: Any) -> float:
    """Resolve the next strictly lower sigma from a sampler schedule."""
    current = float(current_sigma)
    if not math.isfinite(current) or current <= 0.0:
        return 0.0
    tolerance = max(1e-7, abs(current) * 1e-6)
    for candidate in _schedule_values(sigmas):
        if candidate < current - tolerance:
            return candidate
    return 0.0


def matched_noise_ratio(current_sigma: float, sigmas: Any) -> float:
    """Return ``next_sigma / current_sigma`` clamped to a mask value."""
    current = float(current_sigma)
    if not math.isfinite(current) or current <= 0.0:
        return 0.0
    return max(0.0, min(1.0, next_schedule_sigma(current, sigmas) / current))


def temporal_prefix_weights(
    prefix_steps: int,
    taper_steps: int,
) -> tuple[float, ...]:
    """Keep the older prefix matched-noise and taper its seam end to clean."""
    count = int(prefix_steps)
    taper = int(taper_steps)
    if count < 1:
        raise ValueError("h3_drift_control_av: prefix_steps must be positive.")
    if taper < 1 or taper > count:
        raise ValueError(
            "h3_drift_control_av: taper_steps must be between 1 and "
            "prefix_steps."
        )
    matched = count - taper
    weights = [1.0] * matched
    # Four taper steps become .75, .50, .25, .00.  The last carried latent
    # step therefore remains exact at the generated-future boundary.
    weights.extend(
        float(taper - offset - 1) / float(taper)
        for offset in range(taper)
    )
    return tuple(weights)


def apply_dynamic_prefix_mask(
    packed_mask: torch.Tensor,
    video_shape: tuple[int, ...],
    prefix_steps: int,
    ratio: float,
    taper_steps: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return a packed sampler mask and its one-channel H3 video mask."""
    if not torch.is_tensor(packed_mask) or packed_mask.ndim != 3:
        raise ValueError(
            "h3_drift_control_av: the sampler denoise mask must be packed "
            "as [B,1,N]."
        )
    shape = tuple(int(value) for value in video_shape)
    if len(shape) != 5 or shape[0] != int(packed_mask.shape[0]):
        raise ValueError(
            "h3_drift_control_av: expected an H3 video latent shape "
            "[B,C,T,H,W], got %s." % (shape,)
        )
    steps = int(prefix_steps)
    if steps < 1 or steps > shape[2]:
        raise ValueError(
            "h3_drift_control_av: prefix step count %d is outside the "
            "%d-step target latent." % (steps, shape[2])
        )
    video_elements = math.prod(shape[1:])
    if int(packed_mask.shape[-1]) < video_elements:
        raise ValueError(
            "h3_drift_control_av: packed denoise mask is shorter than its "
            "video stream."
        )

    out = packed_mask.clone()
    video = out[..., :video_elements].reshape(shape)
    weights = torch.tensor(
        temporal_prefix_weights(steps, taper_steps),
        device=video.device,
        dtype=video.dtype,
    ).mul_(float(max(0.0, min(1.0, ratio))))
    video[:, :, :steps] = weights.view(1, 1, steps, 1, 1)
    # H3 consumes a one-channel latent-grid mask.  The final merged mask path
    # ceil-quantizes its token grid; doing the same here keeps the dynamic
    # apply-model wrapper consistent on native and compatibility cores.
    quantization = float(DRIFT_CONTROL_AV_RECIPE["mask_quantization"])
    h3_video_mask = (
        torch.ceil(video[:, :1].float() * quantization) / quantization)
    return out, h3_video_mask


class _DriftControlMaskState:
    """Per-model-call state shared by sampler and apply-model wrappers."""

    def __init__(self, video_shape: tuple[int, ...], prefix_steps: int):
        self.video_shape = tuple(int(value) for value in video_shape)
        self.prefix_steps = int(prefix_steps)
        self.matched_steps = int(DRIFT_CONTROL_AV_RECIPE["matched_steps"])
        self.taper_steps = int(DRIFT_CONTROL_AV_RECIPE["taper_steps"])
        if self.prefix_steps != self.matched_steps + self.taper_steps:
            raise ValueError(
                "h3_drift_control_av: the prefix has %d video steps, but "
                "recipe v1 requires %d matched + %d taper steps." %
                (self.prefix_steps, self.matched_steps, self.taper_steps))
        self.current_video_mask: torch.Tensor | None = None
        self.last_sigma: float | None = None
        self.last_ratio: float | None = None

    def denoise_mask_function(
        self,
        sigma: torch.Tensor,
        denoise_mask: torch.Tensor,
        extra_options: dict[str, Any] | None = None,
    ) -> torch.Tensor:
        current = float(torch.as_tensor(sigma).detach().float().reshape(-1)[0])
        schedule = (extra_options or {}).get("sigmas", ())
        ratio = matched_noise_ratio(current, schedule)
        out, video_mask = apply_dynamic_prefix_mask(
            denoise_mask,
            self.video_shape,
            self.prefix_steps,
            ratio,
            self.taper_steps,
        )
        self.current_video_mask = video_mask
        self.last_sigma = current
        self.last_ratio = ratio
        return out

    def apply_model_wrapper(self, executor, *args, **kwargs):
        # process_conds built H3's mask payload before sampling began.  Replace
        # only its video component before BaseModel.process_timestep consumes
        # it; audio remains the static hard/open mask produced by Audio Policy.
        if self.current_video_mask is not None:
            kwargs["denoise_mask"] = self.current_video_mask
        return executor(*args, **kwargs)


def install_drift_control_av_model(
    model: Any,
    latent: dict[str, Any],
    prefix_steps: int,
):
    """Clone an H3 MODEL and install the coupled dynamic-mask hooks."""
    if model is None:
        raise ValueError(
            "Drift-Control AV requires Chain Context's optional model input. "
            "Connect the H3 MODEL to Chain Context and use its model output "
            "for every sampler stage."
        )
    if not callable(getattr(model, "clone", None)):
        raise ValueError(
            "h3_drift_control_av: the connected model is not a ComfyUI MODEL."
        )
    inner = getattr(model, "model", None)
    model_type = str(getattr(getattr(inner, "model_type", None), "name", ""))
    if model_type != "FLOW_AV" and inner.__class__.__name__ != "MiniMaxH3":
        raise ValueError(
            "h3_drift_control_av: the connected MODEL is not MiniMax H3 AV."
        )

    samples = latent.get("samples") if isinstance(latent, dict) else None
    if hasattr(samples, "unbind"):
        streams = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        streams = list(samples)
    else:
        streams = []
    if not streams or not torch.is_tensor(streams[0]):
        raise ValueError(
            "h3_drift_control_av: Chain Context did not receive an H3 AV "
            "latent."
        )
    video_shape = tuple(int(value) for value in streams[0].shape)

    patched = model.clone()
    options = getattr(patched, "model_options", None)
    if not isinstance(options, dict):
        raise ValueError(
            "h3_drift_control_av: the connected MODEL has no model options."
        )
    existing = options.get("denoise_mask_function")
    if callable(existing):
        raise ValueError(
            "Drift-Control AV cannot safely combine with another dynamic "
            "denoise-mask model patch (for example Differential Diffusion). "
            "Remove that patch from the H3 MODEL path."
        )
    if not callable(getattr(patched, "set_model_denoise_mask_function", None)):
        raise RuntimeError(
            "Drift-Control AV requires a current ComfyUI ModelPatcher with "
            "dynamic denoise-mask support."
        )
    if not callable(getattr(patched, "add_wrapper_with_key", None)):
        raise RuntimeError(
            "Drift-Control AV requires ComfyUI apply-model wrappers."
        )

    from comfy.patcher_extension import WrappersMP

    state = _DriftControlMaskState(video_shape, int(prefix_steps))
    patched.set_model_denoise_mask_function(state.denoise_mask_function)
    patched.add_wrapper_with_key(
        WrappersMP.APPLY_MODEL,
        _WRAPPER_KEY,
        state.apply_model_wrapper,
    )
    patched.model_options[_MODEL_OPTION_MARKER] = dict(
        DRIFT_CONTROL_AV_RECIPE)
    # Keep the state inspectable for focused diagnostics without making it
    # part of serialized Plan/checkpoint data.
    patched.model_options[_WRAPPER_KEY] = state
    _LOG.info(
        "H3 Drift-Control AV: installed schedule-matched video mask for %d "
        "prefix steps (%d matched + %d clean-seam taper); audio unchanged",
        int(prefix_steps),
        int(state.matched_steps),
        int(state.taper_steps),
    )
    return patched
