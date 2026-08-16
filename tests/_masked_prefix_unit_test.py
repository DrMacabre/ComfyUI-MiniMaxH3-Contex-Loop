#!/usr/bin/env python3
"""CPU regression for recursive H3 masked AV target-prefix construction."""

import asyncio
import functools
import importlib.util
import json
import os
import sys
import types

import torch
import torch.nn.functional as functional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = "h3_mask_test_pkg"


class NestedTensor:
    def __init__(self, parts):
        self.parts = tuple(parts)

    def unbind(self):
        return list(self.parts)


def _install_comfy_stubs():
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    utils = types.ModuleType("comfy.utils")

    def common_upscale(samples, width, height, _method, _crop):
        return functional.interpolate(
            samples, size=(height, width), mode="bilinear",
            align_corners=False)

    utils.common_upscale = common_upscale
    utils.unpack_latents = lambda value, _shapes: value.unbind()
    nested = types.ModuleType("comfy.nested_tensor")
    nested.NestedTensor = NestedTensor
    comfy.utils = utils
    comfy.nested_tensor = nested
    sys.modules["comfy"] = comfy
    sys.modules["comfy.utils"] = utils
    sys.modules["comfy.nested_tensor"] = nested

    conds = types.ModuleType("comfy.conds")

    class CONDRegular:
        def __init__(self, value):
            self.cond = value

    conds.CONDRegular = CONDRegular
    comfy.conds = conds
    sys.modules["comfy.conds"] = conds

    ldm = types.ModuleType("comfy.ldm")
    ldm.__path__ = []
    minimax = types.ModuleType("comfy.ldm.minimax")
    minimax.__path__ = []
    model = types.ModuleType("comfy.ldm.minimax.model")

    class PackedLayout:
        pass

    model.PackedLayout = PackedLayout
    model.FRAME_RESCALE = 5.0 / 3.0
    comfy.ldm = ldm
    ldm.minimax = minimax
    minimax.model = model
    sys.modules["comfy.ldm"] = ldm
    sys.modules["comfy.ldm.minimax"] = minimax
    sys.modules["comfy.ldm.minimax.model"] = model

    model_base = types.ModuleType("comfy.model_base")

    class MiniMaxH3:
        def extra_conds(self, **_kwargs):
            return {}

    model_base.MiniMaxH3 = MiniMaxH3
    comfy.model_base = model_base
    sys.modules["comfy.model_base"] = model_base

    samplers = types.ModuleType("comfy.samplers")

    class KSamplerX0Inpaint:
        """Pre-989e7a9 sampler: scale does not receive denoise_mask."""

        def __call__(self, x, sigma, denoise_mask, model_options=None,
                     seed=None):
            options = model_options or {}
            mask_function = options.get("denoise_mask_function")
            if mask_function is not None:
                denoise_mask = mask_function(
                    sigma, denoise_mask, extra_options={})
            injected = self.inner_model.inner_model.scale_latent_inpaint(
                x=x, sigma=sigma, noise=self.noise,
                latent_image=self.latent_image)
            return x * denoise_mask + injected * (1.0 - denoise_mask)

    samplers.KSamplerX0Inpaint = KSamplerX0Inpaint
    comfy.samplers = samplers
    sys.modules["comfy.samplers"] = samplers

    helpers = types.ModuleType("node_helpers")
    helpers.conditioning_set_values = lambda value, *_args, **_kwargs: value
    sys.modules["node_helpers"] = helpers

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_output_directory = lambda: "/tmp"
    sys.modules["folder_paths"] = folder_paths

    safe = types.ModuleType("safetensors")
    safe_torch = types.ModuleType("safetensors.torch")
    safe_torch.load_file = None
    safe_torch.save_file = None
    safe.torch = safe_torch
    sys.modules["safetensors"] = safe
    sys.modules["safetensors.torch"] = safe_torch


def _load(name):
    path = os.path.join(ROOT, "%s.py" % name)
    spec = importlib.util.spec_from_file_location(
        "%s.%s" % (PACKAGE, name), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    _install_comfy_stubs()
    package = types.ModuleType(PACKAGE)
    package.__path__ = [ROOT]
    sys.modules[PACKAGE] = package
    _load("patch_layout")
    _load("patch_payload")
    nodes = _load("nodes")
    masked = _load("masked_context")
    masked._require_h3_mask_support = lambda: None

    target_frames = 192
    target_video_steps = 57
    target_audio_steps = 320
    assert nodes._pixel_frames(target_video_steps) == target_frames
    target_video = torch.zeros((1, 16, target_video_steps, 2, 3))
    target_audio = torch.zeros((1, 32, 2, target_audio_steps))
    target = {"samples": NestedTensor((target_video, target_audio))}

    previous_audio = torch.arange(
        1 * 32 * 2 * target_audio_steps, dtype=torch.float32).reshape(
            1, 32, 2, target_audio_steps)
    previous_video = torch.arange(
        target_video_steps, dtype=torch.float32).reshape(
            1, 1, target_video_steps, 1, 1).expand_as(target_video).clone()
    previous = {"samples": NestedTensor((
        previous_video, previous_audio,
    ))}
    frames = torch.zeros((64, 32, 48, 3), dtype=torch.float32)
    for index in range(int(frames.shape[0])):
        frames[index].fill_(float(index))

    class UnexpectedVideoVAE:
        def encode(self, _images):
            raise AssertionError(
                "generated continuation must not re-encode decoded frames")

    refs = [{"kind": "image", "latent_h": 2, "latent_w": 3}]
    conditioning = [["embedding", {
        "minimax_refs": refs,
        "minimax_keyframes": [
            {"resolved_frame_index": 0, "name": "conflicting first"},
            {"resolved_frame_index": 191, "name": "retained last"},
        ],
    }]]
    out_conditioning, out, trim = masked.apply_masked_prefix(
        conditioning=conditioning,
        vae=UnexpectedVideoVAE(),
        latent=target,
        previous_frames=frames,
        context_length=39,
        crop="disabled",
        previous_latent=previous,
    )

    assert trim == 39
    video, audio = out["samples"].unbind()
    video_mask, audio_mask = out["noise_mask"].unbind()
    prefix_video_steps = 12
    prefix_audio_steps = 65
    assert nodes._pixel_frames(prefix_video_steps) == 39
    assert torch.equal(
        video[:, :, :prefix_video_steps],
        previous_video[:, :, -prefix_video_steps:],
    )
    assert not torch.count_nonzero(video[:, :, prefix_video_steps:])
    assert torch.equal(
        audio[..., :prefix_audio_steps],
        previous_audio[..., -prefix_audio_steps:],
    )
    assert not torch.count_nonzero(audio[..., prefix_audio_steps:])
    assert not torch.count_nonzero(video_mask[:, :, :prefix_video_steps])
    assert torch.all(video_mask[:, :, prefix_video_steps:] == 1.0)
    assert not torch.count_nonzero(audio_mask[..., :prefix_audio_steps])
    assert torch.all(audio_mask[..., prefix_audio_steps:] == 1.0)

    _, feathered, feathered_trim = masked.apply_masked_prefix(
        conditioning=conditioning,
        vae=UnexpectedVideoVAE(),
        latent=target,
        previous_frames=frames,
        context_length=39,
        crop="disabled",
        previous_latent=previous,
        temporal_feather=True,
    )
    feathered_video_mask, feathered_audio_mask = (
        feathered["noise_mask"].unbind())
    assert feathered_trim == 39
    assert not torch.count_nonzero(feathered_video_mask[:, :, :8])
    assert torch.allclose(
        feathered_video_mask[0, 0, 8:12, 0, 0],
        torch.tensor([0.2, 0.4, 0.6, 0.8]),
    )
    assert torch.all(feathered_video_mask[:, :, 12:] == 1.0)
    assert not torch.count_nonzero(feathered_audio_mask[..., :42])
    assert torch.allclose(
        feathered_audio_mask[0, 0, 0, 42:65],
        torch.arange(1, 24, dtype=torch.float32) / 24.0,
    )
    assert torch.all(feathered_audio_mask[..., 65:] == 1.0)
    feathered_video, feathered_audio = feathered["samples"].unbind()
    assert torch.equal(
        feathered_video[:, :, :prefix_video_steps],
        previous_video[:, :, -prefix_video_steps:],
    )
    assert torch.equal(
        feathered_audio[..., :prefix_audio_steps],
        previous_audio[..., -prefix_audio_steps:],
    )

    existing_video_mask = torch.ones_like(target_video[:, :1])
    existing_video_mask[:, :, 8:12, 0, 0] = 0.1
    existing_audio_mask = torch.ones(
        (1, 1, int(target_audio.shape[2]), target_audio_steps))
    existing_audio_mask[..., 42:65] = 0.25
    pre_masked_target = {
        "samples": target["samples"],
        "noise_mask": NestedTensor((
            existing_video_mask, existing_audio_mask,
        )),
    }
    _, composed_feathered, _ = masked.apply_masked_prefix(
        conditioning=conditioning,
        vae=UnexpectedVideoVAE(),
        latent=pre_masked_target,
        previous_frames=frames,
        context_length=39,
        crop="disabled",
        previous_latent=previous,
        temporal_feather=True,
    )
    composed_video_mask, composed_audio_mask = (
        composed_feathered["noise_mask"].unbind())
    assert torch.allclose(
        composed_video_mask[0, 0, 8:12, 0, 0],
        torch.tensor([0.1, 0.1, 0.1, 0.1]),
    )
    assert torch.allclose(
        composed_video_mask[0, 0, 8:12, 0, 1],
        torch.tensor([0.2, 0.4, 0.6, 0.8]),
    )
    assert torch.allclose(
        composed_audio_mask[0, 0, 0, 42:65],
        torch.minimum(
            torch.arange(1, 24, dtype=torch.float32) / 24.0,
            torch.full((23,), 0.25),
        ),
    )

    metadata = out_conditioning[0][1]
    assert metadata["minimax_refs"] is refs
    assert [item["name"] for item in metadata["minimax_keyframes"]] == [
        "retained last"]
    assert not torch.count_nonzero(target_video)
    assert not torch.count_nonzero(target_audio)
    print(
        "masked prefix: 39 frames -> 12 video / 65 audio steps; target "
        "streams cloned, generated AV latent tails copied directly, future "
        "generated, refs retained")
    print(
        "feathered AV: first 8 video / 42 audio steps protected, final "
        "4 video / 23 audio prefix steps ramp smoothly toward generation")

    class VideoVAE:
        def __init__(self):
            self.calls = 0

        def encode(self, images):
            self.calls += 1
            steps = max(1, (int(images.shape[0]) - 5) // 17 * 5 + 2)
            value = float(images[-1, 0, 0, 0])
            return torch.full((1, 16, steps, 2, 3), value)

    class ImportedAudioVAE:
        audio_sample_rate = 32000

        def encode(self, _waveform):
            return torch.full((1, 32, 2, prefix_audio_steps), 17.0)

    imported_video_vae = VideoVAE()
    imported_target = {"samples": NestedTensor((
        torch.zeros_like(target_video), torch.zeros_like(target_audio),
    ))}
    _, imported_out, imported_trim = masked.apply_masked_prefix(
        conditioning=conditioning,
        vae=imported_video_vae,
        latent=imported_target,
        previous_frames=frames,
        context_length=39,
        crop="disabled",
        previous_latent=None,
        audio_vae=ImportedAudioVAE(),
        previous_audio={
            "waveform": torch.zeros((1, 2, 60000)),
            "sample_rate": 32000,
        },
    )
    imported_video, imported_audio = imported_out["samples"].unbind()
    assert imported_trim == 39
    assert imported_video_vae.calls == 1
    assert torch.all(imported_video[:, :, :prefix_video_steps] == 63.0)
    assert torch.all(imported_audio[..., :prefix_audio_steps] == 17.0)
    print("masked prefix: imported video/audio retain the VAE fallback path")

    chain = _load("chain_nodes")

    class ReviewInterrupted(BaseException):
        pass

    async def assert_review_interrupt_poll():
        future = asyncio.get_running_loop().create_future()
        original_check = chain._throw_if_review_interrupted

        def interrupt():
            raise ReviewInterrupted()

        chain._throw_if_review_interrupted = interrupt
        try:
            try:
                await chain._await_review_decision(future, 0)
            except ReviewInterrupted:
                pass
            else:
                raise AssertionError(
                    "Review Gate ignored the ComfyUI interruption check")
            assert not future.cancelled()
        finally:
            chain._throw_if_review_interrupted = original_check
            future.cancel()

    asyncio.run(assert_review_interrupt_poll())
    print("review gate: indefinite wait honors ComfyUI Stop/Cancel")
    plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "two", "prompt": "second", "length": 192},
        ]}),
        "masked_test", 64, 32, 39, "video", "head", "disabled",
        "generated_audio", 39, 8.0, 8, 1, 18, "model-stack-v1", 5,
        "masked_av",
    )
    assert plan["compatibility"]["continuation_mode"] == "masked_av"
    assert plan["shots"][1]["delivered_frames"] == 153
    assert "context=39/masked_av" in plan["summary"]
    assert "continuation_mode" not in chain._history_contract(
        plan, 1)["compatibility"]
    assert chain._legacy_history_contract(plan, 1)["compatibility"][
        "continuation_mode"] == "masked_av"
    feathered_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "two", "prompt": "second", "length": 192},
        ]}),
        "feathered_test", 64, 32, 39, "video", "head", "disabled",
        "generated_audio", 39, 8.0, 8, 1, 18, "model-stack-v1", 5,
        "feathered_av",
    )
    assert feathered_plan["compatibility"][
        "continuation_mode"] == "feathered_av"
    assert "context=39/feathered_av" in feathered_plan["summary"]
    guide_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "two", "prompt": "second", "length": 192},
        ]}),
        "guide_test", 64, 32, 39, "video", "head", "disabled",
        "generated_audio", 39, 8.0, 8, 1, 18, "model-stack-v1", 5,
        "guide",
    )
    assert "continuation_mode" not in guide_plan["compatibility"]
    # The Plan-wide selector chooses how the next scene consumes an immutable
    # predecessor. It must not invalidate that predecessor's resume history.
    assert chain._history_hash(plan, 1) == chain._history_hash(guide_plan, 1)
    assert chain._history_hash(plan, 2) == chain._history_hash(guide_plan, 2)
    legacy_masked_hash = chain._fingerprint(
        chain._legacy_history_contract(plan, 1))
    assert chain._accepted_resume_history_hash(guide_plan, 1, {
        "history_hash": legacy_masked_hash,
        "compatibility": dict(plan["compatibility"]),
    }) == legacy_masked_hash
    legacy_guide_hash = chain._fingerprint(
        chain._legacy_history_contract(guide_plan, 1))
    assert chain._accepted_resume_history_hash(plan, 1, {
        "history_hash": legacy_guide_hash,
        "compatibility": dict(guide_plan["compatibility"]),
    }) == legacy_guide_hash
    short_context_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "two", "prompt": "second", "length": 192},
        ]}),
        "short_context_test", 64, 32, 22, "video", "head", "disabled",
        "generated_audio", 39, 8.0, 8, 1, 18, "model-stack-v1", 5,
        "guide",
    )
    assert chain._history_hash(short_context_plan, 1) == chain._history_hash(
        guide_plan, 1)
    assert chain._history_hash(short_context_plan, 2) != chain._history_hash(
        guide_plan, 2)
    legacy_short_context_hash = chain._fingerprint(
        chain._legacy_history_contract(short_context_plan, 1))
    legacy_short_context_metadata = {
        "history_hash": legacy_short_context_hash,
        "compatibility": dict(short_context_plan["compatibility"]),
    }
    assert chain._accepted_resume_history_hash(
        guide_plan, 1, legacy_short_context_metadata,
    ) == legacy_short_context_hash
    intermediate_plan = json.loads(json.dumps(short_context_plan))
    intermediate_plan["compatibility"]["continuation_mode"] = "masked_av"
    intermediate_contract = chain._legacy_history_contract(
        intermediate_plan, 1)
    intermediate_contract["compatibility"] = dict(
        intermediate_contract["compatibility"])
    intermediate_contract["compatibility"].pop("continuation_mode")
    intermediate_hash = chain._fingerprint(intermediate_contract)
    assert chain._accepted_resume_history_hash(guide_plan, 1, {
        "history_hash": intermediate_hash,
        "compatibility": dict(intermediate_plan["compatibility"]),
    }) == intermediate_hash
    legacy_short_context_metadata["history_hash"] = chain._fingerprint(
        chain._legacy_history_contract(short_context_plan, 2))
    assert chain._accepted_resume_history_hash(
        guide_plan, 2, legacy_short_context_metadata,
    ) is None

    class ContextDecodeVAE:
        def decode(self, _latent):
            decoded = torch.zeros((192, 32, 48, 3), dtype=torch.float32)
            for frame_index in range(192):
                decoded[frame_index].fill_(float(frame_index))
            return decoded

    recovered = chain._previous_context_frames({
        "previous_frames": frames[-22:],
        "previous_latent": previous,
        "segments": [{
            "index": 1, "raw_frames": 192, "delivered_frames": 192,
        }],
    }, ContextDecodeVAE(), 39)
    assert tuple(recovered.shape) == (39, 32, 48, 3)
    assert float(recovered[0, 0, 0, 0]) == 153.0
    assert float(recovered[-1, 0, 0, 0]) == 191.0
    changed_prompt_plan = json.loads(json.dumps(guide_plan))
    changed_prompt_plan["shots"][0]["prompt_hash"] = "different-prompt"
    assert chain._accepted_resume_history_hash(changed_prompt_plan, 1, {
        "history_hash": legacy_masked_hash,
        "compatibility": dict(plan["compatibility"]),
    }) is None
    incompatible_metadata = {
        "history_hash": legacy_masked_hash,
        "compatibility": dict(plan["compatibility"]),
    }
    assert chain._selected_resume_history_hash(
        changed_prompt_plan, 1, incompatible_metadata, True) is None
    assert chain._selected_resume_history_hash(
        changed_prompt_plan, 1, incompatible_metadata, False,
    ) == legacy_masked_hash
    loop_start_inputs = chain.MiniMaxH3ChainLoopStart.INPUT_TYPES()
    assert loop_start_inputs["optional"]["verify_resume_history"][1][
        "default"] is True
    resume_calls = []
    original_resume_loader = chain._load_resume_state

    def fake_resume_loader(requested_plan, start_clip, verify_history=True,
                           source_timeline=None, source_audio=None):
        resume_calls.append((start_clip, verify_history))
        return {
            "plan": requested_plan,
            "index": start_clip,
            "segments": [],
            "resumed_from": start_clip - 1,
        }

    chain._load_resume_state = fake_resume_loader
    try:
        unsafe_initial = chain._initial_state(
            changed_prompt_plan, 2, verify_resume_history=False)
    finally:
        chain._load_resume_state = original_resume_loader
    assert unsafe_initial["index"] == 2
    assert resume_calls == [(2, False)]
    mixed_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "new_shot", "prompt": "first", "length": 192},
            {"id": "same_shot", "prompt": "second", "length": 192,
             "continuation_mode": "masked_av"},
        ]}),
        "mixed_test", 64, 32, 39, "video", "head", "disabled",
        "generated_audio", 22, 8.0, 8, 1, 18, "model-stack-v1", 5,
        "guide",
    )
    assert "continuation_mode" not in mixed_plan["compatibility"]
    assert "continuation_mode" not in mixed_plan["shots"][0]
    assert mixed_plan["shots"][1]["continuation_mode"] == "masked_av"
    assert "context=39/mixed" in mixed_plan["summary"]
    assert "continuation_mode" not in chain._history_contract(
        mixed_plan, 1)["shots"][0]
    assert chain._history_contract(mixed_plan, 2)["shots"][1][
        "continuation_mode"] == "masked_av"
    changed_scene_mode_plan = json.loads(json.dumps(mixed_plan))
    changed_scene_mode_plan["shots"][1]["continuation_mode"] = "guide"
    assert chain._history_hash(mixed_plan, 2) != chain._history_hash(
        changed_scene_mode_plan, 2)
    assert chain._effective_editor_plan(mixed_plan)["shots"][1][
        "continuation_mode"] == "masked_av"
    per_scene_context_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "clean", "prompt": "independent", "length": 192,
             "context_length": 0, "continuation_mode": "masked_av"},
            {"id": "long_context", "prompt": "continued", "length": 192,
             "context_length": 39},
        ]}),
        "scene_context_test", 64, 32, 22, "frames", "before", "disabled",
        "generated_audio", 22, 8.0, 8, 1, 18, "model-stack-v1", 0,
        "guide",
    )
    assert [shot["delivered_frames"] for shot in
            per_scene_context_plan["shots"]] == [192, 192, 192]
    assert per_scene_context_plan["shots"][1]["context_length"] == 0
    assert per_scene_context_plan["shots"][2]["context_length"] == 39
    assert per_scene_context_plan["compatibility"][
        "context_storage_length"] == 39
    assert chain._history_contract(per_scene_context_plan, 2)["shots"][1][
        "context_length"] == 0
    assert chain._effective_editor_plan(per_scene_context_plan)["shots"][1][
        "context_length"] == 0
    clean_result = chain.MiniMaxH3ChainContext().apply(
        {"plan": per_scene_context_plan, "index": 2,
         "previous_frames": frames, "previous_latent": previous},
        conditioning, VideoVAE(), target)
    assert clean_result[:3] == (conditioning, 0, False)
    assert clean_result[3] is target
    audio_only_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 192},
            {"id": "audio_only", "prompt": "new visual", "length": 192,
             "context_length": 0, "audio_context_length": 33},
        ]}),
        "audio_only_context_test", 64, 32, 22, "video", "head",
        "disabled", "generated_audio", 22, 8.0, 8, 1, 18,
        "model-stack-v1", 0, "guide",
    )
    assert audio_only_plan["shots"][1]["delivered_frames"] == 192
    assert audio_only_plan["shots"][1]["audio_context_length"] == 33
    assert chain._history_contract(audio_only_plan, 2)["shots"][1][
        "audio_context_length"] == 33
    assert chain._effective_editor_plan(audio_only_plan)["shots"][1][
        "audio_context_length"] == 33
    original_activate = nodes._activate_inline_patches
    nodes._activate_inline_patches = lambda: "native"
    try:
        audio_only_result = chain.MiniMaxH3ChainContext().apply(
            {"plan": audio_only_plan, "index": 2,
             "previous_frames": frames, "previous_latent": previous},
            conditioning, VideoVAE(), target)
    finally:
        nodes._activate_inline_patches = original_activate
    assert audio_only_result[1:3] == (0, True)
    assert audio_only_result[3] is target
    assert any("audio_latent" in keyframe for keyframe in
               audio_only_result[0][0][1]["minimax_keyframes"])
    mixed_state = {
        "plan": mixed_plan,
        "index": 2,
        "previous_frames": frames,
        "previous_latent": previous,
    }
    mixed_result = chain.MiniMaxH3ChainContext().apply(
        mixed_state, conditioning, VideoVAE(), target)
    assert mixed_result[1:3] == (39, True)
    assert "noise_mask" in mixed_result[3]
    feathered_state = dict(mixed_state)
    feathered_state["plan"] = feathered_plan
    feathered_result = chain.MiniMaxH3ChainContext().apply(
        feathered_state, conditioning, VideoVAE(), target)
    assert feathered_result[1:3] == (39, True)
    feathered_chain_video_mask, feathered_chain_audio_mask = (
        feathered_result[3]["noise_mask"].unbind())
    assert torch.allclose(
        feathered_chain_video_mask[0, 0, 8:12, 0, 0],
        torch.tensor([0.2, 0.4, 0.6, 0.8]),
    )
    assert torch.allclose(
        feathered_chain_audio_mask[0, 0, 0, 42:65],
        torch.arange(1, 24, dtype=torch.float32) / 24.0,
    )

    preflight_calls = []
    original_require = masked._require_h3_mask_support
    original_prepare = chain._prepare_native_guide_conditioning
    masked._require_h3_mask_support = lambda: preflight_calls.append("masked")
    chain._prepare_native_guide_conditioning = lambda value: (
        preflight_calls.append("guide") or value)
    try:
        mixed_first_result = chain.MiniMaxH3ChainContext().apply(
            {"plan": mixed_plan, "index": 1, "external_context": False},
            conditioning, VideoVAE(), target)
    finally:
        masked._require_h3_mask_support = original_require
        chain._prepare_native_guide_conditioning = original_prepare
    assert mixed_first_result[:3] == (conditioning, 0, False)
    assert preflight_calls == ["masked", "guide"]
    imported_audio = {
        "waveform": torch.zeros((1, 2, 6400), dtype=torch.float32),
        "sample_rate": 2400,
    }
    external_context, _status = chain.MiniMaxH3ChainExternalVideo().prepare(
        plan, frames, 24.0, False, imported_audio)
    assert int(external_context["context_frames"].shape[0]) == 39
    assert int(external_context["context_audio"]["waveform"].shape[-1]) == 3900
    mixed_external_context, _status = (
        chain.MiniMaxH3ChainExternalVideo().prepare(
            mixed_plan, frames, 24.0, False, imported_audio))
    assert int(mixed_external_context[
        "context_audio"]["waveform"].shape[-1]) == 2200
    zero_external_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "clean_first", "prompt": "first", "length": 192,
             "context_length": 0},
        ]}),
        "zero_external_test", 64, 32, 22, "video", "head", "disabled",
        "generated_audio", 22, 8.0, 8, 1, 18, "model-stack-v1", 0,
        "guide",
    )
    zero_external_context, _status = (
        chain.MiniMaxH3ChainExternalVideo().prepare(
            zero_external_plan, frames, 24.0, False, imported_audio))
    assert int(zero_external_context["context_frames"].shape[0]) == 0
    assert int(zero_external_context[
        "context_audio"]["waveform"].shape[-1]) == 2200
    zero_external_prepared = chain._plan_with_external_context(
        zero_external_plan, zero_external_context)
    assert zero_external_prepared["shots"][0]["delivered_frames"] == 192
    fully_clean_external_plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "fully_clean", "prompt": "first", "length": 192,
             "context_length": 0, "audio_context_length": 0},
        ]}),
        "fully_clean_external_test", 64, 32, 22, "video", "head",
        "disabled", "generated_audio", 22, 8.0, 8, 1, 18,
        "model-stack-v1", 0, "guide",
    )
    fully_clean_context, _status = (
        chain.MiniMaxH3ChainExternalVideo().prepare(
            fully_clean_external_plan, frames, 24.0, False, imported_audio))
    assert int(fully_clean_context["context_frames"].shape[0]) == 0
    assert fully_clean_context["context_audio"] is None
    first_state = {
        "plan": plan,
        "index": 1,
        "external_context": False,
    }
    first_result = chain.MiniMaxH3ChainContext().apply(
        first_state, conditioning, VideoVAE(), target)
    assert first_result[:3] == (conditioning, 0, False)
    assert first_result[3] is target
    for av_mode in ("masked_av", "feathered_av"):
        for invalid_args, expected in (
            ((1, "video", "head"), "at least 5"),
            ((39, "frames", "head"), "encode_mode=video"),
            ((39, "video", "before"), "anchor_mode=head"),
        ):
            context, encode, anchor = invalid_args
            try:
                chain._normalize_plan(
                    json.dumps({"shots": [
                        {"id": "one", "prompt": "first", "length": 192},
                        {"id": "two", "prompt": "second", "length": 192},
                    ]}),
                    "invalid_masked_test", 64, 32, context, encode, anchor,
                    "disabled", "generated_audio", 39, 8.0, 8, 1, 18,
                    "model-stack-v1", 0, av_mode,
                )
            except ValueError as exc:
                assert expected in str(exc), str(exc)
            else:
                raise AssertionError(
                    "%s plan accepted invalid %s/%s/%s" %
                    (av_mode, *invalid_args))
    try:
        chain._normalize_plan(
            json.dumps({"shots": [
                {"id": "one", "prompt": "first", "length": 192},
                {"id": "two", "prompt": "second", "length": 192,
                 "continuation_mode": "masked_av"},
            ]}),
            "invalid_scene_masked_test", 64, 32, 1, "video", "head",
            "disabled", "generated_audio", 1, 8.0, 8, 1, 18,
            "model-stack-v1", 0, "guide",
        )
    except ValueError as exc:
        assert "shot 2" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("per-scene masked mode accepted context_length=1")
    print(
        "masked plan: global mode/context are next-scene controls, explicit "
        "scene settings are history-significant, and invalid configurations "
        "are rejected")

    # Native post-989e7a9 PR #15375 support must remain authoritative. The
    # removed process_denoise_mask hook must not be recreated on this path.
    h3m = sys.modules["comfy.ldm.minimax.model"]
    model_base = sys.modules["comfy.model_base"]
    samplers = sys.modules["comfy.samplers"]
    legacy_sampler = samplers.KSamplerX0Inpaint

    def mask_row_values(*_args):
        return None

    def mod_row(*_args):
        return None

    class NativeModel:
        def forward(self, x, denoise_mask=None, audio_denoise_mask=None):
            return x

        def _forward(self, x, denoise_mask=None, audio_denoise_mask=None):
            return x

    class NativeFinal:
        def forward(self, value):
            return value

    class NativeBase:
        def process_timestep(
                self, timestep, denoise_mask=None, audio_denoise_mask=None):
            return timestep

        def scale_latent_inpaint(
                self, sigma, noise, latent_image, x=None,
                denoise_mask=None, **kwargs):
            return kwargs

        def extra_conds(self, **kwargs):
            # Bytecode exposes both native payload keys.
            return {
                "denoise_mask": kwargs.get("denoise_mask"),
                "audio_denoise_mask": kwargs.get("audio_denoise_mask"),
            }

    class NativeSampler:
        def __call__(self, x, sigma, denoise_mask, model_options=None,
                     seed=None):
            return self.inner_model.inner_model.scale_latent_inpaint(
                x=x, sigma=sigma, noise=self.noise,
                latent_image=self.latent_image,
                denoise_mask=denoise_mask)

    h3m.mask_row_values = mask_row_values
    h3m._mod_row = mod_row
    h3m.MiniMaxH3Model = NativeModel
    h3m.FinalLayer = NativeFinal
    model_base.MiniMaxH3 = NativeBase
    samplers.KSamplerX0Inpaint = NativeSampler
    native_forward = NativeModel.forward
    native_extra = NativeBase.extra_conds
    native_scale = NativeBase.scale_latent_inpaint
    native_sampler_call = NativeSampler.__call__
    mask_compat = _load("h3_mask_compat")
    payload_compat = _load("h3_mask_payload_compat")
    assert mask_compat.ensure_h3_mask_compat()
    assert payload_compat.ensure_av_mask_payload_compat()
    assert h3m.MiniMaxH3Model.forward is native_forward
    assert model_base.MiniMaxH3.extra_conds is native_extra
    assert model_base.MiniMaxH3.scale_latent_inpaint is native_scale
    assert samplers.KSamplerX0Inpaint.__call__ is native_sampler_call
    assert "process_denoise_mask" not in NativeBase.__dict__
    native_status = mask_compat.capability_status()
    assert native_status["mask_engine_native"]
    assert native_status["scale_latent_inpaint_native"]
    assert native_status["sampler_mask_blend_native"]
    assert payload_compat.capability_status()["native_av_mask_payload"]
    assert mask_compat._MARKER == "_h3_motion_context_pr15375_compat_v3"

    def wrapper(self, **kwargs):
        return native_extra(self, **kwargs)

    setattr(wrapper, payload_compat._MARKER, True)
    assert payload_compat._is_compatible_wrapper(wrapper)
    print(
        "mask compatibility: native post-989e7a9 model/sampler support is "
        "detected and left untouched; the removed preprocessing hook stays "
        "removed")

    # A legacy post-#15439 H3 core receives all missing #15375 pieces lazily.
    for name in ("mask_row_values", "_mod_row"):
        delattr(h3m, name)

    class LegacyModel:
        def forward(self, x, timestep, context, transformer_options={},
                    minimax_payload=None, **kwargs):
            return x

        def _forward(self, x, timestep, context, transformer_options={},
                     minimax_payload=None, **kwargs):
            return x

    class LegacyFinal:
        def forward(self, x, t_emb, video_seg, audio_seg):
            return x

    class LegacyBase:
        latent_shapes = None

        def extra_conds(self, **_kwargs):
            return {}

    h3m.MiniMaxH3Model = LegacyModel
    h3m.FinalLayer = LegacyFinal
    h3m.torch = torch
    h3m.VISUAL_COND_TIMESTEP = 0.2
    model_base.MiniMaxH3 = LegacyBase
    model_base.torch = torch
    samplers.KSamplerX0Inpaint = legacy_sampler

    video_shape = (1, 1, 1, 2, 2)
    audio_shape = (1, 2, 2, 1)
    latent_shapes = (video_shape, audio_shape)

    def pack_latents(parts):
        return torch.cat(
            [part.reshape(part.shape[0], -1) for part in parts], dim=1), None

    def unpack_latents(value, shapes):
        parts = []
        offset = 0
        for shape in shapes:
            count = 1
            for size in shape[1:]:
                count *= size
            parts.append(value[:, offset:offset + count].reshape(shape))
            offset += count
        return parts

    utils = sys.modules["comfy.utils"]
    utils.unpack_latents = unpack_latents
    utils.pack_latents = pack_latents
    model_base.utils = utils
    model_base.comfy = sys.modules["comfy"]
    fallback_mask = _load("h3_mask_compat")
    fallback_payload = _load("h3_mask_payload_compat")
    assert not fallback_mask.capability_status()["mask_engine_complete"]
    assert fallback_mask.ensure_h3_mask_compat()
    fallback_status = fallback_mask.capability_status()
    assert fallback_status["mask_engine_compat"]
    assert fallback_status["process_denoise_mask_compat"]
    assert fallback_status["scale_latent_inpaint_compat"]
    assert fallback_status["sampler_mask_blend_compat"]
    assert fallback_mask.is_ready()

    class Patch:
        patch_size = (1, 2, 2)

    class LegacyRuntime(LegacyBase):
        def __init__(self):
            self.latent_shapes = latent_shapes
            self.diffusion_model = Patch()

        def audio_scale(self):
            return 1.0

    model_base.MiniMaxH3 = LegacyRuntime
    # Reattach the lazily installed class hooks after specializing the test
    # runtime, as ComfyUI uses one stable MiniMaxH3 class in production.
    for name in (
        "process_denoise_mask",
        "_pool_masks_to_token_grid",
        "scale_latent_inpaint",
    ):
        setattr(LegacyRuntime, name, getattr(LegacyBase, name))

    runtime = LegacyRuntime()
    video_mask = torch.tensor([[[[[0.25, 0.50], [0.75, 0.30]]]]])
    audio_mask = torch.tensor(
        [[[[0.25], [0.25]], [[0.75], [0.50]]]])
    packed_mask = pack_latents([video_mask, audio_mask])[0]
    packed_zero = torch.zeros_like(packed_mask)
    packed_x = torch.full_like(packed_mask, 10.0)
    sampler = samplers.KSamplerX0Inpaint()
    sampler.inner_model = types.SimpleNamespace(inner_model=runtime)
    sampler.noise = packed_zero
    sampler.latent_image = packed_zero
    result = sampler(
        packed_x, torch.ones((1,)), packed_mask, model_options={})
    result_video, result_audio = unpack_latents(result, latent_shapes)
    assert torch.allclose(
        result_video, torch.full_like(result_video, 7.5)), result_video
    expected_result_audio = torch.tensor(
        [[[[7.5], [5.0]], [[7.5], [5.0]]]])
    assert torch.allclose(result_audio, expected_result_audio)
    assert not hasattr(runtime, fallback_mask._ACTIVE_MASK_ATTR)

    half_mask = torch.full_like(packed_mask, 0.5)

    def replace_mask(_sigma, _mask, extra_options=None):
        return half_mask

    replaced = sampler(
        packed_x, torch.ones((1,)), packed_mask,
        model_options={"denoise_mask_function": replace_mask})
    assert torch.allclose(replaced, torch.full_like(replaced, 5.0))
    assert not hasattr(runtime, fallback_mask._ACTIVE_MASK_ATTR)
    original_parts = [video_mask, audio_mask]
    assert runtime.process_denoise_mask(original_parts) is original_parts

    payload_base = LegacyRuntime.extra_conds

    def add_legacy_payload(out, kwargs):
        masks = unpack_latents(kwargs["denoise_mask"],
                               kwargs["latent_shapes"])
        out["denoise_mask"] = sys.modules["comfy.conds"].CONDRegular(
            masks[0][:, :1])
        out["audio_denoise_mask"] = sys.modules[
            "comfy.conds"].CONDRegular(masks[1][:, :1])

    @functools.wraps(payload_base, updated=())
    def legacy_payload_wrapper(self, **kwargs):
        out = payload_base(self, **kwargs)
        add_legacy_payload(out, kwargs)
        return out

    setattr(legacy_payload_wrapper, fallback_payload._LEGACY_MARKER, True)
    LegacyRuntime.extra_conds = legacy_payload_wrapper
    before_payload = LegacyRuntime.extra_conds
    assert fallback_payload.ensure_av_mask_payload_compat()
    assert LegacyRuntime.extra_conds is not before_payload
    assert not any(fallback_payload._is_legacy_wrapper(item) for item in
                   fallback_payload._walk_wrapped(
                       LegacyRuntime.extra_conds))
    assert fallback_payload.capability_status()["wrapper_present"]
    payload_out = runtime.extra_conds(
        denoise_mask=packed_mask, latent_shapes=latent_shapes)
    expected_video = torch.round(video_mask * 256.0) / 256.0
    expected_audio = torch.round(audio_mask * 256.0) / 256.0
    expected_audio = expected_audio.amax(dim=1, keepdim=True)
    assert torch.equal(
        payload_out["denoise_mask"].cond, expected_video), (
            payload_out["denoise_mask"].cond, expected_video)
    assert torch.equal(payload_out["audio_denoise_mask"].cond,
                       expected_audio)
    print(
        "mask compatibility: legacy post-#15439 H3 receives the 989e7a9 "
        "token-grid blend, per-step sampler bridge, and quantized AV payload")


if __name__ == "__main__":
    main()
