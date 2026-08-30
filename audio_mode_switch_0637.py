"""Visible two-mode audio control for the 0.6.37 H3 chain workflow.

The user-facing switch owns the Plan audio intent while a downstream lazy mux
selects the scene-local decoded soundtrack that is saved/reviewed.  This keeps
source-track and generated-audio workflows on the same graph without asking the
user to rewire nodes.
"""

from __future__ import annotations

from typing import Any

from .contracts_v05 import chain_policy as _contract_chain_policy


CHAIN_POLICY_TYPE = "H3_CHAIN_POLICY"
AUDIO_MODE_CONTROL_TYPE = "H3_AUDIO_MODE_CONTROL"
AUDIO_MODE_CONTROL_VERSION = "h3_audio_mode_control_v1"
AUDIO_MODES = ("source_track", "generated_audio")


def _mode_from_control(value: Any) -> str:
    if not isinstance(value, dict):
        raise ValueError("H3 Audio Mode control is missing or invalid.")
    if value.get("version") != AUDIO_MODE_CONTROL_VERSION:
        raise ValueError("H3 Audio Mode control version is missing or obsolete.")
    mode = str(value.get("mode") or "").strip().lower()
    if mode not in AUDIO_MODES:
        raise ValueError("Unknown H3 Audio Mode %r." % value.get("mode"))
    return mode


class MiniMaxH3AudioModeSwitch:
    """One visible switch for source-track versus H3-generated audio."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_mode": (list(AUDIO_MODES), {
                    "default": "source_track",
                    "tooltip": (
                        "source_track keeps the exact Source Timeline as the final "
                        "soundtrack and uses it as scene audio reference. "
                        "generated_audio ignores the source track for generation, "
                        "carries H3 generated audio between scenes, and assembles "
                        "the generated soundtrack."
                    ),
                }),
            },
        }

    RETURN_TYPES = (CHAIN_POLICY_TYPE, AUDIO_MODE_CONTROL_TYPE, "STRING")
    RETURN_NAMES = ("chain_policy", "mode_control", "status")
    OUTPUT_TOOLTIPS = (
        "Connect to Chain Plan chain_policy.",
        "Connect to the matching Auto Audio Router downstream.",
        "Resolved audio-mode summary.",
    )
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/policies"
    DESCRIPTION = (
        "Visible project-level audio switch. Source Track preserves the exact "
        "source soundtrack; Generated Audio saves and assembles H3's decoded "
        "audio. Scene transition choices remain controlled by the Plan."
    )

    def build(self, audio_mode="source_track"):
        mode = str(audio_mode or "").strip().lower()
        if mode not in AUDIO_MODES:
            raise ValueError("Unknown H3 Audio Mode %r." % audio_mode)

        if mode == "source_track":
            policy = _contract_chain_policy(
                "guide", "source", "on", "off", False)
            status = "SOURCE TRACK — exact Source Timeline final audio"
        else:
            policy = _contract_chain_policy(
                "guide", "generated", "off", "on", False)
            status = "GENERATED AUDIO — H3 decoded/generated final audio"

        control = {
            "version": AUDIO_MODE_CONTROL_VERSION,
            "mode": mode,
        }
        return policy, control, status


class MiniMaxH3AudioModeMux:
    """Select the scene-local audio stream using the upstream visible switch."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode_control": (AUDIO_MODE_CONTROL_TYPE, {
                    "tooltip": "Mode control from MiniMax H3 Audio Mode Switch.",
                }),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Current Shot source_audio_slice.",
                }),
                "generated_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Decoded H3 audio from VAEDecodeAudio.",
                }),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "status")
    OUTPUT_TOOLTIPS = (
        "Selected scene-local audio for Loop Trim / Segment Save / Review.",
        "Selected audio source.",
    )
    FUNCTION = "select"
    CATEGORY = "conditioning/minimax/contex_loop/policies"
    DESCRIPTION = (
        "Automatic downstream audio router paired with MiniMax H3 Audio Mode "
        "Switch. It requests only the branch selected by the project switch."
    )

    def check_lazy_status(
        self, mode_control, source_audio=None, generated_audio=None
    ):
        mode = _mode_from_control(mode_control)
        if mode == "source_track" and source_audio is None:
            return ["source_audio"]
        if mode == "generated_audio" and generated_audio is None:
            return ["generated_audio"]
        return []

    def select(self, mode_control, source_audio=None, generated_audio=None):
        mode = _mode_from_control(mode_control)
        if mode == "source_track":
            if source_audio is None:
                raise ValueError(
                    "H3 Audio Mode is source_track but Current Shot source audio "
                    "is unavailable. Connect a Source Timeline."
                )
            return source_audio, "SOURCE TRACK"

        if generated_audio is None:
            raise ValueError(
                "H3 Audio Mode is generated_audio but decoded H3 audio is "
                "unavailable. Connect VAEDecodeAudio to generated_audio."
            )
        return generated_audio, "GENERATED AUDIO"


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3AudioModeSwitch": MiniMaxH3AudioModeSwitch,
    "MiniMaxH3AudioModeMux": MiniMaxH3AudioModeMux,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3AudioModeSwitch": "MiniMax H3 · Audio Mode Switch",
    "MiniMaxH3AudioModeMux": "MiniMax H3 · Auto Audio Router",
}
