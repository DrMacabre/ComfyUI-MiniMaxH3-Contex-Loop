#!/usr/bin/env python3
"""Read-only installed-runtime preflight for the MASTER companion nodepack.

Run this with ComfyUI's own Python interpreter and pass --comfy-root.  It
checks the exact native core capabilities the companion requires before the
pack is placed in custom_nodes.  The script deliberately imports the companion
compatibility modules only by file path and calls their read-only capability
probes; it never imports the companion package entrypoint and never installs a
compatibility patch.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
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
    spec.loader.exec_module(module)
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
        "sampler_call": getattr(sampler, "__call__", None),
        "tokenizer_alias": getattr(minimax_text, "Qwen3VLSDTokenizer", None),
    }


def _same_snapshot(before, after):
    return all(after.get(key) is value for key, value in before.items())


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
    tokenizer_native = bool(
        getattr(minimax_text, "MiniMaxQwenSDTokenizer", None) is not None)
    guides_native = bool(patch_layout.native_guides_available())
    mask_status = h3_mask.capability_status()
    payload_status = h3_payload.capability_status()

    required_mask = {
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

    after = _object_snapshot()
    shared_core_unchanged = _same_snapshot(before, after)

    missing = []
    if not tokenizer_native:
        missing.append("native MiniMax special tokens / PR #15808")
    if not guides_native:
        missing.append("native H3 Add Guide / MultiRef / PR #15439")
    for name, ok in required_mask.items():
        if not ok:
            missing.append(name)
    if not shared_core_unchanged:
        missing.append("preflight unexpectedly changed shared ComfyUI objects")

    legacy_path = (
        comfy_root / "custom_nodes" / "ComfyUI-MiniMaxH3-Contex-Loop")
    companion_path = comfy_root / "custom_nodes" / "ComfyUI-MiniMaxH3-MASTER"

    result = {
        "ok": not missing,
        "comfy_root": str(comfy_root),
        "python": sys.executable,
        "tokenizer_native": tokenizer_native,
        "guides_native": guides_native,
        "mask_native": required_mask,
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
