from pathlib import Path

source = Path("web/h3_chain_review_final.js").read_text(encoding="utf-8")

required = [
    "let currentExactFrames = null;",
    "const incomingExactFrames = exactResponseLength(node, data, data);",
    "currentExactFrames = incomingExactFrames;",
    "duration.value = reviewFrameLengthText(incomingExactFrames);",
    "? reviewFrameLength(currentExactFrames)",
    "currentExactFrames = acceptedLength;",
]
missing = [item for item in required if item not in source]
if missing:
    raise SystemExit(f"missing latched exact-frame invariants: {missing!r}")

forbidden = [
    "? exactResponseLength(node, submittedReview, submittedReview)",
]
present = [item for item in forbidden if item in source]
if present:
    raise SystemExit(f"transient Review metadata still used by reroll: {present!r}")

# Retry is allowed to read the editable field; Reroll must not.
needle = '''const normalizedLength = action === "retry"\n                ? reviewFrameLength(duration.value)\n                : action === "reroll"\n                    ? reviewFrameLength(currentExactFrames)'''
if needle not in source:
    raise SystemExit("retry/reroll length split is not the expected seed-only contract")

print("PASS Review reroll uses immutable exact-frame latch")
