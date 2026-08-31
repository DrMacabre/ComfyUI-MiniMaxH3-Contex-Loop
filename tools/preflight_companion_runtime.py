#!/usr/bin/env python3
"""Read-only installed-runtime preflight for the MASTER companion nodepack.

Run this with ComfyUI's own Python interpreter and pass ``--comfy-root``.
The companion needs native H3 Add Guide / MultiRef support, but the later
MiniMax tokenizer (#15808) and masked-AV (#15375) changes may be supplied by
MASTER's private MODEL/CLIP compatibility boundary.  This probe therefore
checks both native and scoped paths without importing the package entrypoint or
installing any compatibility patch.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load %s from %s" % (name, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _safe_git_head(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"present": False, "head": "", "branch": "", "clean": None}
    result: dict[str, Any] = {
        "present": True,
        "head": "",
        "branch": "",
        "clean": None,
    }
    try:
        result["head"] = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        result["branch"] = subprocess.check_output(
            ["git", "-C", str(path), "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        result["clean"] = not bool(status.strip())
    except Exception as exc:
        result["git_probe_error"] = str(exc)
    return result


def _object_snapshot():
    import comfy.ldm.minimax.model as h3m
    import comfy.model_base as model_base
    import comfy.samplers as samplers
    import comfy.text_encoders.minimax as minimax_text

    packed = getattr(h3m, "PackedLayout", None)
    model = getattr(model_base, "MiniMaxH3", None)
    sampler = getattr(samplers, "KSamplerX0Inpaint", None)
    return {
        "packed_layout_init": getattr(packed, "__init__", None),
        "extra_conds": getattr(model, "extra_conds", None),
        "scale_latent_inpaint": getattr(model, "scale_latent_inpaint", None),
        "sampler_call": getattr(sampler, "__call__", None),
        "tokenizer_alias": getattr(minimax_text, "Qwen3VLSDTokenizer", None),
        "native_tokenizer": getattr(
            minimax_text, "MiniMaxQwenSDTokenizer", None),
    }


def _same_snapshot(before, after):
    return all(after.get(key) is value for key, value in before.items())


def _callable_attrs(owner: Any, names: tuple[str, ...]) -> dict[str, bool]:
    return {name: callable(getattr(owner, name, None)) for name in names}


def _scoped_tokenizer_support(minimax_text) -> dict[str, Any]:
    import comfy.sd as comfy_sd

    clip_api = _callable_attrs(getattr(comfy_sd, "CLIP", None), ("clone",))
    # Old and new cores both expose a MiniMax Qwen tokenizer family.  MASTER's
    # proxy wraps the loaded qwen3vl_32b instance rather than changing this
    # module-global class.
    tokenizer_family = any(
        getattr(minimax_text, name, None) is not None
        for name in ("Qwen3VLTokenizer", "Qwen3VLSDTokenizer",
                     "MiniMaxQwenSDTokenizer")
    )
    return {
        "clip_clone": bool(clip_api["clone"]),
        "minimax_qwen_tokenizer_family": bool(tokenizer_family),
        "ready": bool(clip_api["clone"] and tokenizer_family),
    }


def _dynamic_class_swap_supported() -> tuple[bool, str]:
    """Exercise the exact Python mechanism used by ModelPatcher object patches.

    Only a tiny local torch module is touched; no ComfyUI class or loaded model
    is modified.
    """
    try:
        import torch

        base = torch.nn.Identity
        scoped = type(
            "_DMH3MasterPreflightIdentity", (base,),
            {"_dmh3_master_preflight": True})
        instance = base()
        original = instance.__class__
        instance.__class__ = scoped
        if instance.__class__ is not scoped:
            return False, "temporary subclass assignment did not take effect"
        instance.__class__ = original
        if instance.__class__ is not original:
            return False, "original class was not restored"
        return True, "temporary subclass swap/restoration works"
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)


def _scoped_mask_support(h3m, model_base, model_patcher) -> dict[str, Any]:
    patcher_api = _callable_attrs(
        getattr(model_patcher, "ModelPatcher", None),
        ("clone", "add_object_patch", "set_model_denoise_mask_function"),
    )
    base_cls = getattr(model_base, "MiniMaxH3", None)
    diffusion_cls = getattr(h3m, "MiniMaxH3Model", None)
    base_api = _callable_attrs(
        base_cls, ("extra_conds", "scale_latent_inpaint"))
    diffusion_api = _callable_attrs(diffusion_cls, ("_forward",))

    helper_names = (
        "PackedLayout",
        "time_shift_sigma",
        "patchify_video",
        "pack_audio",
        "rope_rotation_table",
        "unpatchify_video",
        "unpack_audio",
    )
    helpers = {
        name: callable(getattr(h3m, name, None)) for name in helper_names
    }
    constants = {
        name: getattr(h3m, name, None) is not None
        for name in ("VISUAL_COND_TIMESTEP", "AUDIO_COND_TIMESTEP")
    }
    swap_ok, swap_detail = _dynamic_class_swap_supported()

    ready = bool(
        all(patcher_api.values())
        and all(base_api.values())
        and all(diffusion_api.values())
        and all(helpers.values())
        and all(constants.values())
        and swap_ok
    )
    return {
        "model_patcher_api": patcher_api,
        "minimax_base_api": base_api,
        "minimax_diffusion_api": diffusion_api,
        "h3_helpers": helpers,
        "h3_constants": constants,
        "dynamic_class_swap": swap_ok,
        "dynamic_class_swap_detail": swap_detail,
        "ready": ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    comfy_root = Path(args.comfy_root).resolve()
    if not (comfy_root / "main.py").is_file():
        raise SystemExit("Not a ComfyUI root: %s" % comfy_root)

    os.chdir(comfy_root)
    if str(comfy_root) not in sys.path:
        sys.path.insert(0, str(comfy_root))

    before = _object_snapshot()

    patch_layout = _load_module(
        "_dmh3_master_preflight_patch_layout", ROOT / "patch_layout.py")
    h3_mask = _load_module(
        "_dmh3_master_preflight_h3_mask_compat", ROOT / "h3_mask_compat.py")
    h3_payload = _load_module(
        "_dmh3_master_preflight_h3_mask_payload_compat",
        ROOT / "h3_mask_payload_compat.py",
    )

    minimax_text = importlib.import_module("comfy.text_encoders.minimax")
    h3m = importlib.import_module("comfy.ldm.minimax.model")
    model_base = importlib.import_module("comfy.model_base")
    model_patcher = importlib.import_module("comfy.model_patcher")

    tokenizer_native = bool(
        getattr(minimax_text, "MiniMaxQwenSDTokenizer", None) is not None)
    tokenizer_scoped = _scoped_tokenizer_support(minimax_text)
    tokenizer_mode = (
        "native_pr15808" if tokenizer_native
        else "scoped_companion" if tokenizer_scoped["ready"]
        else "unavailable"
    )

    guides_native = bool(patch_layout.native_guides_available())

    mask_status = h3_mask.capability_status()
    payload_status = h3_payload.capability_status()
    required_mask_native = {
        "process_denoise_mask_native": bool(
            mask_status.get("process_denoise_mask_native")),
        "scale_latent_inpaint_native": bool(
            mask_status.get("scale_latent_inpaint_native")),
        "sampler_mask_blend_native": bool(
            mask_status.get("sampler_mask_blend_native")),
        "mask_engine_native": bool(mask_status.get("mask_engine_native")),
        "mask_helpers_native": bool(mask_status.get("mask_helpers_native")),
        "native_av_mask_payload": bool(
            payload_status.get("native_av_mask_payload")),
    }
    mask_native = all(required_mask_native.values())
    mask_scoped = _scoped_mask_support(h3m, model_base, model_patcher)
    mask_mode = (
        "native_pr15375" if mask_native
        else "scoped_companion" if mask_scoped["ready"]
        else "unavailable"
    )

    after = _object_snapshot()
    shared_core_unchanged = _same_snapshot(before, after)

    missing = []
    if tokenizer_mode == "unavailable":
        missing.append("neither native nor scoped MiniMax special-token support")
    if not guides_native:
        missing.append("native H3 Add Guide / MultiRef / PR #15439")
    if mask_mode == "unavailable":
        missing.append("neither native nor scoped H3 AV-mask support")
    if not shared_core_unchanged:
        missing.append("preflight unexpectedly changed shared ComfyUI objects")

    legacy_path = (
        comfy_root / "custom_nodes" / "ComfyUI-MiniMaxH3-Contex-Loop")
    companion_path = comfy_root / "custom_nodes" / "ComfyUI-MiniMaxH3-MASTER"

    result = {
        "ok": not missing,
        "comfy_root": str(comfy_root),
        "python": sys.executable,
        "guides_native": guides_native,
        "tokenizer": {
            "mode": tokenizer_mode,
            "native_pr15808": tokenizer_native,
            "scoped": tokenizer_scoped,
        },
        "mask": {
            "mode": mask_mode,
            "native_pr15375": required_mask_native,
            "scoped": mask_scoped,
        },
        "shared_core_unchanged": shared_core_unchanged,
        "missing": missing,
        "legacy_pack": _safe_git_head(legacy_path),
        "legacy_path": str(legacy_path),
        "companion_target_present": companion_path.exists(),
        "companion_target": str(companion_path),
        "candidate_source": str(ROOT),
    }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
