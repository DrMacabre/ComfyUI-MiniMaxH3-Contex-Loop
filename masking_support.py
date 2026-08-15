"""Shared capability gate for MiniMax H3 masked-target operations."""

from __future__ import annotations


def require_h3_mask_support(operation: str = "masked target generation"):
    """Prefer native H3 AV masks and install only missing compatibility.

    The node pack already targets the native Add Guide / MultiRef generation
    of MiniMax H3.  Keeping that baseline here prevents a legacy guide wrapper
    and the newer per-row mask engine from being combined accidentally.
    """
    from .patch_layout import native_guides_available

    if not native_guides_available():
        raise RuntimeError(
            "h3_masking: %s requires the native MiniMax H3 Add Guide / "
            "MultiRef core from ComfyUI PR #15439. Update ComfyUI before "
            "using this path." % operation
        )

    from .h3_mask_compat import ensure_h3_mask_compat, is_ready
    from .h3_mask_payload_compat import ensure_av_mask_payload_compat

    ensure_h3_mask_compat()
    ensure_av_mask_payload_compat()

    if not is_ready():
        raise RuntimeError(
            "h3_masking: H3 per-stream AV mask support could not be enabled. "
            "Check the ComfyUI console capability report."
        )
    return True
