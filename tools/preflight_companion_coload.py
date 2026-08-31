#!/usr/bin/env python3
"""Disposable same-process co-load probe for Ethan + MASTER companion.

This script is intended to run in a short-lived subprocess with ComfyUI's own
Python.  It imports the installed Ethan package first, snapshots shared ComfyUI
runtime objects, then imports the staged MASTER companion and verifies that:

* MASTER public node IDs do not collide with Ethan's;
* every MASTER public ID is namespaced;
* MASTER restores its temporary PromptServer/GraphBuilder import shims;
* MASTER adds no further mutation to the audited shared H3/tokenizer/sampler
  classes after Ethan has finished importing.

Route registrations themselves are expected package registration effects; URL
collisions surface naturally as import errors.  No model weights are loaded and
no files under the installed Ethan package are written.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NODE_ID_PREFIX = "DrMacabreH3Master_"


def _load_package(name: str, root: Path):
    entry = root / "__init__.py"
    if not entry.is_file():
        raise RuntimeError("Package entrypoint not found: %s" % entry)
    spec = importlib.util.spec_from_file_location(
        name,
        entry,
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create package spec for %s" % root)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _ensure_prompt_server():
    import server

    if getattr(server.PromptServer, "instance", None) is not None:
        return server.PromptServer.instance, None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        instance = server.PromptServer(loop)
    except Exception:
        loop.close()
        raise
    return instance, loop


def _shared_snapshot() -> dict[str, Any]:
    import comfy.ldm.minimax.model as h3m
    import comfy.model_base as model_base
    import comfy.samplers as samplers
    import comfy.text_encoders.minimax as minimax_text
    import comfy_execution.graph_utils as graph_utils
    import server

    packed = getattr(h3m, "PackedLayout", None)
    h3_model = getattr(h3m, "MiniMaxH3Model", None)
    final_layer = getattr(h3m, "FinalLayer", None)
    owner = getattr(model_base, "MiniMaxH3", None)
    sampler = getattr(samplers, "KSamplerX0Inpaint", None)
    return {
        "PromptServer": getattr(server, "PromptServer", None),
        "GraphBuilder": getattr(graph_utils, "GraphBuilder", None),
        "PackedLayout.__init__": getattr(packed, "__init__", None),
        "MiniMaxH3.extra_conds": getattr(owner, "extra_conds", None),
        "MiniMaxH3.scale_latent_inpaint": getattr(
            owner, "scale_latent_inpaint", None),
        "MiniMaxH3Model.forward": getattr(h3_model, "forward", None),
        "MiniMaxH3Model._forward": getattr(h3_model, "_forward", None),
        "FinalLayer.forward": getattr(final_layer, "forward", None),
        "KSamplerX0Inpaint.__call__": getattr(sampler, "__call__", None),
        "Qwen3VLSDTokenizer": getattr(
            minimax_text, "Qwen3VLSDTokenizer", None),
        "MiniMaxQwenSDTokenizer": getattr(
            minimax_text, "MiniMaxQwenSDTokenizer", None),
    }


def _snapshot_diff(before: dict[str, Any], after: dict[str, Any]):
    return [
        key for key, value in before.items()
        if after.get(key) is not value
    ]


def _mapping(module, name: str) -> dict[str, Any]:
    value = getattr(module, name, None)
    if not isinstance(value, dict):
        raise RuntimeError("%s does not export a dict %s" % (module, name))
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", required=True)
    parser.add_argument("--legacy-path", required=True)
    args = parser.parse_args()

    comfy_root = Path(args.comfy_root).resolve()
    legacy_path = Path(args.legacy_path).resolve()
    if not (comfy_root / "main.py").is_file():
        raise SystemExit("Not a ComfyUI root: %s" % comfy_root)
    if not (legacy_path / "__init__.py").is_file():
        raise SystemExit("Legacy package not found: %s" % legacy_path)

    os.chdir(comfy_root)
    if str(comfy_root) not in sys.path:
        sys.path.insert(0, str(comfy_root))

    result: dict[str, Any] = {
        "ok": False,
        "comfy_root": str(comfy_root),
        "legacy_path": str(legacy_path),
        "candidate_source": str(ROOT),
        "phase": "initializing",
    }
    loop = None
    try:
        _instance, loop = _ensure_prompt_server()

        result["phase"] = "legacy_import"
        legacy = _load_package("_dmh3_legacy_coload_probe", legacy_path)
        legacy_nodes = _mapping(legacy, "NODE_CLASS_MAPPINGS")
        after_legacy = _shared_snapshot()

        result["phase"] = "companion_import"
        companion = _load_package("_dmh3_master_coload_probe", ROOT)
        companion_nodes = _mapping(companion, "NODE_CLASS_MAPPINGS")
        after_companion = _shared_snapshot()

        collisions = sorted(set(legacy_nodes) & set(companion_nodes))
        unprefixed = sorted(
            node_id for node_id in companion_nodes
            if not str(node_id).startswith(NODE_ID_PREFIX)
        )
        shared_core_changes = _snapshot_diff(
            after_legacy, after_companion)

        result.update({
            "phase": "complete",
            "legacy_node_count": len(legacy_nodes),
            "companion_node_count": len(companion_nodes),
            "node_id_collisions": collisions,
            "companion_unprefixed_ids": unprefixed,
            "shared_core_changes_after_companion": shared_core_changes,
            "shared_core_unchanged_after_companion": not shared_core_changes,
            "companion_pack_id": getattr(
                companion, "COMPANION_PACK_ID", ""),
            "companion_prefix": getattr(
                companion, "COMPANION_NODE_ID_PREFIX", ""),
            "legacy_web_directory": str(
                getattr(legacy, "WEB_DIRECTORY", "")),
            "companion_web_directory": str(
                getattr(companion, "WEB_DIRECTORY", "")),
        })
        result["ok"] = bool(
            not collisions
            and not unprefixed
            and not shared_core_changes
            and result["companion_prefix"] == NODE_ID_PREFIX
        )
    except Exception as exc:
        result.update({
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        if loop is not None and not loop.is_closed():
            try:
                loop.close()
            except Exception:
                pass

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
