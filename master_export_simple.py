"""One-control master export facade for the reusable MiniMax H3 workflow."""

from __future__ import annotations

from typing import Any

from . import chain_nodes as c
from . import master_video_export_0637 as advanced


MASTER_EXPORT_PROFILES = (
    "DELIVERY / MOBILE",
    "HIGH QUALITY",
    "LOSSLESS ARCHIVE",
    "EDITING MASTER",
)

_PROFILE_CONFIG = {
    "DELIVERY / MOBILE": {
        "video_codec": "h264",
        "bit_depth": "8",
        "quality_mode": "crf",
        "crf": 20,
        "audio_bitrate": 256,
    },
    "HIGH QUALITY": {
        "video_codec": "h265",
        "bit_depth": "10",
        "quality_mode": "crf",
        "crf": 16,
        "audio_bitrate": 320,
    },
    "LOSSLESS ARCHIVE": {
        "video_codec": "ffv1_lossless",
        "bit_depth": "16",
        "quality_mode": "lossless",
        "crf": 0,
        "audio_bitrate": 320,
    },
    "EDITING MASTER": {
        "video_codec": "uncompressed_v210",
        "bit_depth": "10",
        "quality_mode": "lossless",
        "crf": 0,
        "audio_bitrate": 320,
    },
}


class MiniMaxH3MasterExport:
    """Expose only the useful export profile and basename to normal users."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (c.MANIFEST_TYPE, {
                    "tooltip": "Completed H3 checkpoint lineage.",
                }),
                "video_vae": ("VAE", {
                    "tooltip": "MiniMax H3 video VAE used for high-fidelity latent decode.",
                }),
                "profile": (list(MASTER_EXPORT_PROFILES), {
                    "default": "HIGH QUALITY",
                    "tooltip": "One master-facing choice. Codec, real bit depth, quality mode, blend handling, cache strategy and audio mux settings are resolved internally.",
                }),
                "filename": ("STRING", {
                    "default": "master",
                    "tooltip": "Readable output basename. A content hash is added automatically.",
                }),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Legacy/source-track fallback. It is requested only when this manifest's final audio policy resolves to source.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_path", "status")
    OUTPUT_TOOLTIPS = (
        "File-backed master video.",
        "Absolute master path.",
        "Resolved profile and underlying export status.",
    )
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = (
        "Simple master export. DELIVERY/MOBILE, HIGH QUALITY, LOSSLESS ARCHIVE "
        "and EDITING MASTER are complete internal recipes; the advanced codec "
        "node remains available outside the normal master workflow."
    )

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def check_lazy_status(self, manifest, video_vae, profile, filename,
                          **kwargs):
        try:
            selected = c._audio_policy_final(manifest)
        except Exception:
            selected = None
        if selected == "source" and "source_audio" in kwargs \
                and kwargs.get("source_audio") is None:
            return ["source_audio"]
        return []

    def export(self, manifest, video_vae, profile="HIGH QUALITY",
               filename="master", source_audio=None):
        try:
            config = dict(_PROFILE_CONFIG[str(profile)])
        except KeyError as exc:
            raise ValueError("Unknown H3 master export profile %r." % profile) from exc

        video, path, status = advanced.MiniMaxH3ChainMasterVideoExport().export(
            manifest=manifest,
            video_vae=video_vae,
            video_codec=config["video_codec"],
            bit_depth=config["bit_depth"],
            quality_mode=config["quality_mode"],
            crf=config["crf"],
            audio_source="plan",
            blend_schedule="plan",
            decode_buffer="disk-backed",
            reuse_cache=True,
            filename=filename,
            audio_bitrate=config["audio_bitrate"],
            source_audio=source_audio,
        )
        return video, path, "%s — %s" % (profile, status)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterExport": MiniMaxH3MasterExport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterExport": "MiniMax H3 · Master Export",
}
