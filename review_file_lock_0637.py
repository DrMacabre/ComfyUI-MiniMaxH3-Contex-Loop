"""Windows-safe Segment Review preview cleanup for Fool for Love 0.6.37.

Segment Review preview MP4s are browser-facing cache artifacts.  On Windows a
currently displayed preview can remain open by the browser/media stack.  The
upstream Review helper creates the new content-addressed preview successfully,
then deletes older previews when ``retain_previous`` is false.  A WinError 32
from that stale-file cleanup must not invalidate the already-valid mux or the
saved segment/checkpoint.

This compatibility layer deliberately changes only stale Review-cache cleanup:
- the existing Review implementation still owns validation and AV muxing;
- exact-final audio trimming remains owned by exact_final_timeline.py;
- old previews are removed best-effort after a successful Review result;
- a locked stale preview is retained and retried naturally on a later Review.
"""

from __future__ import annotations

import os
from typing import Any

BUILD = "FFL_REVIEW_FILE_LOCK_0_6_37_V1"


def _log_retained(chain: Any, path: str, exc: OSError) -> None:
    logger = getattr(chain, "_LOG", None)
    if logger is not None:
        logger.info(
            "H3 Chain retained stale Review preview because Windows still has "
            "the file open: %s (%s)", path, exc)


def _cleanup_stale_review_previews(
        chain: Any, plan: dict[str, Any], segment: dict[str, Any],
        current_video: Any) -> None:
    """Delete stale Review MP4s without making cache cleanup a Review failure."""
    if not isinstance(segment, dict):
        return
    try:
        index = int(segment["index"])
        review_dir = os.path.join(chain._run_dir(plan), "reviews")
    except (KeyError, TypeError, ValueError):
        return

    current_name = ""
    if isinstance(current_video, dict):
        current_name = os.path.basename(str(current_video.get("filename") or ""))
    prefix = "clip_%04d." % index

    try:
        filenames = os.listdir(review_dir)
    except OSError as exc:
        _log_retained(chain, review_dir, exc)
        return

    for filename in filenames:
        if (filename == current_name or not filename.startswith(prefix)
                or not filename.endswith(".review.mp4")):
            continue
        path = os.path.join(review_dir, filename)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # Browser/media handles commonly surface as PermissionError /
            # WinError 32 on Windows.  Review previews are disposable cache, so
            # a stale locked file is safe to retain and must not silence Review.
            _log_retained(chain, path, exc)


def activate_review_file_lock_guard(chain: Any) -> str:
    """Wrap the active Review path while preserving all AV/mux semantics."""
    if getattr(chain, "_FFL_REVIEW_FILE_LOCK_BUILD", None) == BUILD:
        return BUILD

    previous_review_video = chain._review_video

    def _review_video_lock_safe(
            plan: dict[str, Any], segment: dict[str, Any], audio: Any,
            retain_previous: bool = False):
        # Prevent the wrapped implementation from deleting browser-visible
        # previews.  It still performs the exact same validation and muxing.
        result = previous_review_video(
            plan, segment, audio, retain_previous=True)
        if not retain_previous and isinstance(result, tuple) and result:
            _cleanup_stale_review_previews(chain, plan, segment, result[0])
        return result

    chain._review_video = _review_video_lock_safe
    chain._FFL_REVIEW_FILE_LOCK_BUILD = BUILD
    return BUILD
