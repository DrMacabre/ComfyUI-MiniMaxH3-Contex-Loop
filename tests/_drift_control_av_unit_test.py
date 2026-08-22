#!/usr/bin/env python3
"""Focused CPU tests for schedule-matched Drift-Control AV masks."""

import copy
import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_NAME = "h3_drift_control_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package


def load_module(name):
    qualified = PACKAGE_NAME + "." + name
    spec = importlib.util.spec_from_file_location(
        qualified, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


contracts = load_module("contracts_v05")
drift = load_module("drift_control")


schedule = torch.tensor([1.0, 0.8, 0.5, 0.2, 0.0])
assert abs(drift.next_schedule_sigma(0.8, schedule) - 0.5) < 1e-7
assert abs(drift.next_schedule_sigma(0.65, schedule) - 0.5) < 1e-7
assert abs(drift.next_schedule_sigma(1.1, schedule) - 1.0) < 1e-7
assert drift.next_schedule_sigma(0.0, schedule) == 0.0
assert abs(drift.matched_noise_ratio(0.8, schedule) - 0.625) < 1e-7
assert drift.matched_noise_ratio(0.2, schedule) == 0.0

weights = drift.temporal_prefix_weights(12, 4)
assert weights == (1.0,) * 8 + (0.75, 0.5, 0.25, 0.0)

video_shape = (1, 2, 15, 2, 2)
video_elements = 2 * 15 * 2 * 2
audio_elements = 24
base = torch.ones((1, 1, video_elements + audio_elements))
dynamic, h3_mask = drift.apply_dynamic_prefix_mask(
    base, video_shape, 12, 0.5, 4)
video = dynamic[..., :video_elements].reshape(video_shape)
for index, expected in enumerate(
        (0.5,) * 8 + (0.375, 0.25, 0.125, 0.0)):
    assert torch.allclose(
        video[:, :, index], torch.full_like(video[:, :, index], expected))
assert torch.equal(video[:, :, 12:], torch.ones_like(video[:, :, 12:]))
assert torch.equal(dynamic[..., video_elements:], base[..., video_elements:])
assert tuple(h3_mask.shape) == (1, 1, 15, 2, 2)

# The sampler uses the exact continuous ratio while H3 receives the final
# merged PR's ceil-quantized 1/256 token-grid convention.
third, quantized = drift.apply_dynamic_prefix_mask(
    base, video_shape, 12, 1.0 / 3.0, 4)
assert abs(float(third[..., 0]) - (1.0 / 3.0)) < 1e-7
assert abs(float(quantized[..., 0, 0, 0]) - (86.0 / 256.0)) < 1e-7

state = drift._DriftControlMaskState(video_shape, 12)
updated = state.denoise_mask_function(
    torch.tensor([0.8]), base, {"sigmas": schedule})
assert abs(state.last_ratio - 0.625) < 1e-7
assert state.current_video_mask is not None
assert abs(float(updated[..., 0]) - 0.625) < 1e-7
captured = {}


def executor(*args, **kwargs):
    captured.update(kwargs)
    return "ok"


assert state.apply_model_wrapper(
    executor, "x", denoise_mask=torch.ones((1, 1, 15, 2, 2))) == "ok"
assert captured["denoise_mask"] is state.current_video_mask

# A sigma-split sampler exposes only its local schedule.  Supplying the full
# unsplit schedule keeps the boundary's next-sigma ratio identical across
# switched model branches instead of incorrectly treating the split as zero.
split_local = torch.tensor([1.0, 0.8])
split_without_override = drift._DriftControlMaskState(video_shape, 12)
split_without_override.denoise_mask_function(
    torch.tensor([0.8]), base, {"sigmas": split_local})
assert split_without_override.last_ratio == 0.0
split_with_override = drift._DriftControlMaskState(
    video_shape, 12, schedule_override=schedule)
split_updated = split_with_override.denoise_mask_function(
    torch.tensor([0.8]), base, {"sigmas": split_local})
assert abs(split_with_override.last_ratio - 0.625) < 1e-7
assert abs(float(split_updated[..., 0]) - 0.625) < 1e-7

try:
    drift._DriftControlMaskState(video_shape, 11)
except ValueError as exc:
    assert "requires 8 matched + 4 taper" in str(exc)
else:
    raise AssertionError("Drift-Control AV accepted a non-v1 prefix layout")


class ModelType:
    name = "FLOW_AV"


class InnerModel:
    model_type = ModelType()


class FakeModel:
    def __init__(self):
        self.model = InnerModel()
        self.model_options = {}
        self.mask_function = None
        self.wrappers = []

    def clone(self):
        cloned = FakeModel()
        cloned.model_options = copy.copy(self.model_options)
        return cloned

    def set_model_denoise_mask_function(self, function):
        self.mask_function = function
        self.model_options["denoise_mask_function"] = function

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers.append((wrapper_type, key, wrapper))


comfy = types.ModuleType("comfy")
patcher_extension = types.ModuleType("comfy.patcher_extension")


class WrappersMP:
    APPLY_MODEL = "apply_model"
    DIFFUSION_MODEL = "diffusion_model"
    SAMPLER_SAMPLE = "sampler_sample"


patcher_extension.WrappersMP = WrappersMP
comfy.patcher_extension = patcher_extension
sys.modules["comfy"] = comfy
sys.modules["comfy.patcher_extension"] = patcher_extension

latent = {"samples": [
    torch.zeros(video_shape),
    torch.zeros((1, 3, 2, 24)),
]}
source_model = FakeModel()
patched = drift.install_drift_control_av_model(source_model, latent, 12)
assert patched is not source_model
assert source_model.model_options == {}
assert callable(patched.model_options["denoise_mask_function"])
assert patched.model_options[
    "h3_context_loop_drift_control_av_recipe"] == (
        contracts.DRIFT_CONTROL_AV_RECIPE)
assert len(patched.wrappers) == 2
assert patched.wrappers[0][0:2] == (
    "apply_model", "h3_context_loop_drift_control_av")
assert patched.wrappers[1][0:2] == (
    "sampler_sample", "h3_context_loop_drift_control_split_handoff")


class FlowSampling:
    noise_scale = 1.0


class InnerSamplerModel:
    model_sampling = FlowSampling()

    @staticmethod
    def process_latent_in(value):
        return value


class FakeGuider:
    inner_model = InnerSamplerModel()


handoff_reference = torch.tensor([[[1.0, 2.0, 3.0, 4.0]]])
stage_a = torch.tensor([[[3.0, 5.0, 7.0, 9.0]]])
zero_noise = torch.zeros_like(stage_a)
handoff_state = drift._DriftControlMaskState(
    video_shape,
    12,
    schedule_override=torch.tensor([1.0, 0.8, 0.5, 0.2, 0.0]),
    reference_samples=handoff_reference,
)
handoff_capture = {}


def handoff_executor(
    guider, sigmas, extra_args, callback, noise, latent_image,
    denoise_mask, disable_pbar,
):
    handoff_capture["noise"] = noise
    handoff_capture["latent_image"] = latent_image
    sigma = float(sigmas[0])
    handoff_capture["start"] = (
        sigma * noise + (1.0 - sigma) * latent_image)
    return "split-ok"


assert handoff_state.sampler_sample_wrapper(
    handoff_executor,
    FakeGuider(),
    torch.tensor([0.5, 0.2, 0.0]),
    {},
    None,
    zero_noise,
    stage_a,
    torch.ones_like(stage_a),
    True,
) == "split-ok"
assert torch.equal(handoff_capture["latent_image"], handoff_reference)
# Stock DisableNoise + stage_a would start at (1-sigma)*stage_a.  The corrected
# call reconstructs that exact state while restoring the original reference.
assert torch.allclose(handoff_capture["start"], 0.5 * stage_a)

stage_one_capture = {}


def stage_one_executor(*args):
    stage_one_capture["noise"] = args[4]
    stage_one_capture["latent_image"] = args[5]
    return "stage-one-ok"


assert handoff_state.sampler_sample_wrapper(
    stage_one_executor,
    FakeGuider(),
    torch.tensor([1.0, 0.8, 0.5]),
    {},
    None,
    zero_noise,
    stage_a,
    torch.ones_like(stage_a),
    True,
) == "stage-one-ok"
assert stage_one_capture["noise"] is zero_noise
assert stage_one_capture["latent_image"] is stage_a

marked = drift.mark_drift_control_latent(latent, 12)
assert marked is not latent
assert drift.drift_control_latent_prefix_steps(marked) == 12
try:
    drift.drift_control_latent_prefix_steps(latent)
except ValueError as exc:
    assert "Chain Context's latent" in str(exc)
else:
    raise AssertionError("The inline patch accepted an unmarked stock latent")

conflicting = FakeModel()
conflicting.model_options["denoise_mask_function"] = lambda *args: args[1]
try:
    drift.install_drift_control_av_model(conflicting, latent, 12)
except ValueError as exc:
    assert "another dynamic denoise-mask" in str(exc)
else:
    raise AssertionError("A conflicting dynamic mask patch was accepted")

print(
    "Drift-Control AV: next-sigma ratios, 8+4 taper, packed sampler mask, "
    "H3 timestep mask, clean-reference split handoff, MODEL patch, and "
    "conflict guard passed")
