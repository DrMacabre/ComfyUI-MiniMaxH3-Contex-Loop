#!/usr/bin/env python3
"""Static regression for the master-facing web UI simplification layer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "web" / "h3_master_simple_ui.js").read_text(encoding="utf-8")

required = (
    ".h3studio-audio-overrides",
    ".h3studio-panel:has(> .h3studio-advanced[open]) > .h3studio-audio-overrides",
    ".h3c-audio-fields",
    ".h3c-editor.h3c-show-advanced .h3c-audio-fields",
)
for token in required:
    assert token in text, token

assert "display: none !important" in text
assert text.count("display: grid !important") >= 2

print("PASS master UI hides low-level scene audio plumbing by default")
