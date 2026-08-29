from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_cleanup_win32_0637", ROOT / "review_cleanup_win32_0637.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SharingViolation(PermissionError):
    def __init__(self, path: str):
        super().__init__(13, "file is being used by another process", path)
        self.winerror = 32


def main() -> None:
    calls = []

    def failing_unlink(path):
        calls.append(str(path))
        raise SharingViolation(str(path))

    chain = SimpleNamespace(
        _safe_unlink=failing_unlink,
        _LOG=None,
    )

    assert MODULE.activate_review_cleanup_win32_guard(chain) == MODULE.BUILD
    assert MODULE.activate_review_cleanup_win32_guard(chain) == MODULE.BUILD

    stale = r"G:\run\reviews\clip_0015.old.old.review.mp4"
    chain._safe_unlink(stale)
    assert calls == [stale]

    temporary = r"G:\run\reviews\.review.abc123.mp4"
    try:
        chain._safe_unlink(temporary)
    except SharingViolation:
        pass
    else:
        raise AssertionError("temporary Review mux errors must still propagate")

    unrelated = r"G:\run\segments\clip_0015.mp4"
    try:
        chain._safe_unlink(unrelated)
    except SharingViolation:
        pass
    else:
        raise AssertionError("non-Review cleanup errors must still propagate")

    wrong_parent = r"G:\other\clip_0015.old.old.review.mp4"
    try:
        chain._safe_unlink(wrong_parent)
    except SharingViolation:
        pass
    else:
        raise AssertionError("Review-looking files outside reviews/ must propagate")

    print("PASS narrow WinError32 Segment Review cache guard")


if __name__ == "__main__":
    main()
