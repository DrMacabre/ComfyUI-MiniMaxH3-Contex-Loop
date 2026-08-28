#!/usr/bin/env python3
"""Conform Review audio to Exact Final Timeline delivered frames.

The normal 0.6.37 Loop Trim removes repeated head context and conforms audio to
its decoded image count. Fool for Love Exact Final Timeline may additionally
carry disposable raw *tail* padding so H3 can generate on the 17k+5 grid.
Segment Save already discards that tail from both final RGB and saved audio,
but Chain Review receives Loop Trim's audio directly. Conform only the Review
copy to segment.delivered_frames so a padded scene remains synchronized without
altering the immutable raw latent/checkpoint.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "exact_final_timeline.py"
source = TARGET.read_text(encoding="utf-8")

marker = "def _review_video_exact("
if marker in source:
    assert "_chain._review_video = _review_video_exact" in source
    assert "_ORIG_REVIEW_VIDEO = _chain._review_video" in source
    print("PASS exact-final review audio patch already present")
    raise SystemExit(0)

anchor_orig = "_ORIG_SELECT_REVIEW_CANDIDATE = _chain._select_review_candidate\n"
if source.count(anchor_orig) != 1:
    raise SystemExit("expected one review-candidate original anchor")
source = source.replace(
    anchor_orig,
    anchor_orig + "_ORIG_REVIEW_VIDEO = _chain._review_video\n",
    1,
)

anchor_install = "    _chain._select_review_candidate = _select_review_candidate_exact\n"
if source.count(anchor_install) != 1:
    raise SystemExit("expected one review-candidate install anchor")
source = source.replace(
    anchor_install,
    anchor_install + "    _chain._review_video = _review_video_exact\n",
    1,
)

anchor_function = "\ndef install() -> str:\n"
if source.count(anchor_function) != 1:
    raise SystemExit("expected one install() anchor")
wrapper = r'''

def _review_video_exact(
        plan: dict[str, Any], segment: dict[str, Any], audio: Any,
        retain_previous: bool = False):
    """Use exact delivered duration for Review without mutating saved RAW AV."""
    if audio is not None and isinstance(segment, dict):
        delivered = int(segment.get(
            "delivered_frames",
            int(segment.get("raw_frames", 0)) -
            int(segment.get("tail_trim_frames", 0))))
        if delivered > 0:
            audio = _trim_audio_to_frames(audio, delivered)
    return _ORIG_REVIEW_VIDEO(
        plan, segment, audio, retain_previous=retain_previous)
'''
source = source.replace(anchor_function, wrapper + anchor_function, 1)
TARGET.write_text(source, encoding="utf-8")

patched = TARGET.read_text(encoding="utf-8")
assert "_ORIG_REVIEW_VIDEO = _chain._review_video" in patched
assert "def _review_video_exact(" in patched
assert "audio = _trim_audio_to_frames(audio, delivered)" in patched
assert "_chain._review_video = _review_video_exact" in patched
print("PASS exact-final Review audio conforms to delivered frames")
