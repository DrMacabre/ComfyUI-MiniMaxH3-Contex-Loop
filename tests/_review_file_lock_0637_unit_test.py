from __future__ import annotations

import importlib.util
import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_file_lock_0637", ROOT / "review_file_lock_0637.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary) / "Fool_for_love"
        review_dir = run_dir / "reviews"
        review_dir.mkdir(parents=True)

        current = "clip_0015.currentvideo.currentaudio.review.mp4"
        locked = "clip_0015.oldvideo.oldaudio.review.mp4"
        removable = "clip_0015.oldvideo2.oldaudio2.review.mp4"
        other_scene = "clip_0014.keep.keep.review.mp4"
        for name in (current, locked, removable, other_scene):
            (review_dir / name).write_bytes(b"review")

        calls = []

        def previous_review(plan, segment, audio, retain_previous=False):
            calls.append(bool(retain_previous))
            return ({
                "filename": current,
                "subfolder": "Fool_for_love/reviews",
                "type": "output",
            }, True, "")

        chain = SimpleNamespace(
            _review_video=previous_review,
            _run_dir=lambda plan: str(run_dir),
            _LOG=logging.getLogger("review-file-lock-test"),
        )
        assert MODULE.activate_review_file_lock_guard(chain) == MODULE.BUILD
        assert MODULE.activate_review_file_lock_guard(chain) == MODULE.BUILD

        real_unlink = os.unlink

        def windows_lock(path, *args, **kwargs):
            if os.path.basename(os.fspath(path)) == locked:
                raise PermissionError(32, "file is being used by another process", path)
            return real_unlink(path, *args, **kwargs)

        with patch.object(MODULE.os, "unlink", side_effect=windows_lock):
            result = chain._review_video(
                {"run_name": "Fool_for_love"}, {"index": 15}, object(),
                retain_previous=False)

        assert calls == [True], calls
        assert result[1] is True and result[2] == "", result
        assert (review_dir / current).is_file()
        assert (review_dir / locked).is_file(), "locked stale preview must be retained"
        assert not (review_dir / removable).exists(), "unlocked stale preview should be removed"
        assert (review_dir / other_scene).is_file(), "other scenes must be untouched"

        # Explicit retain_previous still means retain every candidate.  The
        # wrapped native/exact Review always receives True so no Windows-hostile
        # cleanup can happen below this compatibility layer.
        (review_dir / removable).write_bytes(b"review")
        result = chain._review_video(
            {"run_name": "Fool_for_love"}, {"index": 15}, object(),
            retain_previous=True)
        assert calls == [True, True], calls
        assert result[1] is True
        assert (review_dir / removable).is_file()

    print("PASS Windows-safe Segment Review stale-preview cleanup")


if __name__ == "__main__":
    main()
