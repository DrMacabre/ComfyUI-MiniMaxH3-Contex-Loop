"""Shared native-only capability gate for MASTER H3 masked operations."""

from __future__ import annotations


def require_h3_mask_support(operation: str = "masked target generation"):
    """Require native ComfyUI H3 AV-mask support without patching shared core.

    Ethan's legacy nodepack and the independent MASTER companion are loaded in
    one ComfyUI process. The companion therefore never installs the historical
    PR #15375 compatibility wrappers into shared ``comfy.*`` classes. Native
    core support is mandatory for masked MASTER paths; missing capabilities fail
    closed with an update instruction.
    """
    from .patch_layout import native_guides_available

    if not native_guides_available():
        raise RuntimeError(
            "DrMacabre H3 MASTER: %s requires ComfyUI's native MiniMax H3 Add "
            "Guide / MultiRef core (PR #15439 or newer). The companion will not "
            "install a process-global compatibility patch. Update ComfyUI and "
            "restart." % operation
        )

    from .h3_mask_compat import capability_status as engine_capability_status
    from .h3_mask_payload_compat import capability_status as payload_capability_status

    engine = engine_capability_status()
    payload = payload_capability_status()

    required_engine = {
        "process_denoise_mask_native": bool(
            engine.get("process_denoise_mask_native")),
        "scale_latent_inpaint_native": bool(
            engine.get("scale_latent_inpaint_native")),
        "sampler_mask_blend_native": bool(
            engine.get("sampler_mask_blend_native")),
        "mask_engine_native": bool(engine.get("mask_engine_native")),
        "mask_helpers_native": bool(engine.get("mask_helpers_native")),
    }
    missing = [name for name, available in required_engine.items() if not available]
    if not bool(payload.get("native_av_mask_payload")):
        missing.append("native_av_mask_payload")

    if missing:
        raise RuntimeError(
            "DrMacabre H3 MASTER: %s requires native ComfyUI H3 AV-mask support "
            "(PR #15375 final merged implementation). Missing native capability: "
            "%s. The companion deliberately refuses the legacy process-global "
            "mask compatibility wrappers so it cannot alter Ethan's runtime. "
            "Update ComfyUI and restart."
            % (operation, ", ".join(missing))
        )

    return True
