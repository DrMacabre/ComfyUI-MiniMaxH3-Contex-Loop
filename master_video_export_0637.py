"""High-fidelity master video export for MiniMax H3 0.6.37.

This node deliberately exports from checkpointed H3 video latents instead of
from the saved 8-bit scene MP4s. Frames stay float RGB through exact timeline
selection and boundary blending, then quantize only at the selected output
codec/bit depth.
"""
from __future__ import annotations

import gc
import hashlib
import os
import subprocess
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np

from . import chain_nodes as c


MASTER_EXPORT_FORMAT = "h3_master_video_export_v1"
MASTER_CODECS = (
    "h264",
    "h265",
    "ffv1_lossless",
    "uncompressed_rgb",
    "uncompressed_v210",
)
MASTER_BIT_DEPTHS = ("8", "10", "16")
MASTER_QUALITY_MODES = ("crf", "lossless")


def _normalize_export(codec: Any, bit_depth: Any, quality_mode: Any,
                      crf: Any) -> dict[str, Any]:
    codec = str(codec or "h264").strip().lower()
    depth = str(bit_depth or "8").strip()
    quality = str(quality_mode or "crf").strip().lower()
    if codec not in MASTER_CODECS:
        raise ValueError("Unknown H3 master codec %r." % codec)
    if depth not in MASTER_BIT_DEPTHS:
        raise ValueError("H3 master bit depth must be 8, 10, or 16.")
    if quality not in MASTER_QUALITY_MODES:
        raise ValueError("H3 master quality mode must be crf or lossless.")
    crf = max(0, min(51, int(crf)))

    if codec in ("h264", "h265") and depth == "16":
        raise ValueError(
            "%s master export supports 8-bit or 10-bit output, not 16-bit. "
            "Use FFV1 lossless or uncompressed RGB for 16-bit masters."
            % codec.upper())
    if codec == "uncompressed_rgb" and depth != "8":
        raise ValueError(
            "Uncompressed RGB is the edit-friendly RGB24 8-bit profile. For "
            "10-bit uncompressed editing choose uncompressed_v210; for a "
            "16-bit mathematically lossless master choose FFV1.")
    if codec == "uncompressed_v210" and depth != "10":
        raise ValueError(
            "Uncompressed V210 is a fixed 10-bit 4:2:2 format. Set bit_depth "
            "to 10, or choose another codec.")

    effective_quality = quality
    if codec in ("ffv1_lossless", "uncompressed_rgb", "uncompressed_v210"):
        effective_quality = "lossless"

    return {
        "codec": codec,
        "bit_depth": int(depth),
        "quality_mode": effective_quality,
        "crf": crf,
    }


def _codec_layout(config: dict[str, Any]) -> dict[str, Any]:
    codec = config["codec"]
    depth = int(config["bit_depth"])
    quality = config["quality_mode"]
    crf = int(config["crf"])

    if codec == "h264":
        if quality == "lossless" and depth == 8:
            return {
                "extension": ".mp4",
                "encoder": "libx264rgb",
                "pix_fmt": "rgb24",
                "options": ["-preset", "medium", "-crf", "0"],
                "input_depth": 8,
                "label": "H.264 RGB lossless 8-bit",
            }
        pix_fmt = "yuv444p10le" if depth == 10 and quality == "lossless" else (
            "yuv444p" if quality == "lossless" else
            ("yuv420p10le" if depth == 10 else "yuv420p"))
        return {
            "extension": ".mp4",
            "encoder": "libx264",
            "pix_fmt": pix_fmt,
            "options": ["-preset", "medium", "-crf",
                        "0" if quality == "lossless" else str(crf)],
            "input_depth": 16 if depth == 10 else 8,
            "label": "H.264 %d-bit %s" % (depth, quality),
        }

    if codec == "h265":
        pix_fmt = (
            "yuv444p10le" if depth == 10 and quality == "lossless" else
            "yuv444p" if quality == "lossless" else
            "yuv420p10le" if depth == 10 else "yuv420p")
        options = ["-preset", "medium"]
        if quality == "lossless":
            options += ["-x265-params", "lossless=1"]
        else:
            options += ["-crf", str(crf)]
        return {
            "extension": ".mp4",
            "encoder": "libx265",
            "pix_fmt": pix_fmt,
            "options": options + ["-tag:v", "hvc1"],
            "input_depth": 16 if depth == 10 else 8,
            "label": "H.265/HEVC %d-bit %s" % (depth, quality),
        }

    if codec == "ffv1_lossless":
        pix_fmt = {8: "gbrp", 10: "gbrp10le", 16: "gbrp16le"}[depth]
        return {
            "extension": ".mkv",
            "encoder": "ffv1",
            "pix_fmt": pix_fmt,
            "options": ["-level", "3", "-coder", "1", "-context", "1",
                        "-slicecrc", "1"],
            "input_depth": 8 if depth == 8 else 16,
            "label": "FFV1 RGB 4:4:4 lossless %d-bit" % depth,
        }

    if codec == "uncompressed_v210":
        return {
            "extension": ".mov",
            "encoder": "v210",
            "pix_fmt": "yuv422p10le",
            "options": [],
            "input_depth": 16,
            "label": "Uncompressed V210 10-bit 4:2:2",
        }

    return {
        "extension": ".mov",
        "encoder": "rawvideo",
        "pix_fmt": "rgb24",
        "options": [],
        "input_depth": 8,
        "label": "Uncompressed RGB24 8-bit",
    }


def _float_rgb(image: Any) -> np.ndarray:
    """Return contiguous float32 RGB in [0,1] without premature 8-bit quantization."""
    if c.torch is not None and c.torch.is_tensor(image):
        if image.ndim != 3 or int(image.shape[-1]) < 3:
            raise ValueError(
                "H3 master export expected [height,width,channels] IMAGE; got %r."
                % (getattr(image, "shape", None),))
        array = (c.torch.clamp(image[..., :3], 0.0, 1.0)
                 .detach().to(device="cpu", dtype=c.torch.float32).numpy())
        return np.ascontiguousarray(array, dtype=np.float32)

    array = np.asarray(image)
    if array.ndim != 3 or int(array.shape[-1]) < 3:
        raise ValueError(
            "H3 master export expected an RGB frame; got shape %r."
            % (getattr(array, "shape", None),))
    array = array[..., :3]
    if array.dtype == np.uint8:
        array = array.astype(np.float32) / 255.0
    elif array.dtype == np.uint16:
        array = array.astype(np.float32) / 65535.0
    else:
        array = array.astype(np.float32, copy=False)
    return np.ascontiguousarray(np.clip(array, 0.0, 1.0), dtype=np.float32)


def _raw_bytes(array: np.ndarray, input_depth: int) -> bytes:
    if int(input_depth) == 8:
        out = np.clip(array * 255.0, 0.0, 255.0).round().astype(np.uint8)
        return np.ascontiguousarray(out).tobytes()
    out = np.clip(array * 65535.0, 0.0, 65535.0).round().astype("<u2")
    return np.ascontiguousarray(out).tobytes()


class _FFmpegMasterWriter:
    def __init__(self, path: str, fps: int, config: dict[str, Any],
                 metadata: dict[str, Any]):
        self.path = path
        self.fps = int(fps)
        self.config = dict(config)
        self.layout = _codec_layout(config)
        self.metadata = metadata or {}
        self.process = None
        self.stderr = None
        self.metadata_path = None
        self.width = None
        self.height = None
        self.written = 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c._safe_unlink(path)

    def _open(self, width: int, height: int) -> None:
        ffmpeg = c._usable_ffmpeg()
        if ffmpeg is None:
            raise RuntimeError(
                "H3 Master Video Export requires a usable ffmpeg executable.")
        if width < 1 or height < 1:
            raise ValueError("H3 master export received invalid frame geometry.")
        if (self.config["codec"] in ("h264", "h265", "uncompressed_v210")
                and (width % 2 or height % 2)):
            raise ValueError(
                "H3 master export codec %s requires even width and height; got %dx%d."
                % (self.config["codec"], width, height))

        self.width, self.height = int(width), int(height)
        input_pix_fmt = "rgb24" if self.layout["input_depth"] == 8 else "rgb48le"
        self.metadata_path = "%s.%s.ffmetadata" % (self.path, uuid.uuid4().hex)
        c._write_ffmetadata(self.metadata_path, self.metadata)
        stderr_path = "%s.%s.stderr.log" % (self.path, uuid.uuid4().hex)
        self.stderr = open(stderr_path, "w+b")
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", input_pix_fmt,
            "-s:v", "%dx%d" % (width, height),
            "-r", str(self.fps), "-i", "pipe:0",
            "-f", "ffmetadata", "-i", self.metadata_path,
            "-map", "0:v:0", "-map_metadata", "1", "-an",
            "-c:v", self.layout["encoder"],
            "-pix_fmt", self.layout["pix_fmt"],
            *self.layout["options"],
            "-r", str(self.fps),
        ]
        if self.layout["extension"] == ".mp4":
            command += ["-movflags", "use_metadata_tags+faststart"]
        command += [self.path]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=self.stderr)

    def write(self, image: Any) -> None:
        array = _float_rgb(image)
        height, width = int(array.shape[0]), int(array.shape[1])
        if self.process is None:
            self._open(width, height)
        elif width != self.width or height != self.height:
            raise ValueError(
                "H3 master export frame geometry changed from %dx%d to %dx%d."
                % (self.width, self.height, width, height))
        assert self.process is not None and self.process.stdin is not None
        try:
            self.process.stdin.write(_raw_bytes(array, self.layout["input_depth"]))
        except BrokenPipeError as exc:
            raise RuntimeError(self._failure_message("ffmpeg closed its input")) from exc
        self.written += 1

    def _failure_message(self, prefix: str) -> str:
        details = ""
        if self.stderr is not None:
            try:
                self.stderr.flush()
                self.stderr.seek(0)
                details = self.stderr.read().decode("utf-8", errors="replace").strip()
            except Exception:
                details = ""
        return "%s for %s%s" % (
            prefix, self.layout["label"], (":\n" + details) if details else "")

    def close(self) -> None:
        if self.process is None:
            raise RuntimeError("H3 master export wrote no frames.")
        assert self.process.stdin is not None
        try:
            self.process.stdin.close()
            rc = self.process.wait()
            if rc != 0:
                raise RuntimeError(self._failure_message("ffmpeg encode failed"))
        finally:
            self._cleanup_aux()
            self.process = None
        if not os.path.isfile(self.path) or os.path.getsize(self.path) < 1:
            raise RuntimeError("H3 master export encoder produced no output file.")

    def abort(self) -> None:
        if self.process is not None:
            try:
                if self.process.stdin is not None:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self._cleanup_aux()
        c._safe_unlink(self.path)

    def _cleanup_aux(self) -> None:
        if self.stderr is not None:
            stderr_name = getattr(self.stderr, "name", None)
            try:
                self.stderr.close()
            finally:
                if isinstance(stderr_name, str):
                    c._safe_unlink(stderr_name)
            self.stderr = None
        if self.metadata_path:
            c._safe_unlink(self.metadata_path)
            self.metadata_path = None


def _cache_valid(path: str, sidecar_path: str, digest: str,
                 total_frames: int) -> bool:
    if not os.path.isfile(path) or not os.path.isfile(sidecar_path):
        return False
    try:
        record = c._read_json(sidecar_path)
        return (
            isinstance(record, dict)
            and record.get("format") == MASTER_EXPORT_FORMAT
            and bool(record.get("complete"))
            and str(record.get("cache_key") or "") == digest
            and int(record.get("frame_count", -1)) == int(total_frames)
            and int(record.get("file_size", -1)) == os.path.getsize(path)
            and os.path.getsize(path) > 0
        )
    except (OSError, TypeError, ValueError):
        return False


class MiniMaxH3ChainMasterVideoExport:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest": (c.MANIFEST_TYPE, {
                    "tooltip": "Completed H3 checkpoint lineage. The master is "
                               "decoded from saved video latents, not scene MP4s."}),
                "video_vae": ("VAE", {
                    "tooltip": "Original MiniMax H3 video VAE used to decode "
                               "the saved checkpoint latents."}),
                "video_codec": (MASTER_CODECS, {
                    "default": "h265",
                    "tooltip": "H.264/H.265 for delivery, FFV1 for true "
                               "lossless compression, uncompressed_rgb for raw "
                               "RGB24 8-bit, or uncompressed_v210 for standard 10-bit "
                               "4:2:2 editing video."}),
                "bit_depth": (MASTER_BIT_DEPTHS, {
                    "default": "10",
                    "tooltip": "Real output precision. Frames remain float RGB "
                               "through latent decode and boundary blending and "
                               "are quantized only at this export stage."}),
                "quality_mode": (MASTER_QUALITY_MODES, {
                    "default": "lossless",
                    "tooltip": "For H.264/H.265 choose CRF compression or the "
                               "codec's lossless mode. FFV1 and uncompressed "
                               "profiles are always lossless."}),
                "crf": ("INT", {
                    "default": 18, "min": 0, "max": 51,
                    "tooltip": "Used only when H.264/H.265 quality_mode=crf. "
                               "Lower is higher quality; 18 is a strong master "
                               "delivery setting."}),
                "audio_source": (["plan", "source", "generated", "none"], {
                    "default": "plan",
                    "tooltip": "Same audio policy as final H3 assembly."}),
                "blend_schedule": ("STRING", {
                    "default": "plan",
                    "tooltip": "Exact boundary crossfades. plan uses the saved "
                               "incoming-scene blend values."}),
                "decode_buffer": (["disk-backed", "memory"], {
                    "default": "disk-backed",
                    "tooltip": "disk-backed keeps full-chain RAM bounded while "
                               "decoding source latents."}),
                "reuse_cache": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Reuse a master only when checkpoint lineage, "
                               "VAE, blends, audio and export format all match."}),
                "filename": ("STRING", {
                    "default": "master",
                    "tooltip": "Readable basename. A short content hash is "
                               "appended so different master profiles never "
                               "overwrite one another."}),
                "audio_bitrate": ("INT", {
                    "default": 320, "min": 64, "max": 512,
                    "tooltip": "AAC bitrate when audio is included."}),
            },
            "optional": {
                "source_audio": ("AUDIO", {
                    "tooltip": "Legacy source-audio fallback, matching the "
                               "existing Full-Chain Latent Video node."}),
            },
        }

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_path", "status")
    OUTPUT_TOOLTIPS = (
        "File-backed master VIDEO decoded directly from H3 checkpoint latents.",
        "Absolute master path (.mp4, .mkv, or .mov depending on codec).",
        "Codec, true bit depth, scene/frame counts, blend schedule and path.",
    )
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "conditioning/minimax/contex_loop"
    DESCRIPTION = (
        "Create a high-fidelity editing/master video directly from H3 checkpoint "
        "latents. Float RGB is preserved through scene selection and crossfades; "
        "quantization happens only at the selected codec/bit depth.")

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def export(self, manifest, video_vae, video_codec, bit_depth, quality_mode,
               crf, audio_source, blend_schedule, decode_buffer, reuse_cache,
               filename, audio_bitrate, source_audio=None):
        if c._st_load is None or c.torch is None or c.av is None or c.np is None:
            raise RuntimeError(
                "H3 Master Video Export requires safetensors, torch, NumPy, and PyAV.")
        if c._usable_ffmpeg() is None:
            raise RuntimeError("H3 Master Video Export requires ffmpeg.")
        if not isinstance(manifest, dict) or manifest.get("format") != "h3_chain_manifest_v3":
            raise ValueError(
                "H3 Master Video Export requires a complete generated lineage "
                "from Loop End or Checkpoint Manager.")

        config = _normalize_export(video_codec, bit_depth, quality_mode, crf)
        layout = _codec_layout(config)
        segments = c._checkpoint_export_segments(manifest)
        prelude = c._validate_prelude(manifest)
        schedule = c._full_chain_blend_schedule(
            manifest, segments, prelude, blend_schedule)
        selected_audio = str(audio_source or "plan").strip().lower()
        if selected_audio == "plan":
            selected_audio = c._audio_policy_final(manifest)
        if selected_audio not in ("source", "generated", "none"):
            raise ValueError(
                "H3 Master Video Export audio_source must resolve to source, "
                "generated, or none; got %r." % selected_audio)

        prelude_frames = int(prelude["frame_count"]) if prelude else 0
        total_frames = prelude_frames + int(manifest["total_delivered_frames"])
        _, source_identity = c._full_chain_cache_identity(
            manifest, segments, prelude, schedule, selected_audio, video_vae)
        identity = {
            "format": MASTER_EXPORT_FORMAT,
            "source": source_identity,
            "video_export": config,
        }
        digest = hashlib.sha256(
            c._canonical_json(identity).encode("utf-8")).hexdigest()
        run_name = c._safe_name(manifest.get("run_name"), "h3_chain")
        final_dir = os.path.join(c._output_root(), "h3_chains", run_name, "masters")
        os.makedirs(final_dir, exist_ok=True)
        base = c._safe_name(c._expand_filename_date(filename), "master")
        final_path = os.path.join(
            final_dir, "%s_%s%s" % (base, digest[:12], layout["extension"]))
        sidecar_path = os.path.splitext(final_path)[0] + ".json"
        if bool(reuse_cache) and _cache_valid(
                final_path, sidecar_path, digest, total_frames):
            status = "reused H3 master: %s / %d frames -> %s" % (
                layout["label"], total_frames, final_path)
            return (c._native_video_from_path(final_path), final_path, status)

        transaction = uuid.uuid4().hex
        silent_path = os.path.join(
            final_dir, ".%s.%s.video%s" %
            (digest, transaction, layout["extension"]))
        muxed_path = os.path.join(
            final_dir, ".%s.%s.muxed%s" %
            (digest, transaction, layout["extension"]))
        buffer_paths: list[str] = []
        writer = _FFmpegMasterWriter(
            silent_path, c.FPS, config, c._manifest_media_metadata(manifest))
        pending: deque[np.ndarray] = deque()
        decoder_modes: list[str] = []

        records: list[dict[str, Any]] = []
        if prelude is not None:
            records.append({
                "kind": "prelude",
                "input_frames": prelude_frames,
                "blend_frames": 0,
                "path": c._absolute_output_path(prelude["video"]),
            })
        schedule_index = 0
        for segment in segments:
            has_predecessor = bool(records)
            blend = int(schedule[schedule_index]) if has_predecessor else 0
            if has_predecessor:
                schedule_index += 1
            delivered = int(segment["delivered_frames"])
            raw = int(segment["raw_frames"])
            repeated = raw - delivered
            if blend > repeated:
                raise ValueError(
                    "H3 Master Video boundary before clip %d requests %d blend "
                    "frames, but that scene repeats only %d context frames."
                    % (int(segment["index"]), blend, repeated))
            records.append({
                "kind": "segment", "segment": segment,
                "input_frames": delivered + blend,
                "blend_frames": blend,
                "start_frame": repeated - blend,
            })
        if schedule_index != len(schedule):
            raise RuntimeError(
                "H3 Master Video did not consume its complete blend schedule.")

        def consume(iterator: Any, expected: int, blend: int,
                    next_blend: int, label: str) -> None:
            seen = 0
            if writer.written == 0 and not pending:
                for image in iterator:
                    pending.append(_float_rgb(image))
                    seen += 1
                    while len(pending) > next_blend:
                        writer.write(pending.popleft())
            else:
                if len(pending) != blend:
                    raise RuntimeError(
                        "%s retained %d predecessor frames; expected %d."
                        % (label, len(pending), blend))
                iterator = iter(iterator)
                for offset in range(blend):
                    try:
                        incoming = _float_rgb(next(iterator))
                    except StopIteration as exc:
                        raise ValueError("%s ended inside its overlap." % label) from exc
                    previous = pending.popleft()
                    alpha = (offset + 1) / float(blend + 1)
                    mixed = np.clip(
                        previous * (1.0 - alpha) + incoming * alpha,
                        0.0, 1.0).astype(np.float32, copy=False)
                    writer.write(mixed)
                    seen += 1
                for image in iterator:
                    pending.append(_float_rgb(image))
                    seen += 1
                    while len(pending) > next_blend:
                        writer.write(pending.popleft())
            if seen != int(expected):
                raise ValueError(
                    "%s provided %d frames; expected %d."
                    % (label, seen, int(expected)))
            if len(pending) != int(next_blend):
                raise RuntimeError(
                    "%s retained %d frames for the next boundary; expected %d."
                    % (label, len(pending), int(next_blend)))

        try:
            for record_index, record in enumerate(records):
                next_blend = (int(records[record_index + 1]["blend_frames"])
                              if record_index + 1 < len(records) else 0)
                if record["kind"] == "prelude":
                    consume(
                        c._first_video_frames(record["path"], record["input_frames"]),
                        record["input_frames"], 0, next_blend,
                        "H3 master prelude")
                    continue

                segment = record["segment"]
                index = int(segment["index"])
                checkpoint = c._absolute_output_path(segment["checkpoint"])
                tensors = c._st_load(checkpoint)
                video = tensors.get("video")
                if video is None:
                    raise ValueError(
                        "H3 Master Video checkpoint for clip %d has no video latent."
                        % index)
                buffer_path = os.path.join(
                    final_dir, ".%s.%s.clip_%04d.buffer" %
                    (digest, transaction, index))
                images = mapped = None
                try:
                    images, mapped, decoder_mode = c._decode_checkpoint_video_for_streaming(
                        video_vae, video, decode_buffer, buffer_path)
                    decoder_modes.append(decoder_mode)
                    if mapped is not None:
                        buffer_paths.append(buffer_path)
                    raw = int(segment["raw_frames"])
                    if int(images.shape[0]) != raw:
                        raise ValueError(
                            "H3 Master Video decoded %d frames for clip %d; "
                            "checkpoint requires %d."
                            % (int(images.shape[0]), index, raw))
                    start = int(record["start_frame"])
                    stop = start + int(record["input_frames"])
                    consume(
                        images[start:stop], record["input_frames"],
                        record["blend_frames"], next_blend,
                        "H3 master clip %d" % index)
                finally:
                    del images, mapped, video, tensors
                    gc.collect()
                    c._safe_unlink(buffer_path)

            while pending:
                writer.write(pending.popleft())
            writer.close()
            if writer.written != total_frames:
                raise RuntimeError(
                    "H3 Master Video wrote %d frames; expected %d."
                    % (writer.written, total_frames))

            audio = c._full_chain_selected_audio(
                manifest, selected_audio, prelude, source_audio)
            if audio is None:
                os.replace(silent_path, final_path)
            else:
                c._mux_full_chain_adapter_audio(
                    silent_path, audio, muxed_path, int(audio_bitrate), total_frames)
                os.replace(muxed_path, final_path)
                c._safe_unlink(silent_path)
                del audio

            record = {
                "format": MASTER_EXPORT_FORMAT,
                "complete": True,
                "cache_key": digest,
                "identity": identity,
                "frame_count": total_frames,
                "scene_count": len(segments),
                "prelude_frames": prelude_frames,
                "blend_schedule": schedule,
                "audio_source": selected_audio,
                "video_export": config,
                "codec_label": layout["label"],
                "decoder_modes": decoder_modes,
                "file": os.path.basename(final_path),
                "file_size": os.path.getsize(final_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            c._atomic_json(sidecar_path, record)
        except BaseException:
            writer.abort()
            c._safe_unlink(muxed_path)
            c._safe_unlink(silent_path)
            raise
        finally:
            for path in buffer_paths:
                c._safe_unlink(path)

        mode_status = ", ".join(sorted(set(decoder_modes))) or "cached"
        warning = ""
        if prelude is not None and int(config["bit_depth"]) > 8:
            warning = " / prelude source was already 8-bit"
        status = (
            "built H3 master: %s / %d scenes / %d frames / %s / blends [%s] / "
            "audio=%s%s -> %s" %
            (layout["label"], len(segments), total_frames, mode_status,
             ",".join(str(item) for item in schedule), selected_audio,
             warning, final_path))
        c._LOG.info("H3 Chain %s", status)
        return (c._native_video_from_path(final_path), final_path, status)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3ChainMasterVideoExport": MiniMaxH3ChainMasterVideoExport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3ChainMasterVideoExport": "MiniMax H3 Master Video Export",
}
