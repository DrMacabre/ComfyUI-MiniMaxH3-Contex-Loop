"""Hidden policy composition for the simplified MiniMax H3 master UI.

Users choose one continuation mode and one audio mode. This module translates
those semantic controls into the existing H3 Chain Policy contract and gates
the project source track lazily, so unused source media is never evaluated.
"""

from __future__ import annotations

from typing import Any

from .contracts_v05 import chain_policy as _chain_policy
from .master_simple_ui import (
    MASTER_AUDIO_CONTROL_TYPE,
    MASTER_AUDIO_CONTROL_VERSION,
)


MASTER_TRANSITION_CONTROL_TYPE = "H3_MASTER_TRANSITION_CONTROL"
MASTER_TRANSITION_CONTROL_VERSION = "h3_master_transition_control_v1"
MASTER_TRANSITION_MODES = (
    "NEW SHOT / GUIDE",
    "CONTINUE / MASKED AV",
    "SOFT AV CONTINUE",
    "CUT / INDEPENDENT",
)

_TRANSITION_BY_LABEL = {
    "NEW SHOT / GUIDE": "guide",
    "CONTINUE / MASKED AV": "hard_av",
    "SOFT AV CONTINUE": "soft_av",
    "CUT / INDEPENDENT": "cut",
}


def _audio_control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != MASTER_AUDIO_CONTROL_VERSION:
        raise ValueError("Master Audio control is missing or obsolete.")
    mode = str(value.get("mode") or "")
    if mode not in (
        "generated", "source", "generated_with_references",
        "generated_external_mix",
    ):
        raise ValueError("Unknown Master Audio mode %r." % mode)
    return value


def _transition_control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != MASTER_TRANSITION_CONTROL_VERSION:
        raise ValueError("Master Continuation control is missing or obsolete.")
    preset = str(value.get("preset") or "")
    if preset not in ("guide", "hard_av", "soft_av", "cut"):
        raise ValueError("Unknown Master Continuation preset %r." % preset)
    return value


class MiniMaxH3MasterTransitionMode:
    """One visible continuation choice; context implementation stays internal."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "continuation_mode": (list(MASTER_TRANSITION_MODES), {
                    "default": "NEW SHOT / GUIDE",
                    "tooltip": "Choose the scene-boundary behavior. GUIDE uses the standard guided new-shot path; MASKED AV uses the tested 39-frame AV continuation; SOFT AV keeps the same picture continuation with feathered audio; CUT makes the scene independent.",
                }),
            },
        }

    RETURN_TYPES = (MASTER_TRANSITION_CONTROL_TYPE, "STRING")
    RETURN_NAMES = ("transition_control", "status")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = "Simple semantic continuation selector for the master workflow."

    def build(self, continuation_mode="NEW SHOT / GUIDE"):
        label = str(continuation_mode)
        try:
            preset = _TRANSITION_BY_LABEL[label]
        except KeyError as exc:
            raise ValueError("Unknown Master Continuation mode %r." % label) from exc
        return {
            "version": MASTER_TRANSITION_CONTROL_VERSION,
            "label": label,
            "preset": preset,
        }, label


class MiniMaxH3MasterChainPolicyRouter:
    """Internal adapter from the two simple master controls to H3 Chain Policy."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_control": (MASTER_AUDIO_CONTROL_TYPE, {}),
                "transition_control": (MASTER_TRANSITION_CONTROL_TYPE, {}),
            },
        }

    RETURN_TYPES = ("H3_CHAIN_POLICY", "STRING")
    RETURN_NAMES = ("chain_policy", "status")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/master/internal"
    DESCRIPTION = "Internal master policy composer. No low-level policy axes are user-facing."

    def build(self, audio_control, transition_control):
        audio = _audio_control(audio_control)
        transition = _transition_control(transition_control)
        mode = str(audio["mode"])
        if mode == "source":
            final_audio, source_reference, generated_continuity = (
                "source", "on", "off")
        else:
            final_audio, source_reference, generated_continuity = (
                "generated", "off", "on")
        policy = _chain_policy(
            transition["preset"], final_audio, source_reference,
            generated_continuity, False)
        return policy, "%s / %s" % (
            transition.get("label", transition["preset"]),
            audio.get("label", mode))


class MiniMaxH3MasterSourceAudioGate:
    """Lazy project-source gate for Loop Start; inactive modes output None."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_control": (MASTER_AUDIO_CONTROL_TYPE, {}),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Full SOURCE / EXTERNAL AUDIO loader. Evaluated for Loop Start only when EXTERNAL / SOURCE is selected.",
                }),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("source_audio", "status")
    FUNCTION = "route"
    CATEGORY = "conditioning/minimax/contex_loop/master/internal"
    DESCRIPTION = "Internal lazy gate preventing unused source-audio loaders from running."

    def check_lazy_status(self, audio_control, **kwargs):
        mode = str(_audio_control(audio_control)["mode"])
        if mode == "source" and "source_audio" in kwargs and kwargs.get("source_audio") is None:
            return ["source_audio"]
        return []

    def route(self, audio_control, source_audio=None):
        mode = str(_audio_control(audio_control)["mode"])
        if mode != "source":
            return None, "Source Timeline inactive for this audio mode"
        if source_audio is None:
            raise ValueError(
                "EXTERNAL / SOURCE is selected but SOURCE / EXTERNAL AUDIO is not connected.")
        return source_audio, "Source Timeline active"


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterTransitionMode": MiniMaxH3MasterTransitionMode,
    "MiniMaxH3MasterChainPolicyRouter": MiniMaxH3MasterChainPolicyRouter,
    "MiniMaxH3MasterSourceAudioGate": MiniMaxH3MasterSourceAudioGate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterTransitionMode": "MiniMax H3 · Continuation Mode",
    "MiniMaxH3MasterChainPolicyRouter": "MiniMax H3 · Internal Policy Router",
    "MiniMaxH3MasterSourceAudioGate": "MiniMax H3 · Internal Source Audio Gate",
}
