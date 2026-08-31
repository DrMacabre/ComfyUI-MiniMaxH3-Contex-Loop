"""Simplified source-video modes for the reusable MiniMax H3 master workflow.

The single visible mode selector is deliberately separate from master audio.
Source-video editing replaces only the H3 video target; it never silently turns
embedded source audio into final/reference audio. Existing-video continuation is
prepared only for the continuation mode and remains an optional Loop Start input.
"""

from __future__ import annotations

from typing import Any

import torch

from . import chain_nodes as c
from .masked_context import _validate_target_streams
from .nodes import _resize
from .source_av_target import _canonical_indices


MASTER_VIDEO_CONTROL_TYPE = "H3_MASTER_VIDEO_CONTROL"
MASTER_VIDEO_CONTROL_VERSION = "h3_master_video_control_v1"
MASTER_VIDEO_MODES = (
    "H3 GENERATION",
    "CONTINUE SOURCE VIDEO",
    "EDIT SOURCE VIDEO",
)

_MODE_GENERATE = "generate"
_MODE_CONTINUE = "continue"
_MODE_EDIT = "edit"
_MODE_BY_LABEL = {
    MASTER_VIDEO_MODES[0]: _MODE_GENERATE,
    MASTER_VIDEO_MODES[1]: _MODE_CONTINUE,
    MASTER_VIDEO_MODES[2]: _MODE_EDIT,
}


def _control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != MASTER_VIDEO_CONTROL_VERSION:
        raise ValueError("Master Video control is missing or obsolete.")
    mode = str(value.get("mode") or "")
    if mode not in (_MODE_GENERATE, _MODE_CONTINUE, _MODE_EDIT):
        raise ValueError("Unknown Master Video mode %r." % mode)
    return value


class MiniMaxH3MasterVideoMode:
    """The only source-video mode control exposed by the master workflow."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_mode": (list(MASTER_VIDEO_MODES), {
                    "default": "H3 GENERATION",
                    "tooltip": "H3 GENERATION ignores Source Video; CONTINUE SOURCE VIDEO uses it as scene 1 predecessor and prepends it to assembly; EDIT SOURCE VIDEO uses its exact picture timeline as the H3 video target. Audio routing remains controlled independently by Master Audio Mode.",
                }),
            },
        }

    RETURN_TYPES = (MASTER_VIDEO_CONTROL_TYPE, "STRING")
    RETURN_NAMES = ("video_control", "status")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = "One visible source-video mode selector; routing details stay internal."

    def build(self, video_mode="H3 GENERATION"):
        try:
            mode = _MODE_BY_LABEL[str(video_mode)]
        except KeyError as exc:
            raise ValueError("Unknown Master Video mode %r." % video_mode) from exc
        return {
            "version": MASTER_VIDEO_CONTROL_VERSION,
            "mode": mode,
            "label": str(video_mode),
        }, str(video_mode)


class MiniMaxH3MasterExistingVideoRouter:
    """Internal lazy adapter feeding Loop Start only in continuation mode."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "plan": (c.PLAN_TYPE, {}),
                "video_control": (MASTER_VIDEO_CONTROL_TYPE, {}),
            },
            "optional": {
                "source_video": ("VIDEO", {
                    "lazy": True,
                    "tooltip": "Full Source Video. Evaluated only in CONTINUE SOURCE VIDEO mode.",
                }),
            },
        }

    RETURN_TYPES = (c.EXTERNAL_CONTEXT_TYPE, "STRING")
    RETURN_NAMES = ("external_context", "status")
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/contex_loop/master/internal"
    DESCRIPTION = "Internal lazy Existing Video Context route controlled by Master Video Mode."

    def check_lazy_status(self, plan, video_control, **kwargs):
        if _control(video_control)["mode"] != _MODE_CONTINUE:
            return []
        if "source_video" in kwargs and kwargs.get("source_video") is None:
            return ["source_video"]
        return []

    def prepare(self, plan, video_control, source_video=None):
        mode = _control(video_control)["mode"]
        if mode != _MODE_CONTINUE:
            return None, "Existing Video Context inactive"
        if source_video is None:
            raise ValueError(
                "CONTINUE SOURCE VIDEO is selected but Source Video is not connected.")
        context, status = c.MiniMaxH3ChainExternalVideo().prepare(
            plan, source_video=source_video, prepend_original=True)
        return context, "CONTINUE SOURCE VIDEO — %s" % status


def _edit_source_frames(state, source_video, latent, vae, crop="center"):
    plan = state.get("plan") if isinstance(state, dict) else None
    index = int(state.get("index", 0)) if isinstance(state, dict) else 0
    if not isinstance(plan, dict) or index < 1 or index > len(plan.get("shots", [])):
        raise ValueError("EDIT SOURCE VIDEO requires a valid Current Shot state.")
    shot = plan["shots"][index - 1]
    try:
        start_frame = int(shot["generation_start_frame"])
        raw_frames = int(shot["raw_frames"])
        tail_trim = max(0, int(shot.get("tail_trim_frames", 0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Current scene lacks exact source-video timeline metadata.") from exc
    if start_frame < 0:
        raise ValueError(
            "EDIT SOURCE VIDEO cannot begin before source frame 0; source continuation and source editing are separate master modes.")
    visible_frames = raw_frames - tail_trim
    if visible_frames < 1:
        raise ValueError("EDIT SOURCE VIDEO resolved no visible source frames.")

    source_frames, _source_audio, source_fps, _route = c._resolve_video_inputs(
        source_video, None, None, 24.0, "Master source-video edit")
    target_video, target_audio, target_frames = _validate_target_streams(
        latent, strict_audio_grid=False)
    if int(target_frames) != raw_frames:
        raise RuntimeError(
            "EDIT SOURCE VIDEO target covers %d frames but Current Shot plans %d raw H3 frames."
            % (int(target_frames), raw_frames))

    indices = _canonical_indices(
        int(source_frames.shape[0]), source_fps, source_frames.device)
    end_frame = start_frame + visible_frames
    if end_frame > int(indices.numel()):
        raise ValueError(
            "EDIT SOURCE VIDEO scene %d needs source frames %d..%d, but the canonical 24 fps source has only %d frames."
            % (index, start_frame, end_frame - 1, int(indices.numel())))
    selected = source_frames.index_select(0, indices[start_frame:end_frame])
    if tail_trim:
        selected = torch.cat(
            (selected, selected[-1:].expand(tail_trim, -1, -1, -1).clone()),
            dim=0)
    if int(selected.shape[0]) != raw_frames:
        raise RuntimeError("EDIT SOURCE VIDEO exact-final padding produced the wrong raw frame count.")

    width = int(target_video.shape[4]) * 16
    height = int(target_video.shape[3]) * 16
    resized = _resize(selected, width, height, crop)
    encoded = vae.encode(resized)
    if getattr(encoded, "ndim", 0) != 5:
        raise ValueError("EDIT SOURCE VIDEO VAE must return [B,C,T,H,W].")
    encoded = encoded[:1].to(device=target_video.device, dtype=target_video.dtype)
    if tuple(encoded.shape) != tuple(target_video.shape):
        raise ValueError(
            "EDIT SOURCE VIDEO encoded video shape %s does not match H3 target %s."
            % (tuple(encoded.shape), tuple(target_video.shape)))

    import comfy.nested_tensor

    output = latent.copy()
    output["samples"] = comfy.nested_tensor.NestedTensor((
        encoded.clone(), target_audio.clone()))
    status = (
        "EDIT SOURCE VIDEO scene %d — source %d..%d; %d visible + %d hidden-tail repeat = %d raw frames; audio target untouched"
        % (index, start_frame, end_frame - 1, visible_frames, tail_trim, raw_frames))
    return output, status


class MiniMaxH3MasterSourceVideoTarget:
    """Internal lazy source-picture target; audio is intentionally untouched."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "state": ("H3_CHAIN_STATE", {}),
                "latent": ("LATENT", {}),
                "vae": ("VAE", {}),
                "video_control": (MASTER_VIDEO_CONTROL_TYPE, {}),
            },
            "optional": {
                "source_video": ("VIDEO", {
                    "lazy": True,
                    "tooltip": "Full Source Video. Evaluated only in EDIT SOURCE VIDEO mode.",
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("latent", "status")
    FUNCTION = "prepare"
    CATEGORY = "conditioning/minimax/contex_loop/master/internal"
    DESCRIPTION = (
        "Internal source-video edit route. It replaces only the picture target, "
        "preserves the independent H3 audio target, and repeat-pads hidden Exact "
        "Final Timeline tail frames instead of consuming the next source scene."
    )

    def check_lazy_status(self, state, latent, vae, video_control, **kwargs):
        if _control(video_control)["mode"] != _MODE_EDIT:
            return []
        if "source_video" in kwargs and kwargs.get("source_video") is None:
            return ["source_video"]
        return []

    def prepare(self, state, latent, vae, video_control, source_video=None):
        mode = _control(video_control)["mode"]
        if mode != _MODE_EDIT:
            return latent, "Source-video edit target inactive"
        if source_video is None:
            raise ValueError(
                "EDIT SOURCE VIDEO is selected but Source Video is not connected.")
        return _edit_source_frames(state, source_video, latent, vae)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterVideoMode": MiniMaxH3MasterVideoMode,
    "MiniMaxH3MasterExistingVideoRouter": MiniMaxH3MasterExistingVideoRouter,
    "MiniMaxH3MasterSourceVideoTarget": MiniMaxH3MasterSourceVideoTarget,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterVideoMode": "MiniMax H3 · Master Video Mode",
    "MiniMaxH3MasterExistingVideoRouter": "MiniMax H3 · Internal Existing Video Route",
    "MiniMaxH3MasterSourceVideoTarget": "MiniMax H3 · Internal Source Video Edit",
}
