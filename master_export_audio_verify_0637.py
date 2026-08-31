"""Fail-closed audio-track verification for reusable H3 master exports.

The reusable master must never report/reuse a successful final when the selected
final-audio policy expects audio but the produced container has no decodable
audio stream. This overlay is intentionally narrow: it does not alter scene
audio, exact-timeline assembly, or ffmpeg mux semantics. It only validates the
container produced/reused by ``master_video_export_0637``.
"""
from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable


_SENTINEL = "_h3_master_export_audio_verify_v1"
BUILD = "H3_MASTER_EXPORT_AUDIO_VERIFY_0_6_37_V1"


class MasterExportAudioVerifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class MasterExportAudioVerifyReport:
    activated: bool
    patched: tuple[str, ...]


def _expected_audio(chain_module: Any, manifest: Any, requested: Any) -> str:
    selected = str(requested or "plan").strip().lower()
    if selected == "plan":
        selected = str(chain_module._audio_policy_final(manifest)).strip().lower()
    if selected not in ("source", "generated", "none"):
        raise MasterExportAudioVerifyError(
            "master export audio policy resolved to unsupported value %r" % selected)
    return selected


def _probe_audio(path: str, av_module: Any) -> tuple[bool, str]:
    if not isinstance(path, str) or not path or not os.path.isfile(path):
        return False, "output file is missing"
    if av_module is None:
        return False, "PyAV is unavailable"
    try:
        with av_module.open(path) as container:
            streams = list(getattr(container.streams, "audio", ()) or ())
            if not streams:
                return False, "container has no audio stream"
            # Decode one frame. A declared-but-empty audio stream is not an
            # acceptable final master either.
            frame = next(container.decode(audio=0), None)
            if frame is None:
                return False, "audio stream exists but contains no decodable frame"
            samples = int(getattr(frame, "samples", 0) or 0)
            rate = int(getattr(frame, "sample_rate", 0) or 0)
            return True, "audio stream decodes (%d samples @ %d Hz first frame)" % (
                samples, rate)
    except Exception as exc:
        return False, "audio probe failed: %s" % exc


def _signature_prefix(function: Callable[..., Any], expected: tuple[str, ...], *, label: str) -> None:
    try:
        names = tuple(inspect.signature(function).parameters)
    except (TypeError, ValueError) as exc:
        raise MasterExportAudioVerifyError("cannot inspect %s" % label) from exc
    if names[: len(expected)] != expected:
        raise MasterExportAudioVerifyError(
            "refusing master-audio verifier: %s signature %r does not begin with %r"
            % (label, names, expected))


def preflight_master_export_audio_verify(export_module: Any, chain_module: Any) -> tuple[str, ...]:
    cache_valid = getattr(export_module, "_cache_valid", None)
    export_cls = getattr(export_module, "MiniMaxH3ChainMasterVideoExport", None)
    export = getattr(export_cls, "export", None) if isinstance(export_cls, type) else None
    if not callable(cache_valid) or not callable(export):
        raise MasterExportAudioVerifyError("master export owners are missing")
    _signature_prefix(
        cache_valid, ("path", "sidecar_path", "digest", "total_frames"),
        label="master_video_export_0637._cache_valid")
    _signature_prefix(
        export,
        ("self", "manifest", "video_vae", "video_codec", "bit_depth", "quality_mode"),
        label="MiniMaxH3ChainMasterVideoExport.export")
    for name in ("_audio_policy_final", "_read_json", "_safe_unlink", "av", "_LOG"):
        if not hasattr(chain_module, name):
            raise MasterExportAudioVerifyError(
                "chain module is missing required master-audio symbol %s" % name)
    return (
        "master_video_export_0637._cache_valid",
        "MiniMaxH3ChainMasterVideoExport.export",
    )


def activate_master_export_audio_verify(
    export_module: Any, chain_module: Any,
) -> MasterExportAudioVerifyReport:
    preflight_master_export_audio_verify(export_module, chain_module)
    existing = getattr(export_module, _SENTINEL, None)
    if isinstance(existing, MasterExportAudioVerifyReport):
        return existing

    original_cache_valid = export_module._cache_valid

    @wraps(original_cache_valid)
    def cache_valid(path, sidecar_path, digest, total_frames):
        if not original_cache_valid(path, sidecar_path, digest, total_frames):
            return False
        try:
            record = chain_module._read_json(sidecar_path)
            selected = str((record or {}).get("audio_source") or "none").strip().lower()
        except Exception as exc:
            chain_module._LOG.warning(
                "H3 Master cache audio verification rejected %s: sidecar read failed: %s",
                path, exc)
            return False
        if selected == "none":
            return True
        ok, detail = _probe_audio(path, chain_module.av)
        if not ok:
            chain_module._LOG.warning(
                "H3 Master cache audio verification rejected %s (audio=%s): %s",
                path, selected, detail)
            return False
        return True

    setattr(cache_valid, _SENTINEL, True)
    cache_valid._master_export_audio_verify_original = original_cache_valid
    export_module._cache_valid = cache_valid

    export_cls = export_module.MiniMaxH3ChainMasterVideoExport
    original_export = export_cls.export

    @wraps(original_export)
    def export(
        self, manifest, video_vae, video_codec, bit_depth, quality_mode,
        crf, audio_source, blend_schedule, decode_buffer, reuse_cache,
        filename, audio_bitrate, source_audio=None,
    ):
        selected = _expected_audio(chain_module, manifest, audio_source)
        result = original_export(
            self, manifest, video_vae, video_codec, bit_depth, quality_mode,
            crf, audio_source, blend_schedule, decode_buffer, reuse_cache,
            filename, audio_bitrate, source_audio=source_audio)
        if selected == "none":
            return result
        try:
            path = str(result[1])
        except Exception as exc:
            raise MasterExportAudioVerifyError(
                "master export returned no inspectable output path") from exc
        ok, detail = _probe_audio(path, chain_module.av)
        if not ok:
            sidecar = os.path.splitext(path)[0] + ".json"
            # Keep the bad media file for forensic inspection, but invalidate
            # its cache record so the next queue cannot silently reuse it.
            chain_module._safe_unlink(sidecar)
            raise MasterExportAudioVerifyError(
                "H3 Master final expected %s audio but %s: %s. "
                "The cache sidecar was invalidated; this file will not be reused."
                % (selected, path, detail))
        chain_module._LOG.info(
            "H3 Master final audio verified: %s / %s / %s",
            selected, path, detail)
        status = str(result[2]) + " / audio verified"
        return result[0], result[1], status

    setattr(export, _SENTINEL, True)
    export._master_export_audio_verify_original = original_export
    export_cls.export = export

    report = MasterExportAudioVerifyReport(
        activated=True,
        patched=(
            "master_video_export_0637._cache_valid",
            "MiniMaxH3ChainMasterVideoExport.export",
        ),
    )
    setattr(export_module, _SENTINEL, report)
    return report
