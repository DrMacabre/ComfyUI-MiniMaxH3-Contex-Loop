"""Exact continuation-boundary sanitation for H3 Contex Loop 0.6.37.

Authoritative source audit for 0.6.37 established a crucial asymmetry:

* Loop End ``previous_frames`` are selected from the already delivered/trimmed
  RGB clip and therefore land exactly on the authored edit boundary.
* Loop End ``previous_latent`` is copied from the RAW sampler latent and can
  extend beyond that boundary whenever ``tail_trim_frames > 0``.
* Segment Save intentionally persists that RAW latent as an immutable render /
  redecode artifact.  It must NOT be destructively cropped on disk.

This layer sanitizes only the continuation state crossing scene boundaries:

* LIVE recursion: padded predecessor => ``previous_latent = None`` while
  delivered ``previous_frames`` are preserved verbatim.
* DISK resume: padded last segment => restore exact RGB frames but never expose
  the RAW checkpoint latent as hidden next-scene continuation state.
* grid-aligned predecessor (tail == 0) keeps the RAW latent available.

The existing Exact Final Timeline context-application policy remains the owner
of mode-specific fallback behavior (Masked AV => delivered RGB context,
latent_guide => RGB Guide, generated-audio latent continuity => fail closed).
This module deliberately does not alter checkpoint tensor files or capability
broker / allowlist policy.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

_SENTINEL = "_fool_for_love_exact_continuation_overlay_v1"


class ExactContinuationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContinuationReport:
    activated: bool
    patched: tuple[str, ...]
    deferred: tuple[str, ...]


def _tail_value(value: Any, *, where: str) -> int:
    try:
        tail = int(value or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExactContinuationError(f"invalid tail_trim_frames in {where}: {value!r}") from exc
    if tail < 0:
        raise ExactContinuationError(f"negative tail_trim_frames in {where}: {tail}")
    return tail


def _sanitize_live_next_state(next_state: Any) -> dict[str, Any]:
    """Copy and sanitize the state handed from scene N to scene N+1.

    This is intentionally the same contract as the externally verified 0.6.37
    correction: use ``state['index'] - 1`` to identify the predecessor in the
    normalized plan; a positive predecessor tail makes the RAW sampler latent
    timeline-inexact.  RGB ``previous_frames`` are never touched.
    """
    if not isinstance(next_state, dict):
        raise ExactContinuationError("Loop End next_state is not a dict")

    state = dict(next_state)
    try:
        index = int(state.get("index", 1))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExactContinuationError("Loop End next_state index is not an integer") from exc
    previous_index = index - 1
    plan = state.get("plan")

    if isinstance(plan, dict) and 1 <= previous_index <= len(plan.get("shots", [])):
        shot = plan["shots"][previous_index - 1]
        if not isinstance(shot, dict):
            raise ExactContinuationError(
                f"Loop End predecessor shot {previous_index} is not a dict"
            )
        tail = _tail_value(
            shot.get("tail_trim_frames", 0),
            where=f"live predecessor scene {previous_index}",
        )
        exact = tail == 0
        state["previous_latent_timeline_exact"] = exact
        if not exact:
            # RAW H3 sampler latent extends beyond the authored edit boundary.
            # Never expose it as hidden continuation state.
            state["previous_latent"] = None

    return state


def _sanitize_resume_state(state_value: Any) -> dict[str, Any]:
    """Copy and sanitize disk-resume continuation state.

    Checkpoint RAW latent remains on disk untouched.  Only the in-memory resume
    state is stripped when the last completed segment had an H3-only tail.
    """
    if not isinstance(state_value, dict):
        raise ExactContinuationError("_initial_state returned a non-dict state")

    state = dict(state_value)
    segments = state.get("segments")
    if isinstance(segments, list) and segments:
        last = segments[-1]
        if not isinstance(last, dict):
            raise ExactContinuationError("last resume segment is not a dict")
        tail = _tail_value(last.get("tail_trim_frames", 0), where="resume last segment")
        exact = tail == 0
        state["previous_latent_timeline_exact"] = exact
        if not exact:
            # Checkpoint keeps the RAW latent as an immutable render artifact,
            # but resume must not turn its padded tail into next-scene context.
            state["previous_latent"] = None
    else:
        state["previous_latent_timeline_exact"] = True
    return state


def _signature_exact(fn: Callable[..., Any], expected_prefix: tuple[str, ...], *, label: str):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ExactContinuationError(f"cannot inspect {label}") from exc
    names = tuple(sig.parameters)
    if names[: len(expected_prefix)] != expected_prefix:
        raise ExactContinuationError(
            f"refusing continuation overlay: {label} signature {names!r} does not begin "
            f"with {expected_prefix!r}"
        )
    return sig


def _wrap_recurse(original: Callable[..., Any]):
    if getattr(original, _SENTINEL, False):
        return original

    @wraps(original)
    def _recurse_exact(self, flow, next_state, dynprompt, unique_id):
        state = _sanitize_live_next_state(next_state)
        return original(self, flow, state, dynprompt, unique_id)

    setattr(_recurse_exact, _SENTINEL, True)
    _recurse_exact._exact_timeline_original = original
    return _recurse_exact


def _wrap_initial_state(original: Callable[..., Any]):
    if getattr(original, _SENTINEL, False):
        return original

    @wraps(original)
    def _initial_state_exact(*args, **kwargs):
        state = original(*args, **kwargs)
        return _sanitize_resume_state(state)

    setattr(_initial_state_exact, _SENTINEL, True)
    _initial_state_exact._exact_timeline_original = original
    return _initial_state_exact


def generated_audio_latent_continuity_guard(state: dict[str, Any]) -> None:
    """Fail closed if generated-audio continuity would consume padded RAW latent.

    The real mode-specific context application stays in its existing owner. This
    helper exists so that the invariant is independently regression-tested by
    the transactional layer: a state explicitly marked timeline-inexact may
    never be accepted as latent AV continuity.
    """
    if not isinstance(state, dict):
        raise ExactContinuationError("context state is not a dict")
    if state.get("previous_latent_timeline_exact") is False:
        raise ExactContinuationError(
            "generated-audio latent continuity refused: predecessor RAW latent "
            "extends beyond the authored edit boundary"
        )


def preflight_exact_continuation(chain_module: Any) -> tuple[str, ...]:
    loop_cls = getattr(chain_module, "MiniMaxH3ChainLoopEnd", None)
    if not isinstance(loop_cls, type):
        raise ExactContinuationError("MiniMaxH3ChainLoopEnd is missing")
    recurse = getattr(loop_cls, "_recurse", None)
    if not callable(recurse):
        raise ExactContinuationError("MiniMaxH3ChainLoopEnd._recurse is missing")
    _signature_exact(
        recurse,
        ("self", "flow", "next_state", "dynprompt", "unique_id"),
        label="MiniMaxH3ChainLoopEnd._recurse",
    )

    initial_state = getattr(chain_module, "_initial_state", None)
    if not callable(initial_state):
        raise ExactContinuationError("upstream _initial_state is missing")
    try:
        inspect.signature(initial_state)
    except (TypeError, ValueError) as exc:
        raise ExactContinuationError("cannot inspect upstream _initial_state") from exc

    return (
        "MiniMaxH3ChainLoopEnd._recurse",
        "_initial_state",
    )


def activate_exact_continuation(chain_module: Any) -> ContinuationReport:
    preflight_exact_continuation(chain_module)
    existing = getattr(chain_module, _SENTINEL, None)
    if isinstance(existing, ContinuationReport):
        return existing

    loop_cls = chain_module.MiniMaxH3ChainLoopEnd
    loop_cls._recurse = _wrap_recurse(loop_cls._recurse)
    chain_module._initial_state = _wrap_initial_state(chain_module._initial_state)

    report = ContinuationReport(
        activated=True,
        patched=(
            "MiniMaxH3ChainLoopEnd._recurse",
            "_initial_state",
        ),
        deferred=(
            "Review backend/frontend",
        ),
    )
    setattr(chain_module, _SENTINEL, report)
    return report
