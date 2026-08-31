"""Simplified user-facing controls for the reusable MiniMax H3 master workflow.

The master workflow deliberately hides low-level H3 policy axes behind one
semantic choice per function. Existing chain/reference implementations remain
authoritative; these nodes are thin lazy facades that preserve their contracts.
"""

from __future__ import annotations

import math
from typing import Any

import torch

from . import chain_nodes as _chain
from .contracts_v05 import chain_policy as _contract_chain_policy
from .exact_final_timeline import _exact_source_window


TAGGED_REFERENCE_TYPE = "H3_TAGGED_REFERENCES"
CHAIN_POLICY_TYPE = "H3_CHAIN_POLICY"
MASTER_AUDIO_CONTROL_TYPE = "H3_MASTER_AUDIO_CONTROL"
MASTER_AUDIO_CONTROL_VERSION = "h3_master_audio_control_v1"

MASTER_AUDIO_MODES = (
    "H3 GENERATED",
    "EXTERNAL / SOURCE",
    "H3 GENERATED + AUDIO REFERENCES",
    "H3 GENERATED + EXTERNAL MIX",
)

_MODE_GENERATED = "generated"
_MODE_SOURCE = "source"
_MODE_REFERENCES = "generated_with_references"
_MODE_MIX = "generated_external_mix"

_MODE_BY_LABEL = {
    MASTER_AUDIO_MODES[0]: _MODE_GENERATED,
    MASTER_AUDIO_MODES[1]: _MODE_SOURCE,
    MASTER_AUDIO_MODES[2]: _MODE_REFERENCES,
    MASTER_AUDIO_MODES[3]: _MODE_MIX,
}


def _empty_or_previous(previous: Any) -> dict[str, Any]:
    if previous is None:
        return _chain._make_tagged_references([])
    _chain._tagged_reference_entries(previous)
    return previous


def _disabled_reference(previous: Any, label: str):
    references = _empty_or_previous(previous)
    return (
        references,
        _chain._reference_fingerprint_output(references),
        "%s OFF — media not evaluated or registered" % label,
    )


def _require_lazy_input(enabled: bool, name: str, values: dict[str, Any]) -> list[str]:
    if not bool(enabled):
        return []
    if name in values and values.get(name) is None:
        return [name]
    return []


class MiniMaxH3MasterPictureReferenceSlot:
    """One permanent picture slot with a real lazy ON/OFF switch."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "ON registers this picture as an H3 @reference. OFF leaves the slot wired but does not evaluate the image loader.",
                }),
                "tag": ("STRING", {
                    "default": "image_ref_1",
                    "tooltip": "Stable prompt tag without @, for example hero_face.",
                }),
                "image": ("IMAGE", {
                    "lazy": True,
                    "tooltip": "Permanent picture-loader connection. It is evaluated only when this slot is ON.",
                }),
            },
            "optional": {
                "previous": (TAGGED_REFERENCE_TYPE, {
                    "tooltip": "Previous master reference slot.",
                }),
            },
            "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (TAGGED_REFERENCE_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("references", "reference_fingerprint", "status")
    FUNCTION = "add"
    CATEGORY = "conditioning/minimax/contex_loop/master/references"
    DESCRIPTION = "Simple lazy H3 picture-reference slot: ON/OFF, tag, media."

    def check_lazy_status(self, enabled, **kwargs):
        return _require_lazy_input(enabled, "image", kwargs)

    def add(self, enabled, tag, image=None, previous=None,
            dynprompt=None, unique_id=None):
        if not bool(enabled):
            return _disabled_reference(previous, "PICTURE REF")
        if image is None:
            raise ValueError("Picture reference is ON but no image is connected.")
        return _chain.MiniMaxH3TaggedPictureReference().add(
            image, tag, previous=previous,
            dynprompt=dynprompt, unique_id=unique_id)


class MiniMaxH3MasterVideoReferenceSlot:
    """One permanent video slot; paired audio and timing policy are internal."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "ON registers this video as an H3 @reference. OFF keeps the slot wired without evaluating its video/audio preparation branch.",
                }),
                "tag": ("STRING", {
                    "default": "video_ref_1",
                    "tooltip": "Stable prompt tag without @.",
                }),
                "video": ("IMAGE", {
                    "lazy": True,
                    "tooltip": "Permanent 24 fps reference-video connection. It is evaluated only when this slot is ON.",
                }),
            },
            "optional": {
                "audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Optional synchronized audio from the same reference video. When connected it is paired automatically; no extra user switch is required.",
                }),
                "previous": (TAGGED_REFERENCE_TYPE, {
                    "tooltip": "Previous master reference slot.",
                }),
            },
            "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (TAGGED_REFERENCE_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("references", "reference_fingerprint", "status")
    FUNCTION = "add"
    CATEGORY = "conditioning/minimax/contex_loop/master/references"
    DESCRIPTION = "Simple lazy H3 video-reference slot with automatic paired audio."

    def check_lazy_status(self, enabled, **kwargs):
        if not bool(enabled):
            return []
        needed = _require_lazy_input(True, "video", kwargs)
        if "audio" in kwargs and kwargs.get("audio") is None:
            needed.append("audio")
        return needed

    def add(self, enabled, tag, video=None, audio=None, previous=None,
            dynprompt=None, unique_id=None):
        if not bool(enabled):
            return _disabled_reference(previous, "VIDEO REF")
        if video is None:
            raise ValueError("Video reference is ON but no video is connected.")
        return _chain.MiniMaxH3TaggedVideoReference().add(
            video, tag, "", timeline_mode="restart_each_scene",
            audio=audio, previous=previous,
            dynprompt=dynprompt, unique_id=unique_id)


class MiniMaxH3MasterAudioReferenceSlot:
    """One permanent standalone audio-reference slot with no source-track mode."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "ON registers this clip only as a standalone H3 audio reference. OFF does not evaluate the audio loader.",
                }),
                "tag": ("STRING", {
                    "default": "audio_ref_1",
                    "tooltip": "Stable prompt tag without @, for example voice.",
                }),
                "audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Permanent audio-reference loader connection. This can never become the project source/final soundtrack through this node.",
                }),
            },
            "optional": {
                "previous": (TAGGED_REFERENCE_TYPE, {
                    "tooltip": "Previous master reference slot.",
                }),
            },
            "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (TAGGED_REFERENCE_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("references", "reference_fingerprint", "status")
    FUNCTION = "add"
    CATEGORY = "conditioning/minimax/contex_loop/master/references"
    DESCRIPTION = "Simple lazy standalone H3 audio-reference slot: ON/OFF, tag, media."

    def check_lazy_status(self, enabled, **kwargs):
        return _require_lazy_input(enabled, "audio", kwargs)

    def add(self, enabled, tag, audio=None, previous=None,
            dynprompt=None, unique_id=None):
        if not bool(enabled):
            return _disabled_reference(previous, "AUDIO REF")
        if audio is None:
            raise ValueError("Audio reference is ON but no audio is connected.")
        return _chain.MiniMaxH3TaggedAudioReference().add(
            audio, tag, timeline_mode="standalone",
            align_audio_reference=False, previous=previous,
            dynprompt=dynprompt, unique_id=unique_id)


def _normalized_master_audio_control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != MASTER_AUDIO_CONTROL_VERSION:
        raise ValueError("Master Audio control is missing or obsolete.")
    mode = str(value.get("mode") or "")
    if mode not in (_MODE_GENERATED, _MODE_SOURCE, _MODE_REFERENCES, _MODE_MIX):
        raise ValueError("Unknown Master Audio mode %r." % mode)
    result = dict(value)
    result["generated_level"] = float(result.get("generated_level", 1.0))
    result["external_level"] = float(result.get("external_level", 1.0))
    return result


class MiniMaxH3MasterAudioMode:
    """One user choice; all low-level H3 audio policy axes are internal."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_mode": (list(MASTER_AUDIO_MODES), {
                    "default": "H3 GENERATED",
                    "tooltip": "Choose the intended final-audio behavior. Source/reference/continuity routing is resolved internally.",
                }),
                "generated_level": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01,
                    "tooltip": "Used only by GENERATED + EXTERNAL MIX. 1.0 = unchanged.",
                }),
                "external_level": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01,
                    "tooltip": "Used only by GENERATED + EXTERNAL MIX. 1.0 = unchanged.",
                }),
            },
        }

    RETURN_TYPES = (CHAIN_POLICY_TYPE, MASTER_AUDIO_CONTROL_TYPE, "STRING")
    RETURN_NAMES = ("chain_policy", "audio_control", "status")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = (
        "Master-facing audio selector. It replaces the separate Final audio, "
        "Source reference, Generated continuity and Lock source audio switches "
        "with one semantic choice."
    )

    def build(self, audio_mode="H3 GENERATED",
              generated_level=1.0, external_level=1.0):
        try:
            mode = _MODE_BY_LABEL[str(audio_mode)]
        except KeyError as exc:
            raise ValueError("Unknown Master Audio mode %r." % audio_mode) from exc
        generated_level = float(generated_level)
        external_level = float(external_level)
        if not math.isfinite(generated_level) or not math.isfinite(external_level):
            raise ValueError("Master Audio levels must be finite numbers.")

        if mode == _MODE_SOURCE:
            policy = _contract_chain_policy(
                "guide", "source", "on", "off", False)
            detail = "exact Source Timeline final audio; source guidance on; generated carry off"
        elif mode == _MODE_MIX:
            policy = _contract_chain_policy(
                "guide", "generated", "off", "on", False)
            detail = "H3 generated audio mixed with an independent external master track"
        elif mode == _MODE_REFERENCES:
            policy = _contract_chain_policy(
                "guide", "generated", "off", "on", False)
            detail = "H3 generated final audio; standalone @audio refs remain prompt-driven"
        else:
            policy = _contract_chain_policy(
                "guide", "generated", "off", "on", False)
            detail = "H3 generated final audio; generated continuity on"

        control = {
            "version": MASTER_AUDIO_CONTROL_VERSION,
            "mode": mode,
            "label": str(audio_mode),
            "generated_level": generated_level,
            "external_level": external_level,
        }
        return policy, control, "%s — %s" % (audio_mode, detail)


def _audio_3d(audio: Any, label: str):
    waveform, sample_rate = _chain._validate_audio(audio, label)
    if getattr(waveform, "ndim", 0) == 2:
        waveform = waveform.unsqueeze(0)
    if getattr(waveform, "ndim", 0) != 3:
        raise ValueError("%s must resolve to [B,C,L] AUDIO." % label)
    waveform = waveform[:1]
    channels = int(waveform.shape[1])
    if channels == 1:
        waveform = waveform.repeat(1, 2, 1)
    elif channels != 2:
        raise ValueError("%s must be mono or stereo." % label)
    return waveform, int(sample_rate)


def _resample_waveform(waveform, source_rate: int, target_rate: int):
    if int(source_rate) == int(target_rate):
        return waveform
    try:
        import torchaudio
    except ImportError as exc:
        raise RuntimeError(
            "Master Audio mix needs torchaudio to combine different sample rates."
        ) from exc
    return torchaudio.functional.resample(
        waveform, int(source_rate), int(target_rate))


def _fit_samples(waveform, samples: int):
    samples = max(0, int(samples))
    current = int(waveform.shape[-1])
    if current > samples:
        return waveform[..., :samples]
    if current < samples:
        return torch.nn.functional.pad(waveform, (0, samples - current))
    return waveform


def _mix_audio(generated: Any, external: Any,
               generated_level: float, external_level: float):
    generated_wave, sample_rate = _audio_3d(
        generated, "Master Audio generated input")
    external_wave, external_rate = _audio_3d(
        external, "Master Audio external input")
    external_wave = _resample_waveform(
        external_wave, external_rate, sample_rate)
    external_wave = _fit_samples(external_wave, int(generated_wave.shape[-1]))
    generated_wave = generated_wave.to(dtype=torch.float32)
    external_wave = external_wave.to(
        device=generated_wave.device, dtype=torch.float32)
    mixed = (
        generated_wave * float(generated_level)
        + external_wave * float(external_level)
    )
    peak = float(mixed.detach().abs().max().item()) if mixed.numel() else 0.0
    attenuation = 1.0
    if peak > 1.0:
        attenuation = 1.0 / peak
        mixed = mixed * attenuation
    return {
        "waveform": mixed,
        "sample_rate": int(sample_rate),
    }, peak, attenuation


class MiniMaxH3MasterAudioRouter:
    """Lazy final scene-audio selector/mixer paired with Master Audio Mode."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": ("H3_CHAIN_STATE", {
                    "tooltip": "Current Shot state. Used to align an independent external mix track to the exact raw H3 scene window.",
                }),
                "audio_control": (MASTER_AUDIO_CONTROL_TYPE, {
                    "tooltip": "Control from MiniMax H3 Master Audio Mode.",
                }),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Current Shot source_audio_slice. Requested only in EXTERNAL / SOURCE mode.",
                }),
                "generated_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Decoded H3 scene audio before Loop Trim. Requested only by generated modes.",
                }),
                "external_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Independent full external/master soundtrack. Requested only in GENERATED + EXTERNAL MIX.",
                }),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "status")
    FUNCTION = "route"
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = (
        "Automatic lazy scene-audio router. One upstream mode choice selects "
        "source, generated, generated-with-reference conditioning, or a real "
        "generated+external mix; inactive branches are not evaluated."
    )

    def check_lazy_status(self, state, audio_control, **kwargs):
        control = _normalized_master_audio_control(audio_control)
        mode = control["mode"]
        if mode == _MODE_SOURCE:
            wanted = ["source_audio"]
        elif mode in (_MODE_GENERATED, _MODE_REFERENCES):
            wanted = ["generated_audio"]
        else:
            wanted = ["generated_audio", "external_audio"]
        return [
            name for name in wanted
            if name in kwargs and kwargs.get(name) is None
        ]

    def route(self, state, audio_control, source_audio=None,
              generated_audio=None, external_audio=None):
        control = _normalized_master_audio_control(audio_control)
        mode = control["mode"]
        if mode == _MODE_SOURCE:
            if source_audio is None:
                raise ValueError(
                    "EXTERNAL / SOURCE mode needs Current Shot source_audio_slice."
                )
            return source_audio, "EXTERNAL / SOURCE — exact source scene audio"

        if mode in (_MODE_GENERATED, _MODE_REFERENCES):
            if generated_audio is None:
                raise ValueError(
                    "%s needs decoded H3 audio from VAEDecodeAudio." %
                    control.get("label", "H3 GENERATED"))
            suffix = (
                " + prompt-driven standalone audio references"
                if mode == _MODE_REFERENCES else "")
            return generated_audio, "H3 GENERATED%s" % suffix

        if generated_audio is None:
            raise ValueError(
                "GENERATED + EXTERNAL MIX needs decoded H3 generated audio.")
        if external_audio is None:
            raise ValueError(
                "GENERATED + EXTERNAL MIX needs the full external/master AUDIO."
            )
        plan = state.get("plan") if isinstance(state, dict) else None
        index = int(state.get("index", 0)) if isinstance(state, dict) else 0
        if not isinstance(plan, dict) or index < 1 or index > len(plan.get("shots", [])):
            raise ValueError("Master Audio mix requires a valid Current Shot state.")
        shot = plan["shots"][index - 1]
        external_scene = _exact_source_window(
            plan, state, shot, None, external_audio)
        mixed, peak, attenuation = _mix_audio(
            generated_audio, external_scene,
            control["generated_level"], control["external_level"])
        safety = (
            "; safety attenuation %.4f (pre-limit peak %.4f)" %
            (attenuation, peak) if attenuation < 1.0 else "")
        return mixed, (
            "GENERATED + EXTERNAL MIX — generated %.2f / external %.2f%s" %
            (control["generated_level"], control["external_level"], safety)
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterPictureReferenceSlot": MiniMaxH3MasterPictureReferenceSlot,
    "MiniMaxH3MasterVideoReferenceSlot": MiniMaxH3MasterVideoReferenceSlot,
    "MiniMaxH3MasterAudioReferenceSlot": MiniMaxH3MasterAudioReferenceSlot,
    "MiniMaxH3MasterAudioMode": MiniMaxH3MasterAudioMode,
    "MiniMaxH3MasterAudioRouter": MiniMaxH3MasterAudioRouter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterPictureReferenceSlot": "MiniMax H3 · Picture Ref Slot",
    "MiniMaxH3MasterVideoReferenceSlot": "MiniMax H3 · Video Ref Slot",
    "MiniMaxH3MasterAudioReferenceSlot": "MiniMax H3 · Audio Ref Slot",
    "MiniMaxH3MasterAudioMode": "MiniMax H3 · Master Audio Mode",
    "MiniMaxH3MasterAudioRouter": "MiniMax H3 · Master Audio Router",
}
