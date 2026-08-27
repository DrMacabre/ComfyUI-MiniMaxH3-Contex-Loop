"""Focused package-integration regression for FFL 0.6.37 continuation sanitation.

This deliberately emulates the already-installed monolithic exact timeline
wrappers: they mark previous_latent_timeline_exact but historically left the
RAW latent exposed.  The new continuation overlay must clear only the in-memory
latent for padded predecessors while preserving delivered RGB context.
"""
from __future__ import annotations

import copy
import types

from exact_final_timeline_continuation_0637 import (
    ExactContinuationError,
    activate_exact_continuation,
    generated_audio_latent_continuity_guard,
    preflight_exact_continuation,
)


def padded_shot():
    return {
        "requested_frames": 57,
        "raw_frames": 107,
        "delivered_frames": 57,
        "head_trim_frames": 39,
        "tail_trim_frames": 11,
    }


def aligned_shot():
    return {
        "requested_frames": 68,
        "raw_frames": 107,
        "delivered_frames": 68,
        "head_trim_frames": 39,
        "tail_trim_frames": 0,
    }


class ExistingMonolithicLoopEnd:
    captured = None

    def _recurse(self, flow, next_state, dynprompt, unique_id):
        # Existing monolithic 0.6.37 behavior: mark exactness, but do not
        # reintroduce or otherwise mutate previous_latent.
        state = next_state
        index = int(state.get("index", 1))
        previous_index = index - 1
        plan = state.get("plan")
        if isinstance(plan, dict) and 1 <= previous_index <= len(plan.get("shots", [])):
            tail = int(plan["shots"][previous_index - 1].get("tail_trim_frames", 0))
            state["previous_latent_timeline_exact"] = tail == 0
        type(self).captured = state
        return state


def make_existing_initial_state(holder):
    def _initial_state(*args, **kwargs):
        state = copy.deepcopy(holder["state"])
        segments = state.get("segments")
        if isinstance(segments, list) and segments:
            state["previous_latent_timeline_exact"] = (
                int(segments[-1].get("tail_trim_frames", 0)) == 0)
        else:
            state["previous_latent_timeline_exact"] = True
        return state
    return _initial_state


def module_for(initial_state):
    return types.SimpleNamespace(
        MiniMaxH3ChainLoopEnd=type(
            "LoopEndClone", (ExistingMonolithicLoopEnd,), {}),
        _initial_state=initial_state,
    )


frames = [f"rgb-{i}" for i in range(39)]
raw_latent = {"samples": "RAW-LATENT-WITH-H3-TAIL"}
holder = {
    "state": {
        "segments": [],
        "previous_frames": list(frames),
        "previous_latent": raw_latent,
    }
}
mod = module_for(make_existing_initial_state(holder))
assert preflight_exact_continuation(mod) == (
    "MiniMaxH3ChainLoopEnd._recurse", "_initial_state")
report = activate_exact_continuation(mod)
assert report.activated

# LIVE padded predecessor: copy caller state, preserve RGB, clear RAW latent.
live = {
    "index": 2,
    "plan": {"shots": [padded_shot(), {"requested_frames": 1}]},
    "previous_frames": list(frames),
    "previous_latent": raw_latent,
}
mod.MiniMaxH3ChainLoopEnd()._recurse("flow", live, "dyn", "uid")
sent = mod.MiniMaxH3ChainLoopEnd.captured
assert sent is not live
assert sent["previous_frames"] == frames
assert sent["previous_latent"] is None
assert sent["previous_latent_timeline_exact"] is False
assert live["previous_latent"] is raw_latent

# RESUME padded predecessor: disk representation stays untouched; returned
# continuation state loses only the in-memory RAW latent.
checkpoint_latent = {"samples": "IMMUTABLE-CHECKPOINT-RAW"}
holder["state"] = {
    "segments": [{"id": "s1", "tail_trim_frames": 11}],
    "previous_frames": list(frames),
    "previous_latent": checkpoint_latent,
}
resumed = mod._initial_state()
assert resumed["previous_frames"] == frames
assert resumed["previous_latent"] is None
assert resumed["previous_latent_timeline_exact"] is False
assert holder["state"]["previous_latent"] is checkpoint_latent

# Grid-aligned predecessor remains latent-capable LIVE and RESUME.
aligned_latent = {"samples": "GRID-ALIGNED-RAW"}
aligned_live = {
    "index": 2,
    "plan": {"shots": [aligned_shot(), {"requested_frames": 1}]},
    "previous_frames": list(frames),
    "previous_latent": aligned_latent,
}
mod.MiniMaxH3ChainLoopEnd()._recurse("flow", aligned_live, "dyn", "uid")
aligned_sent = mod.MiniMaxH3ChainLoopEnd.captured
assert aligned_sent["previous_latent"] is aligned_latent
assert aligned_sent["previous_latent_timeline_exact"] is True

holder["state"] = {
    "segments": [{"id": "s1", "tail_trim_frames": 0}],
    "previous_frames": list(frames),
    "previous_latent": aligned_latent,
}
aligned_resume = mod._initial_state()
assert aligned_resume["previous_latent"] == aligned_latent
assert aligned_resume["previous_latent_timeline_exact"] is True

# Generated-audio latent continuity remains fail-closed for padded state.
try:
    generated_audio_latent_continuity_guard(sent)
except ExactContinuationError as exc:
    assert "generated-audio latent continuity refused" in str(exc)
else:
    raise AssertionError("padded predecessor must fail closed")
generated_audio_latent_continuity_guard(aligned_sent)

# Signature drift must fail before mutation.
class DriftLoopEnd:
    def _recurse(self, flow, wrong_state, dynprompt, unique_id):
        return wrong_state

drift = types.SimpleNamespace(
    MiniMaxH3ChainLoopEnd=DriftLoopEnd,
    _initial_state=lambda: {},
)
try:
    activate_exact_continuation(drift)
except ExactContinuationError as exc:
    assert "signature" in str(exc)
else:
    raise AssertionError("signature drift must fail closed")

print("PASS package integration continuation sanitation 0.6.37")
