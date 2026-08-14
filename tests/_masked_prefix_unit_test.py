#!/usr/bin/env python3
"""CPU regression for recursive H3 masked AV target-prefix construction."""

import asyncio
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
    previous = {"samples": NestedTensor((
        torch.zeros_like(target_video), previous_audio,
    ))}
    frames = torch.zeros((64, 32, 48, 3), dtype=torch.float32)
    for index in range(int(frames.shape[0])):
        frames[index].fill_(float(index))

    class VideoVAE:
        def encode(self, images):
            steps = max(1, (int(images.shape[0]) - 5) // 17 * 5 + 2)
            value = float(images[-1, 0, 0, 0])
            return torch.full((1, 16, steps, 2, 3), value)

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
        vae=VideoVAE(),
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
    assert torch.all(video[:, :, :prefix_video_steps] == 63.0)
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

    metadata = out_conditioning[0][1]
    assert metadata["minimax_refs"] is refs
    assert [item["name"] for item in metadata["minimax_keyframes"]] == [
        "retained last"]
    assert not torch.count_nonzero(target_video)
    assert not torch.count_nonzero(target_audio)
    print(
        "masked prefix: 39 frames -> 12 video / 65 audio steps; target "
        "streams cloned, prefix preserved, future generated, refs retained")

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
    assert chain._history_contract(plan, 1)["compatibility"][
        "continuation_mode"] == "masked_av"
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
                "model-stack-v1", 0, "masked_av",
            )
        except ValueError as exc:
            assert expected in str(exc), str(exc)
        else:
            raise AssertionError(
                "masked plan accepted invalid %s/%s/%s" % invalid_args)
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
        "masked plan: mode participates in compatibility/history and rejects "
        "non-video, non-head, or sub-5-frame configurations")

    # Native PR #15375-equivalent hooks must remain authoritative: neither
    # compatibility module may wrap or replace them.
    h3m = sys.modules["comfy.ldm.minimax.model"]
    model_base = sys.modules["comfy.model_base"]

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

        def process_denoise_mask(self, masks):
            return masks

        def scale_latent_inpaint(self, **kwargs):
            return kwargs

        def extra_conds(self, **kwargs):
            # Bytecode exposes both native payload keys.
            return {
                "denoise_mask": kwargs.get("denoise_mask"),
                "audio_denoise_mask": kwargs.get("audio_denoise_mask"),
            }

    h3m.mask_row_values = mask_row_values
    h3m._mod_row = mod_row
    h3m.MiniMaxH3Model = NativeModel
    h3m.FinalLayer = NativeFinal
    model_base.MiniMaxH3 = NativeBase
    native_forward = NativeModel.forward
    native_extra = NativeBase.extra_conds
    mask_compat = _load("h3_mask_compat")
    payload_compat = _load("h3_mask_payload_compat")
    assert mask_compat.ensure_h3_mask_compat()
    assert payload_compat.ensure_av_mask_payload_compat()
    assert h3m.MiniMaxH3Model.forward is native_forward
    assert model_base.MiniMaxH3.extra_conds is native_extra
    assert mask_compat.capability_status()["mask_engine_native"]
    assert payload_compat.capability_status()["native_av_mask_payload"]
    assert mask_compat._MARKER == "_h3_motion_context_pr15375_compat_v2"

    def wrapper(self, **kwargs):
        return native_extra(self, **kwargs)

    setattr(wrapper, payload_compat._MARKER, True)
    assert payload_compat._is_compatible_wrapper(wrapper)
    print(
        "mask compatibility: complete native PR #15375-equivalent hooks are "
        "detected and left untouched; sibling marker ABI is recognized")

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
        def extra_conds(self, **_kwargs):
            return {}

    h3m.MiniMaxH3Model = LegacyModel
    h3m.FinalLayer = LegacyFinal
    h3m.torch = torch
    model_base.MiniMaxH3 = LegacyBase
    model_base.torch = torch
    model_base.utils = types.SimpleNamespace(
        unpack_latents=lambda *_args: [],
        pack_latents=lambda *_args: (None,),
    )
    model_base.comfy = sys.modules["comfy"]
    fallback_mask = _load("h3_mask_compat")
    fallback_payload = _load("h3_mask_payload_compat")
    assert not fallback_mask.capability_status()["mask_engine_complete"]
    assert fallback_mask.ensure_h3_mask_compat()
    fallback_status = fallback_mask.capability_status()
    assert fallback_status["mask_engine_compat"]
    assert fallback_status["process_denoise_mask_compat"]
    assert fallback_status["scale_latent_inpaint_compat"]
    before_payload = LegacyBase.extra_conds
    assert fallback_payload.ensure_av_mask_payload_compat()
    assert LegacyBase.extra_conds is not before_payload
    assert fallback_payload.capability_status()["wrapper_present"]
    print(
        "mask compatibility: legacy post-#15439 H3 receives the complete lazy "
        "#15375 engine, model hooks, and AV payload wrapper")


if __name__ == "__main__":
    main()
