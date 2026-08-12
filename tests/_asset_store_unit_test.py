#!/usr/bin/env python3
"""Standalone saved-run media archive and fallback restoration checks."""

import json
import pathlib
import tempfile

from asset_store import RunAssetStore


def binding(binding_id, role, value, output_type, node_id):
    return {
        "binding_id": binding_id,
        "label": binding_id,
        "role": role,
        "node_id": str(node_id),
        "node_type": {
            "picture": "LoadImage",
            "video": "LoadVideo",
            "audio_reference": "LoadAudio",
            "source_track": "LoadAudio",
        }[role],
        "node_title": binding_id,
        "output_slot": 0,
        "output_type": output_type,
        "widget_name": {
            "picture": "image",
            "video": "file",
            "audio_reference": "audio",
            "source_track": "audio",
        }[role],
        "original_value": value,
    }


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        output = root / "output"
        inputs = root / "input"
        (inputs / "characters").mkdir(parents=True)
        (inputs / "audio").mkdir()
        (inputs / "video").mkdir()
        image = inputs / "characters" / "hero.png"
        audio = inputs / "audio" / "voice.wav"
        video = inputs / "video" / "motion.mp4"
        image.write_bytes(b"image-v1")
        audio.write_bytes(b"audio-v1")
        video.write_bytes(b"video-v1")

        store = RunAssetStore(str(output), str(inputs))
        bindings = [
            binding("hero", "picture", "characters/hero.png", "IMAGE", 911),
            binding("voice", "audio_reference", "audio/voice.wav", "AUDIO", 940),
            binding("motion", "video", "video/motion.mp4", "VIDEO", 1928),
        ]
        saved = store.save("portable", bindings, {
            "images": True, "audio": True, "video": False,
        })
        assert saved["asset_count"] == 3
        assert saved["archived_asset_count"] == 2
        manifest_path = output / saved["manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        by_id = {item["binding_id"]: item for item in manifest["bindings"]}
        assert by_id["hero"]["archive_policy"] == "fallback_copy"
        assert by_id["voice"]["archive"]["sha256"]
        assert by_id["motion"]["archive_policy"] == "path_only"
        assert "archive" not in by_id["motion"]

        # A changed input becomes the active archive while the prior content
        # remains addressable in version history.
        image.write_bytes(b"image-v2")
        saved = store.save("portable", bindings, {
            "images": True, "audio": True, "video": False,
        })
        hero = next(item for item in saved["bindings"]
                    if item["binding_id"] == "hero")
        assert len(hero["versions"]) == 1
        assert hero["versions"][0]["sha256"] != hero["archive"]["sha256"]

        # Original input paths win. Missing originals materialize archived
        # fallbacks at the input root so stock loader validation can see them.
        first_restore = store.prepare_restore("portable")
        first = {item["binding_id"]: item for item in first_restore["bindings"]}
        assert first["hero"]["restore_source"] == "original_input"
        image.unlink()
        audio.unlink()
        video.unlink()
        fallback = store.prepare_restore("portable")
        restored = {item["binding_id"]: item for item in fallback["bindings"]}
        assert restored["hero"]["restore_source"] == "archived_fallback"
        assert restored["voice"]["restore_source"] == "archived_fallback"
        assert restored["motion"]["restore_source"] == "missing"
        assert (inputs / restored["hero"]["restore_value"]).read_bytes() == b"image-v2"
        assert (inputs / restored["voice"]["restore_value"]).read_bytes() == b"audio-v1"

        # Browser-supplied traversal and non-input annotations cannot expose
        # arbitrary host files through this recovery feature.
        unsafe = store.save("unsafe", [
            binding("escape", "picture", "../secret.png", "IMAGE", 1),
            binding("output", "picture", "foo.png [output]", "IMAGE", 2),
        ], {"images": True})
        assert unsafe["archived_asset_count"] == 0
        assert len(unsafe["warnings"]) == 2

        # Changing a loader to an unavailable filename must not silently use
        # the prior file as the active fallback for the new binding value.
        alternate = inputs / "alternate.png"
        alternate.write_bytes(b"alternate")
        original = binding("replace", "picture", "alternate.png", "IMAGE", 3)
        store.save("replacement", [original], {"images": True})
        changed = dict(original, original_value="missing.png")
        replaced = store.save("replacement", [changed], {"images": True})
        replaced_binding = replaced["bindings"][0]
        assert "archive" not in replaced_binding
        assert len(replaced_binding["versions"]) == 1
        assert store.prepare_restore("replacement")["bindings"][0][
            "restore_source"] == "missing"

    print("H3 run assets: policies, versions, safe paths and fallback restore pass")


if __name__ == "__main__":
    main()
