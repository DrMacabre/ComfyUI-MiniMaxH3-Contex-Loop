"""Expose exact authored frame counts on every Segment Review payload.

Fool for Love 0.6.37 keeps H3's internal raw 17k+5 frame count separate from
its exact delivered timeline length.  The Review backend already stores that
exact value as ``current_requested_frames`` in each pending review, but the
browser-facing ``public`` payload historically exposed only ``raw_frames``.

That omission makes a seed-only Reroll unable to recover the exact authored
length when the connected Plan cannot be resolved by the browser.  This tiny
compatibility layer changes only the pending-review container: whenever a
pending review is stored, it mirrors ``current_requested_frames`` into the
public ``requested_frames`` field.  Existing raw-frame/H3 generation semantics
are untouched.
"""

from __future__ import annotations

from typing import Any

BUILD = "FFL_REVIEW_EXACT_FRAMES_PAYLOAD_0_6_37_V1"
_MARKER = "_ffl_review_exact_frames_payload_0637"


class _ExactReviewPendingDict(dict):
    """Pending-review dict that enriches only the browser-facing payload."""

    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(value, dict):
            public = value.get("public")
            exact = value.get("current_requested_frames")
            if isinstance(public, dict) and exact is not None:
                try:
                    exact_frames = int(exact)
                except (TypeError, ValueError):
                    exact_frames = None
                if exact_frames is not None and exact_frames > 0:
                    public["requested_frames"] = exact_frames
        super().__setitem__(key, value)


def activate_review_exact_frames_payload(chain_module: Any) -> str:
    current = getattr(chain_module, "_PENDING_REVIEWS", None)
    if getattr(current, _MARKER, False):
        return BUILD
    if not isinstance(current, dict):
        raise RuntimeError("H3 Review exact-frame payload patch needs _PENDING_REVIEWS dict.")

    wrapped = _ExactReviewPendingDict()
    setattr(wrapped, _MARKER, True)
    for key, value in current.items():
        wrapped[key] = value
    chain_module._PENDING_REVIEWS = wrapped
    return BUILD
