"""Stable data-contract declarations for the 0.5 workflow UX migration.

This module is deliberately independent from ComfyUI, PyTorch, and the node
implementations.  It freezes the vocabulary and compatibility translations
before runtime nodes start consuming the new contracts.
"""

from __future__ import annotations

from typing import Any


SOURCE_TIMELINE_VERSION = "h3_source_timeline_v1"
AUDIO_POLICY_VERSION = "h3_audio_policy_v1"
TRANSITION_POLICY_VERSION = "h3_transition_policy_v1"
SCENE_DEPENDENCY_VERSION = "h3_scene_dependency_v1"

FINAL_AUDIO_POLICIES = ("generated", "source", "none")
SOURCE_REFERENCE_POLICIES = ("off", "on")
GENERATED_CONTINUITY_POLICIES = ("off", "on")
PAIRED_AUDIO_POLICIES = ("off", "embedded")

LEGACY_AUDIO_MODE_POLICIES = {
    "source_track": {
        "final_audio": "source",
        "source_reference": "on",
        "generated_continuity": "off",
    },
    "generated_audio": {
        "final_audio": "generated",
        "source_reference": "off",
        "generated_continuity": "on",
    },
    "source_plus_timeline": {
        "final_audio": "source",
        "source_reference": "on",
        "generated_continuity": "on",
    },
}

TRANSITION_PRESETS = {
    "cut": {
        "continuation_mode": "guide",
        "context_length": 0,
        "label": "Cut / Independent",
    },
    "guide": {
        "continuation_mode": "guide",
        "context_length": 22,
        "label": "Guided transition",
    },
    "hard_av": {
        "continuation_mode": "masked_av",
        "context_length": 39,
        "label": "Hard continuation",
    },
    "soft_av": {
        "continuation_mode": "feathered_av",
        "context_length": 39,
        "label": "Soft continuation",
    },
}

DEPENDENCY_SCOPES = (
    "global_generation",
    "scene_generation",
    "incoming_boundary",
    "assembly_only",
)


def migrate_legacy_audio_mode(mode: str) -> dict[str, str]:
    """Return a new independent audio-policy record for a 0.4 mode."""
    try:
        policy = LEGACY_AUDIO_MODE_POLICIES[str(mode)]
    except KeyError as exc:
        raise ValueError("Unknown legacy H3 audio mode %r." % mode) from exc
    return {"version": AUDIO_POLICY_VERSION, **policy}


def transition_preset(name: str) -> dict[str, Any]:
    """Return an isolated resolved transition preset."""
    try:
        preset = TRANSITION_PRESETS[str(name)]
    except KeyError as exc:
        raise ValueError("Unknown H3 transition preset %r." % name) from exc
    return {"version": TRANSITION_POLICY_VERSION, "preset": str(name), **preset}


def source_timeline_shape() -> dict[str, Any]:
    """Document the required serializable shape without creating media state."""
    return {
        "version": SOURCE_TIMELINE_VERSION,
        "video": {
            "path": "absolute host path or empty",
            "stream_index": 0,
            "native_fps": "positive rational",
            "start_pts_seconds": "number",
            "duration_seconds": "positive number",
            "frame_count_24fps": "non-negative integer",
        },
        "audio": {
            "kind": "embedded | external_path | deferred_tensor | none",
            "path": "absolute host path or empty",
            "stream_index": "non-negative integer or null",
            "sample_rate": "positive integer or null",
            "duration_seconds": "non-negative number",
        },
        "origin": {
            "skip_native_frames": "non-negative integer",
            "skip_seconds": "non-negative number",
        },
        "fingerprints": {
            "video": "sha256 or empty",
            "audio": "sha256 or empty",
            "timeline": "sha256",
        },
        "recovery": {
            "original_available": "boolean",
            "archived_path": "absolute host path or empty",
            "run_owned_audio_path": "absolute host path or empty",
        },
    }
