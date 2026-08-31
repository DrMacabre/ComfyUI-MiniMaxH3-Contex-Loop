"""Runtime policy for the independent MASTER companion pack.

The companion may alter only its package-local modules or private MODEL/CLIP
objects. Shared ComfyUI H3/tokenizer classes remain read-only. Native H3 Guides
are still mandatory; newer tokenizer/masked-AV features may be supplied by the
explicit MASTER Core Compatibility node.
"""

from __future__ import annotations

import importlib
from typing import Any


def require_native_minimax_tokenizer() -> dict[str, str]:
    """Report native #15808 support or select the private companion fallback.

    The historical compatibility helper rewrites the module-global
    ``comfy.text_encoders.minimax.Qwen3VLSDTokenizer`` alias and is therefore
    forbidden. Older cores are instead handled later by a private CLIP tokenizer
    proxy in ``MASTER — Core Compatibility``.
    """
    try:
        minimax_module = importlib.import_module("comfy.text_encoders.minimax")
    except Exception as exc:
        raise RuntimeError(
            "DrMacabre H3 MASTER requires ComfyUI MiniMax H3 tokenizer support."
        ) from exc

    native = getattr(minimax_module, "MiniMaxQwenSDTokenizer", None)
    if native is not None:
        return {
            "state": "native",
            "message": "ComfyUI owns MiniMax H3 additional special tokens",
        }
    return {
        "state": "scoped_compat",
        "message": (
            "MASTER Core Compatibility will provide MiniMax H3 special tokens "
            "on a private CLIP object"
        ),
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
