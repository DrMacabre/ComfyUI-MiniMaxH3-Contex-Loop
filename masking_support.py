"""Capability gate for MASTER H3 masked operations.

The companion never installs the historical process-global #15375 wrappers.
Older ComfyUI builds are supported through ``MASTER — Core Compatibility``,
which carries the backport only on its private MODEL clone.
"""

from __future__ import annotations


def require_h3_mask_support(operation: str = "masked target generation"):
    """Require native H3 Guides plus the packaged scoped mask implementation."""
    from .patch_layout import native_guides_available

    if not native_guides_available():
        raise RuntimeError(
            "DrMacabre H3 MASTER: %s requires ComfyUI's native MiniMax H3 Add "
            "Guide / MultiRef core (PR #15439 or newer). The companion will not "
            "install a process-global guide compatibility patch. Update ComfyUI "
            "and restart." % operation
        )

    # Merely importing the companion implementation is read-only. The actual
    # #15375 backport is attached later to the MODEL clone by the explicit
    # MASTER Core Compatibility node; no comfy.* class is modified here.
    from .companion_core_compat import _scoped_mask_model

    if not callable(_scoped_mask_model):
        raise RuntimeError(
            "DrMacabre H3 MASTER: scoped AV-mask compatibility is unavailable."
        )
    return True
