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
PREFLIGHT_VERSION = "h3_preflight_v1"

FINAL_AUDIO_POLICIES = ("generated", "source", "none")
SOURCE_REFERENCE_POLICIES = ("off", "on")
GENERATED_CONTINUITY_POLICIES = ("off", "on")
PAIRED_AUDIO_POLICIES = ("off", "embedded")
CONTEXT_SPATIAL_PROXY_MODES = ("off", "rgb_5_6", "latent_5_6")
CONTINUATION_POLICIES = (
    "guide", "tone_carry_guide", "latent_guide", "tapered_guide",
    "masked_av", "tapered_av", "feathered_av", "audio_feathered_av")
TRANSITION_CONTEXT_LENGTHS = (
    0, 1, 5, 22, 39, 56, 73, 90, 107, 124,
    141, 158, 175, 192, 209, 226, 243,
)
AV_TRANSITION_CONTEXT_LENGTHS = (39, 90, 141, 192, 243)

# Experimental one-shot latent-context recipe adapted from beijinren's
# ComfyUI-H3-Context-Noise. Keep every generation-significant value in the
# scene dependency contract so changing the recipe cannot silently resume a
# scene rendered with an older taper.
DETAIL_AV_RECIPE = {
    "version": "h3_detail_av_latent_taper_v2",
    "context_frames": 39,
    "video_steps": 12,
    "alpha": 0.30,
    "alpha_end": 0.00,
    "ramp_steps": 4,
    "noise_scale": "match_latent_std",
    "seed_xor": 0xD37A11,
}

# Boundary-only low-grid experiment reconstructed from a mixed-resolution
# chain: a 1376x768 target carried a predecessor generated at 1152x640.  The
# Guide recipe spatially reduces the complete saved predecessor video latent,
# decodes that disposable 5/6 latent at its native 1152x640 canvas, then lets
# Motion Context restore only the requested RGB tail to the target canvas.
# This deliberately keeps the nonlinear low-grid VAE decode that a simple RGB
# resize cannot reproduce.  AV keeps its cheaper latent down/up prefix filter.
# Generated scenes and checkpoint/assembly artifacts keep the Plan canvas.
CONTEXT_SPATIAL_PROXY_RECIPE = {
    "version": "h3_context_spatial_proxy_v2",
    "scale_numerator": 5,
    "scale_denominator": 6,
    "pixel_alignment": 32,
    "guide_source": "saved_predecessor_video_latent",
    "guide_latent_downsample": "area",
    "guide_decode": "full_low_grid_stream",
    "guide_tail": "delivered_frames",
    "guide_restore": "motion_context_lanczos",
    "latent_downsample": "area",
    "latent_restore": "bilinear",
    "preserve_latent_statistics": False,
}

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
    "tone_guide": {
        "continuation_mode": "tone_carry_guide",
        "context_length": 22,
        "label": "Tone-carry guided transition",
    },
    "latent_guide": {
        "continuation_mode": "latent_guide",
        "context_length": 22,
        "label": "Latent-guided transition",
    },
    "detail_guide": {
        "continuation_mode": "tapered_guide",
        "context_length": 22,
        "label": "Detail-preserving guided transition",
    },
    "detail_av": {
        "continuation_mode": "tapered_av",
        "context_length": 39,
        "label": "Detail-preserving AV continuation (experimental)",
    },
    "hard_av": {
        "continuation_mode": "masked_av",
        "context_length": 39,
        "label": "Hard continuation",
    },
    "soft_av": {
        "continuation_mode": "audio_feathered_av",
        "context_length": 39,
        "label": "Soft continuation (hard picture, soft audio)",
    },
    "audio_feather_av": {
        "continuation_mode": "audio_feathered_av",
        "context_length": 39,
        "label": "Audio-feathered continuation (legacy alias)",
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


def migrate_continuation_mode(mode: str) -> str:
    """Map retired experimental implementations to a supported mode."""
    value = str(mode)
    if value == "feathered_av_rgb":
        return "feathered_av"
    return value


def audio_policy(
    final_audio: str,
    source_reference: str,
    generated_continuity: str,
) -> dict[str, str]:
    """Validate and return one independent 0.5 audio-policy record."""
    final = str(final_audio)
    source = str(source_reference)
    continuity = str(generated_continuity)
    if final not in FINAL_AUDIO_POLICIES:
        raise ValueError("Unknown H3 final-audio policy %r." % final_audio)
    if source not in SOURCE_REFERENCE_POLICIES:
        raise ValueError(
            "Unknown H3 source-reference policy %r." % source_reference)
    if continuity not in GENERATED_CONTINUITY_POLICIES:
        raise ValueError(
            "Unknown H3 generated-continuity policy %r." %
            generated_continuity)
    return {
        "version": AUDIO_POLICY_VERSION,
        "final_audio": final,
        "source_reference": source,
        "generated_continuity": continuity,
    }


def paired_audio_policy(value: str | bool) -> str:
    """Normalize a reference-local paired-audio choice or legacy boolean."""
    if isinstance(value, bool):
        return "embedded" if value else "off"
    normalized = str(value).strip().lower()
    if normalized not in PAIRED_AUDIO_POLICIES:
        raise ValueError("Unknown H3 paired-audio policy %r." % value)
    return normalized


def transition_preset(name: str) -> dict[str, Any]:
    """Return an isolated resolved transition preset."""
    try:
        preset = TRANSITION_PRESETS[str(name)]
    except KeyError as exc:
        raise ValueError("Unknown H3 transition preset %r." % name) from exc
    return {"version": TRANSITION_POLICY_VERSION, "preset": str(name), **preset}


def transition_policy(
    preset: str,
    *,
    expert_override: bool = False,
    continuation_mode: str | None = None,
    context_length: int | None = None,
) -> dict[str, Any]:
    """Resolve a semantic preset and optional explicit low-level override."""
    resolved = transition_preset(preset)
    expert = bool(expert_override)
    if expert:
        mode = migrate_continuation_mode(continuation_mode)
        if mode not in CONTINUATION_POLICIES:
            raise ValueError(
                "Unknown H3 continuation implementation %r." %
                continuation_mode)
        try:
            context = int(context_length)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "H3 transition context must be 0 or one of %s." %
                (TRANSITION_CONTEXT_LENGTHS,)) from exc
        if context not in TRANSITION_CONTEXT_LENGTHS:
            raise ValueError(
                "H3 transition context must be 0 or one of %s." %
                (TRANSITION_CONTEXT_LENGTHS,))
        if mode == "latent_guide" and 0 < context < 5:
            raise ValueError(
                "H3 Latent Guide requires at least 5 context frames.")
        if (mode in (
                "masked_av", "tapered_av", "feathered_av",
                "audio_feathered_av"
        ) and context > 0 and context not in AV_TRANSITION_CONTEXT_LENGTHS):
            raise ValueError(
                "H3 AV transition implementations require an exact shared "
                "video/audio boundary: 39, 90, 141, 192, or 243 context "
                "frames (or 0 to disable continuation).")
        if (mode == "tapered_av" and context not in (
                0, int(DETAIL_AV_RECIPE["context_frames"]))):
            raise ValueError(
                "H3 Detail AV currently requires exactly 39 context frames "
                "(or 0 to disable continuation).")
        resolved["continuation_mode"] = mode
        resolved["context_length"] = context
    resolved["expert_override"] = expert
    return resolved


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


def scene_dependency_shape() -> dict[str, Any]:
    """Document the versioned, four-scope checkpoint dependency record."""
    return {
        "version": SCENE_DEPENDENCY_VERSION,
        "scene": "one-based integer",
        "scopes": {scope: "JSON-safe field map" for scope in DEPENDENCY_SCOPES},
        "fingerprints": {scope: "sha256" for scope in DEPENDENCY_SCOPES},
        "generation_hash": "sha256 of scopes except assembly_only",
    }
