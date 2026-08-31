"""Fail-closed runtime policy for the independent MASTER companion pack.

The companion is allowed to mutate its own package modules, but not shared
ComfyUI H3/tokenizer classes.  Older upstream code in this repository contains
compatibility fallbacks that patch global ComfyUI objects; this module replaces
those entry points with native-only guards before the chain runtime imports
them.
"""

from __future__ import annotations

import importlib
from typing import Any


def require_native_minimax_tokenizer() -> dict[str, str]:
    """Require ComfyUI's native MiniMax special-token implementation.

    The legacy pack contains a compatibility helper that rewrites the module-
    global ``comfy.text_encoders.minimax.Qwen3VLSDTokenizer`` alias.  That is
    intentionally forbidden in the companion because the same alias is visible
    to Ethan's installed pack.  Fail closed instead of changing shared core.
    """
    try:
        minimax_module = importlib.import_module("comfy.text_encoders.minimax")
    except Exception as exc:
        raise RuntimeError(
            "DrMacabre H3 MASTER requires ComfyUI MiniMax H3 tokenizer support."
        ) from exc

    native = getattr(minimax_module, "MiniMaxQwenSDTokenizer", None)
    if native is None:
        raise RuntimeError(
            "DrMacabre H3 MASTER requires ComfyUI's native MiniMax H3 special-"
            "token support (PR #15808 or newer). The companion will not install "
            "the legacy process-global tokenizer compatibility patch because it "
            "must remain isolated from Ethan's nodepack. Update ComfyUI and "
            "restart."
        )
    return {
        "state": "native",
        "message": "ComfyUI owns MiniMax H3 additional special tokens",
    }


def install_native_only_guide_policy(nodes_module: Any) -> dict[str, str]:
    """Replace package-local legacy guide fallbacks with native-only guards."""
    native_guides_available = getattr(nodes_module, "native_guides_available", None)
    if not callable(native_guides_available):
        raise RuntimeError("MASTER companion could not inspect native H3 guides.")

    def require_native_guides() -> str:
        if native_guides_available():
            return "native"
        raise RuntimeError(
            "DrMacabre H3 MASTER requires ComfyUI's native H3 Add Guide / "
            "MultiRef implementation (PR #15439 or newer). The companion will "
            "not activate the legacy process-global PackedLayout/Payload "
            "compatibility patches because Ethan's nodepack is loaded in the "
            "same ComfyUI process. Update ComfyUI and restart."
        )

    def claim_native_guides() -> str:
        require_native_guides()
        return "native guides; core-owned; companion does not patch shared H3 runtime"

    def prepare_native_guide_conditioning(conditioning):
        require_native_guides()
        return conditioning

    # These assignments modify only our separately imported ``nodes`` module.
    # ``chain_nodes`` imports the functions afterwards and therefore captures
    # these safe companion-local implementations rather than the legacy ones.
    nodes_module._activate_inline_patches = require_native_guides
    nodes_module._claim_inline_patch_ownership = claim_native_guides
    nodes_module._prepare_native_guide_conditioning = prepare_native_guide_conditioning

    return {
        "state": "native_only",
        "message": "Legacy process-global H3 guide compatibility disabled",
    }


__all__ = [
    "require_native_minimax_tokenizer",
    "install_native_only_guide_policy",
]
