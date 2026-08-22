#!/usr/bin/env python3
"""Focused CPU tests for schedule-aware native H3 video-reference fading."""

import copy
import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_NAME = "h3_reference_video_fade_test_package"
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


fade = load_module("reference_video_fade")


schedule = torch.tensor([1.0, 0.75, 0.5, 0.25, 0.0])
assert fade.schedule_progress(1.0, schedule) == 0.0
assert fade.schedule_progress(0.5, schedule) == 0.5
assert fade.schedule_progress(0.375, schedule) == 0.625
assert fade.schedule_progress(0.0, schedule) == 1.0
assert fade.schedule_progress(float("nan"), schedule) is None

assert fade.reference_strength(0.49, 0.5, 0.0) == 1.0
assert abs(fade.reference_strength(0.75, 0.5, 0.0) - 0.5) < 1e-7
assert fade.reference_strength(1.0, 0.5, 0.15) == 0.15
assert fade.resolve_reference_video_fade_preset(
    "balanced", 0.1, 0.1) == (0.67, 0.20)
assert fade.resolve_reference_video_fade_preset(
    "custom", 0.6, 0.3) == (0.6, 0.3)


layout = types.SimpleNamespace(segments=(
    (0, 2, "text"),
    (2, 4, "ref_img"),       # native still picture: never faded
    (4, 8, "ref_img"),       # native video
    (8, 9, "ref_audio"),
    (9, 12, "ref_img"),      # native video+audio
    (12, 14, "ref_audio"),   # standalone reference audio
    (14, 16, "audio"),       # target audio
    (16, 22, "video"),       # target video
))
payload = {
    "layout": layout,
    "refs": (
        {"kind": "image"},
        {"kind": "video"},
        {"kind": "video_audio"},
        {"kind": "audio"},
    ),
}
ranges, sequence_length = fade.reference_video_ranges(payload)
assert ranges == ((4, 8), (9, 12))
assert sequence_length == 22

# Refuse an unknown row layout instead of accidentally fading a still picture
# or a target stream.
bad_payload = {
    "layout": types.SimpleNamespace(segments=((0, 2, "text"),
                                               (2, 4, "ref_img"),
                                               (4, 8, "video"))),
    "refs": ({"kind": "image"}, {"kind": "video"}),
}
assert fade.reference_video_ranges(bad_payload)[0] == ()

# The full schedule keeps a split tail at global progress 0.75. A local tail
# schedule [0.25, 0] would incorrectly call that progress 0 without override.
state = fade._ReferenceVideoFadeState(
    0.5, 0.0, schedule_override=schedule)
captured_diffusion = {}


def diffusion_executor(*args, **kwargs):
    captured_diffusion.update(kwargs)
    return "diffusion-ok"


assert state.diffusion_model_wrapper(
    diffusion_executor,
    "x",
    torch.tensor([250.0]),
    "context",
    transformer_options={"sample_sigmas": torch.tensor([0.25, 0.0])},
    minimax_payload=payload,
) == "diffusion-ok"
assert abs(state.current_progress - 0.75) < 1e-7
assert abs(state.current_strength - 0.5) < 1e-7
assert state.reference_ranges == ((4, 8), (9, 12))
assert captured_diffusion["minimax_payload"] is payload

# Only the two video-reference V slices are attenuated. The prior optimized
# attention override remains the executor, which is the SolAttn/CK composition
# contract used by the real node.
prior_capture = {}


def prior_override(original, q, k, v, heads, **kwargs):
    prior_capture["v"] = v.clone()
    prior_capture["kwargs"] = kwargs
    return "prior-ok"


override = state.make_attention_override(prior_override)
q = torch.ones((1, 2, 22, 3))
k = torch.ones_like(q)
v = torch.ones_like(q)
assert override(
    lambda *args, **kwargs: "dense-ok",
    q, k, v, 2,
    skip_reshape=True,
    transformer_options={"test": True},
) == "prior-ok"
seen = prior_capture["v"]
assert torch.equal(seen[..., :4, :], torch.ones_like(seen[..., :4, :]))
assert torch.equal(
    seen[..., 4:8, :], torch.full_like(seen[..., 4:8, :], 0.5))
assert torch.equal(seen[..., 8:9, :], torch.ones_like(seen[..., 8:9, :]))
assert torch.equal(
    seen[..., 9:12, :], torch.full_like(seen[..., 9:12, :], 0.5))
assert torch.equal(seen[..., 12:, :], torch.ones_like(seen[..., 12:, :]))
assert state.gated_attention_calls == 1

# The shorter text-token refiner attention must pass through untouched even
# while the main packed-sequence gate is active.
short_v = torch.ones((1, 2, 2, 3))
assert override(
    lambda *args, **kwargs: "dense-ok",
    torch.ones_like(short_v), torch.ones_like(short_v), short_v, 2,
    skip_reshape=True,
) == "prior-ok"
assert torch.equal(prior_capture["v"], torch.ones_like(short_v))
assert state.gated_attention_calls == 1


class ModelType:
    name = "FLOW_AV"


class InnerModel:
    model_type = ModelType()


class FakeModel:
    def __init__(self):
        self.model = InnerModel()
        self.model_options = {"transformer_options": {
            "optimized_attention_override": prior_override,
        }}
        self.wrappers = []

    def clone(self):
        cloned = FakeModel()
        cloned.model_options = copy.copy(self.model_options)
        cloned.model_options["transformer_options"] = copy.copy(
            self.model_options.get("transformer_options", {}))
        return cloned

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers.append((wrapper_type, key, wrapper))


comfy = types.ModuleType("comfy")
patcher_extension = types.ModuleType("comfy.patcher_extension")


class WrappersMP:
    DIFFUSION_MODEL = "diffusion_model"


patcher_extension.WrappersMP = WrappersMP
comfy.patcher_extension = patcher_extension
sys.modules["comfy"] = comfy
sys.modules["comfy.patcher_extension"] = patcher_extension

source = FakeModel()
patched = fade.install_reference_video_fade_model(
    source, 0.67, 0.20, schedule_override=schedule)
assert patched is not source
assert "h3_context_loop_reference_video_fade_recipe" not in (
    source.model_options)
recipe = patched.model_options[
    "h3_context_loop_reference_video_fade_recipe"]
assert recipe["fade_start"] == 0.67
assert recipe["end_strength"] == 0.20
assert recipe["full_schedule_values"] == 5
assert len(patched.wrappers) == 1
assert patched.wrappers[0][0:2] == (
    "diffusion_model", "h3_context_loop_reference_video_fade")
assert patched.model_options["transformer_options"][
    "optimized_attention_override"] is not prior_override

# Full is a true bypass: no clone, wrapper, or attention override is added.
assert fade.install_reference_video_fade_model(source, 1.0, 1.0) is source

node = fade.MiniMaxH3ReferenceVideoFadeModelPatch()
assert node.patch(source, "full", 0.2, 0.0)[0] is source

print("reference video fade unit test passed")
