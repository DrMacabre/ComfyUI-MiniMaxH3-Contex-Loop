"""Lazy AV denoise-mask payload compatibility for H3 masked continuation.

Normal guide continuation never installs this wrapper. Native ComfyUI support
always wins; the wrapper only adds the two AV mask conditions when the running
MiniMaxH3 implementation does not already expose PR #15375-equivalent payload
handling.

Adapted from seitanism/ComfyUI-H3-Motion-Context-MultiRef (GPL-3.0).
"""

from __future__ import annotations

import functools
import inspect
import logging
import types

import torch

import comfy.conds
import comfy.model_base as model_base
import comfy.utils as utils


_LOG = logging.getLogger("minimax_h3_context_loop.masked_prefix")
# Version 4 matches the final merged #15375 helper-based payload path. Version
# 3 predates merge commit c676536 and rounds before token-grid pooling; it must
# not wrap or overwrite the native merged result.
_MARKER = "_h3_existing_video_av_mask_payload_compat_v4"
_LEGACY_MARKERS = (
    "_h3_existing_video_av_mask_payload_compat_v2",
    "_h3_existing_video_av_mask_payload_compat_v3",
)
# Kept as an internal compatibility alias for focused third-party tests that
# marked the immediately preceding wrapper directly.
_LEGACY_MARKER = _LEGACY_MARKERS[-1]


def _walk_wrapped(fn):
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        yield fn
        fn = getattr(fn, "__wrapped__", None)


def _is_ours(fn):
    code = getattr(fn, "__code__", None)
    return bool(
        getattr(fn, _MARKER, False)
        and code is not None
        and code.co_name == "wrapper"
        and code.co_filename == __file__
    )


def _is_compatible_wrapper(fn):
    code = getattr(fn, "__code__", None)
    return bool(
        getattr(fn, _MARKER, False)
        and code is not None
        and code.co_name == "wrapper"
    )


def _is_legacy_wrapper(fn):
    code = getattr(fn, "__code__", None)
    return bool(
        any(getattr(fn, marker, False) for marker in _LEGACY_MARKERS)
        and code is not None
        and code.co_name == "wrapper"
    )


def _signature_has(fn, *names):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return all(name in params for name in names)


def _code_strings(code):
    """Yield strings/names from a function and nested code objects."""
    if not isinstance(code, types.CodeType):
        return
    yield from code.co_names

    def walk_const(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, types.CodeType):
            yield from _code_strings(value)
        elif isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                yield from walk_const(item)

    for value in code.co_consts:
        yield from walk_const(value)


def _function_mentions_native_payload(fn):
    for item in _walk_wrapped(fn):
        if _is_ours(item) or _is_legacy_wrapper(item):
            continue
        strings = set(_code_strings(getattr(item, "__code__", None)) or ())
        if "denoise_mask" in strings and "audio_denoise_mask" in strings:
            return True
    return False


def _function_calls_native_helper(fn):
    for item in _walk_wrapped(fn):
        if _is_ours(item) or _is_legacy_wrapper(item):
            continue
        strings = set(_code_strings(getattr(item, "__code__", None)) or ())
        if "denoise_mask" in strings and "_denoise_mask_conds" in strings:
            return True
    return False


def _native_h3_mask_hooks(cls, fn):
    if cls is None:
        return False
    scale = cls.__dict__.get("scale_latent_inpaint")
    merged_helpers = all(callable(cls.__dict__.get(name)) for name in (
        "_pool_masks_to_token_grid",
        "_token_grid_masks",
        "_denoise_mask_values",
        "_denoise_mask_conds",
    ))
    merged_path = bool(
        merged_helpers
        and _function_calls_native_helper(fn)
    )
    return bool(
        merged_path
        and callable(scale)
        and _signature_has(scale, "x", "denoise_mask")
    )


def _native_av_mask_payload(cls, fn):
    return bool(fn and _native_h3_mask_hooks(cls, fn))


def capability_status():
    cls = getattr(model_base, "MiniMaxH3", None)
    fn = getattr(cls, "extra_conds", None) if cls is not None else None
    direct = bool(fn and _function_mentions_native_payload(fn))
    native_hooks = _native_h3_mask_hooks(cls, fn)
    native = bool(fn and native_hooks)
    return {
        "available": fn is not None,
        "native_av_mask_payload": native,
        "native_payload_direct": direct,
        "native_h3_mask_hooks": native_hooks,
        "wrapper_present": bool(
            fn and any(_is_compatible_wrapper(item)
                       for item in _walk_wrapped(fn))),
    }


def _add_av_mask_conditions(owner, out, kwargs):
    if not isinstance(out, dict):
        return
    denoise_mask = kwargs.get("denoise_mask")
    latent_shapes = kwargs.get("latent_shapes")
    if denoise_mask is None or latent_shapes is None or len(latent_shapes) < 2:
        return

    native_helper = getattr(owner, "_denoise_mask_conds", None)
    if callable(native_helper):
        out.update(native_helper(denoise_mask, latent_shapes))
        return

    # Last-resort compatibility when this module is used without the engine
    # gate. The normal pack path installs the exact helper set first. Ceil to
    # the merged 8-bit token strength rather than the pre-merge nearest value.
    masks = utils.unpack_latents(denoise_mask, latent_shapes)
    if len(masks) < 2:
        return
    pool = getattr(owner, "_pool_masks_to_token_grid", None)
    if callable(pool):
        masks = pool(masks)
    masks = [torch.ceil(mask * 256.0) / 256.0 for mask in masks]
    if torch.amin(masks[0]).item() < 1.0 - 1e-3:
        out["denoise_mask"] = comfy.conds.CONDRegular(
            masks[0][:1, :1].clone())
    if torch.amin(masks[1]).item() < 1.0 - 1e-3:
        out["audio_denoise_mask"] = comfy.conds.CONDRegular(
            masks[1][:1].amax(dim=1, keepdim=True))


def _make_wrapper(base):
    @functools.wraps(base, updated=())
    def wrapper(self, **kwargs):
        out = base(self, **kwargs)
        _add_av_mask_conditions(self, out, kwargs)
        return out

    setattr(wrapper, _MARKER, True)
    return wrapper


def ensure_av_mask_payload_compat():
    cls = getattr(model_base, "MiniMaxH3", None)
    if cls is None or not hasattr(cls, "extra_conds"):
        raise RuntimeError(
            "h3_masked_prefix: MiniMaxH3.extra_conds not found.")
    current = cls.extra_conds
    original = current
    # Strip only obsolete top-level versions before probing native support.
    # Otherwise their wrapped native function can make the chain look healthy
    # while the outer v3 wrapper overwrites the merged token-grid conditions.
    while _is_legacy_wrapper(current) and callable(
            getattr(current, "__wrapped__", None)):
        current = current.__wrapped__
    if current is not original:
        cls.extra_conds = current
    if _native_av_mask_payload(cls, current):
        return True
    if any(_is_compatible_wrapper(item) for item in _walk_wrapped(current)):
        return True
    # Unknown third-party wrappers remain in the chain; the v4 layer only
    # replaces the two mask conditions after their base result is produced.
    cls.extra_conds = _make_wrapper(current)
    _LOG.info(
        "h3_masked_prefix: PR #15375 AV-mask payload compatibility enabled")
    return True
