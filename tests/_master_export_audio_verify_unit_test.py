#!/usr/bin/env python3
"""CPU regression for fail-closed master export audio verification."""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "master_export_audio_verify_0637.py")


def _load_module():
    name = "master_export_audio_verify_0637_tested"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load master_export_audio_verify_0637.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Frame:
    samples = 1024
    sample_rate = 48000


class _Streams:
    def __init__(self, has_audio):
        self.audio = [object()] if has_audio else []


class _Container:
    def __init__(self, has_audio=True, decodes=True):
        self.streams = _Streams(has_audio)
        self.decodes = decodes

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def decode(self, audio=0):
        if self.decodes:
            yield _Frame()
        return


class _Av:
    def __init__(self, has_audio=True, decodes=True):
        self.has_audio = has_audio
        self.decodes = decodes

    def open(self, path):
        return _Container(self.has_audio, self.decodes)


def main():
    m = _load_module()
    with tempfile.TemporaryDirectory() as temp:
        media = os.path.join(temp, "master.mp4")
        sidecar = os.path.join(temp, "master.json")
        open(media, "wb").write(b"video")

        def read_json(path):
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)

        def atomic_json(path, value):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(value, handle)

        atomic_json(sidecar, {"audio_source": "generated"})

        ok, detail = m._probe_audio(media, _Av(True, True))
        assert ok and "decodes" in detail
        ok, detail = m._probe_audio(media, _Av(False, True))
        assert not ok and "no audio stream" in detail
        ok, detail = m._probe_audio(media, _Av(True, False))
        assert not ok and "no decodable frame" in detail

        chain = types.SimpleNamespace(
            _audio_policy_final=lambda manifest: manifest.get("audio", "generated"),
            _read_json=read_json,
            _atomic_json=atomic_json,
            _safe_unlink=lambda path: os.path.exists(path) and os.unlink(path),
            av=_Av(True, True),
            _LOG=logging.getLogger("master_export_audio_verify_test"),
        )

        class Export:
            def export(self, manifest, video_vae, video_codec, bit_depth,
                       quality_mode, crf, audio_source, blend_schedule,
                       decode_buffer, reuse_cache, filename, audio_bitrate,
                       source_audio=None):
                return "video", media, "built"

        export_module = types.SimpleNamespace(
            _cache_valid=lambda path, sidecar_path, digest, total_frames: True,
            MiniMaxH3ChainMasterVideoExport=Export,
        )
        report = m.activate_master_export_audio_verify(export_module, chain)
        assert report.activated

        # A pre-fix master with a valid audio stream but no assembly-version
        # marker must be rejected from cache.
        assert not export_module._cache_valid(media, sidecar, "x", 10)

        # Fresh successful export stamps the boundary-safe assembly version.
        result = Export().export(
            {"audio": "generated"}, None, "h264", "8", "crf", 20,
            "plan", "plan", "disk-backed", True, "master", 256)
        assert result[1] == media
        assert "audio verified" in result[2]
        assert m.AUDIO_ASSEMBLY_VERSION in result[2]
        persisted = read_json(sidecar)
        assert persisted["audio_assembly_version"] == m.AUDIO_ASSEMBLY_VERSION
        assert export_module._cache_valid(media, sidecar, "x", 10)

        # Cached output that claims generated audio but lacks a stream must be
        # rejected rather than reused.
        chain.av = _Av(False, True)
        assert not export_module._cache_valid(media, sidecar, "x", 10)

        # A freshly returned silent final fails closed and invalidates sidecar.
        atomic_json(sidecar, {
            "audio_source": "generated",
            "audio_assembly_version": m.AUDIO_ASSEMBLY_VERSION,
        })
        try:
            Export().export(
                {"audio": "generated"}, None, "h264", "8", "crf", 20,
                "plan", "plan", "disk-backed", True, "master", 256)
        except m.MasterExportAudioVerifyError as exc:
            assert "expected generated audio" in str(exc)
        else:
            raise AssertionError("silent generated master must fail closed")
        assert not os.path.exists(sidecar)

    print("PASS fail-closed master export audio verification + cache versioning")


if __name__ == "__main__":
    main()
