"""One-control master export facade for the reusable MiniMax H3 workflow."""

from __future__ import annotations

from typing import Any

from . import chain_nodes as c
from . import master_video_export_0637 as advanced


MASTER_EXPORT_CONFIG_TYPE = "H3_MASTER_EXPORT_CONFIG"
MASTER_EXPORT_CONFIG_VERSION = "h3_master_export_config_v1"
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


def _profile_config(profile: Any) -> dict[str, Any]:
    name = str(profile or "HIGH QUALITY")
    try:
        recipe = dict(_PROFILE_CONFIG[name])
    except KeyError as exc:
        raise ValueError("Unknown H3 master export profile %r." % profile) from exc
    return {
        "version": MASTER_EXPORT_CONFIG_VERSION,
        "profile": name,
        **recipe,
    }


def _normalized_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != MASTER_EXPORT_CONFIG_VERSION:
        raise ValueError("Master Export Profile is missing or obsolete.")
    profile = str(value.get("profile") or "")
    if profile not in _PROFILE_CONFIG:
        raise ValueError("Unknown H3 master export profile %r." % profile)
    return _profile_config(profile)


class MiniMaxH3MasterExportProfile:
    """The single export-quality control shared by every master output."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "profile": (list(MASTER_EXPORT_PROFILES), {
                    "default": "HIGH QUALITY",
                    "tooltip": "One shared choice for normal and recovery exports. DELIVERY/MOBILE is H.264 8-bit compatible output; HIGH QUALITY is HEVC 10-bit; LOSSLESS ARCHIVE is FFV1 16-bit; EDITING MASTER is true uncompressed V210 10-bit.",
                }),
            },
        }

    RETURN_TYPES = (MASTER_EXPORT_CONFIG_TYPE, "STRING")
    RETURN_NAMES = ("export_config", "status")
    FUNCTION = "build"
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = "One export profile fan-outs to every final/recovery master exporter."

    def build(self, profile="HIGH QUALITY"):
        config = _profile_config(profile)
        return config, "%s — %s %s-bit %s" % (
            config["profile"], config["video_codec"], config["bit_depth"],
            config["quality_mode"])


class MiniMaxH3MasterExport:
    """Export one manifest using the shared master profile."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (c.MANIFEST_TYPE, {
                    "tooltip": "Completed H3 checkpoint lineage from normal Loop End or recovery Manifest Load.",
                }),
                "video_vae": ("VAE", {
                    "tooltip": "MiniMax H3 video VAE used for high-fidelity latent decode.",
                }),
                "export_config": (MASTER_EXPORT_CONFIG_TYPE, {
                    "tooltip": "Shared config from the single Master Export Profile node.",
                }),
                "filename": ("STRING", {
                    "default": "master",
                    "tooltip": "Readable output basename. A content hash is added automatically.",
                }),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "lazy": True,
                    "tooltip": "Source-track fallback, evaluated only when the manifest's final audio policy resolves to source.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_path", "status")
    OUTPUT_TOOLTIPS = (
        "File-backed master video.",
        "Absolute master path.",
        "Resolved shared profile and underlying export status.",
    )
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop/master"
    DESCRIPTION = (
        "Master exporter driven by the shared profile node. Codec, bit depth, "
        "quality mode, blend handling, cache and audio mux settings are internal."
    )

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def check_lazy_status(self, manifest, video_vae, export_config=None,
                          filename="master", **kwargs):
        if export_config is not None:
            _normalized_config(export_config)
        try:
            selected = c._audio_policy_final(manifest)
        except Exception:
            selected = None
        if selected == "source" and "source_audio" in kwargs \
                and kwargs.get("source_audio") is None:
            return ["source_audio"]
        return []

    def export(self, manifest, video_vae, export_config=None,
               filename="master", source_audio=None, profile=None):
        # `profile` is a hidden Python-level compatibility path for the first
        # development facade/tests. The ComfyUI master workflow exposes only
        # export_config from MiniMaxH3MasterExportProfile.
        config = (
            _normalized_config(export_config)
            if export_config is not None else _profile_config(profile))
        profile_name = config["profile"]
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
        return video, path, "%s — %s" % (profile_name, status)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterExportProfile": MiniMaxH3MasterExportProfile,
    "MiniMaxH3MasterExport": MiniMaxH3MasterExport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterExportProfile": "MiniMax H3 · Export Profile",
    "MiniMaxH3MasterExport": "MiniMax H3 · Master Export",
}
