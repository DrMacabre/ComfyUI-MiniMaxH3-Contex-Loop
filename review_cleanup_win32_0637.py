"""Narrow Windows sharing-violation guard for Segment Review cache cleanup.

The synchronized Review mux is already complete before chain_nodes deletes older
same-scene ``clip_XXXX.*.review.mp4`` cache files.  On Windows a browser/media
handle can transiently keep one of those stale previews open and ``os.unlink``
then raises WinError 32.  That cleanup exception must not be reclassified as an
AV mux failure and downgrade the newly-created Review to the silent fallback.

This layer changes only that one disposable-cache case.  It does not wrap
``_review_video``, does not change ``retain_previous`` semantics, and does not
swallow errors from temp files, mux targets, checkpoints, segments, or any other
path.
"""

from __future__ import annotations

import os
from typing import Any

BUILD = "FFL_REVIEW_CLEANUP_WIN32_0_6_37_V1"


def _is_stale_review_cache_path(path: Any) -> bool:
    try:
        normalized = os.path.normpath(os.fspath(path))
    except TypeError:
        return False
    filename = os.path.basename(normalized)
    parent = os.path.basename(os.path.dirname(normalized))
    return (
        parent.lower() == "reviews"
        and filename.startswith("clip_")
        and filename.endswith(".review.mp4")
    )


def _is_windows_sharing_violation(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) == 32


def activate_review_cleanup_win32_guard(chain: Any) -> str:
    """Ignore WinError 32 only for deletion of stale final Review cache MP4s."""
    if getattr(chain, "_FFL_REVIEW_CLEANUP_WIN32_BUILD", None) == BUILD:
        return BUILD

    previous_safe_unlink = chain._safe_unlink

    def _safe_unlink_review_cache_guarded(path: Any) -> None:
        try:
            previous_safe_unlink(path)
        except OSError as exc:
            if not (_is_windows_sharing_violation(exc)
                    and _is_stale_review_cache_path(path)):
                raise
            logger = getattr(chain, "_LOG", None)
            if logger is not None:
                logger.warning(
                    "H3 Chain kept a stale Segment Review cache file because "
                    "Windows still has it open; synchronized Review remains "
                    "valid: %s (%s)", path, exc)

    _safe_unlink_review_cache_guarded._ffl_review_cleanup_win32 = True
    chain._safe_unlink = _safe_unlink_review_cache_guarded
    chain._FFL_REVIEW_CLEANUP_WIN32_BUILD = BUILD
    return BUILD
