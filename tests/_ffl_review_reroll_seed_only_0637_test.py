from pathlib import Path

chain = Path("chain_nodes.py").read_text(encoding="utf-8")
final = Path("web/h3_chain_review_final.js").read_text(encoding="utf-8")

required_chain = [
    '"current_requested_frames": int(shot.get(',
    'if action == "reroll"',
    'pending.get("current_requested_frames",',
    'review_length, "H3 review retry length"',
]
required_final = [
    'const normalizedLength = action === "retry"',
    '? reviewFrameLength(duration.value)',
    ': action === "reroll"',
    '? reviewFrameLength(currentExactFrames)',
    'length: normalizedLength',
]
forbidden_final = [
    'const normalizedLength = action === "retry" || action === "reroll"',
    '? exactResponseLength(node, submittedReview, submittedReview)',
]

missing = [item for item in required_chain if item not in chain]
missing += [item for item in required_final if item not in final]
forbidden = [item for item in forbidden_final if item in final]
if missing or forbidden:
    raise SystemExit(f"missing={missing!r} forbidden_present={forbidden!r}")

# Contract: only explicit Retry is allowed to consume the editable Final frames
# field. Seed-only Reroll must source the exact frame count latched when the
# Review token arrived, so later polling/recovery metadata cannot change it.
retry_pos = final.index('const normalizedLength = action === "retry"')
reroll_pos = final.index(': action === "reroll"', retry_pos)
field_pos = final.index('? reviewFrameLength(duration.value)', retry_pos)
latch_pos = final.index('? reviewFrameLength(currentExactFrames)', reroll_pos)
if not (retry_pos < field_pos < reroll_pos < latch_pos):
    raise SystemExit("Review Reroll seed exact-frame branch ordering is wrong")

print("PASS Review Reroll seed is seed-only and preserves latched exact final frames")
