from pathlib import Path

# First preserve/apply the existing exact requested-vs-raw Review contract.
v2 = Path(__file__).with_name("ffl_patch_exact_review_reroll_frames_0637_v2.py")
try:
    exec(compile(v2.read_text(encoding="utf-8"), str(v2), "exec"), {
        "__name__": "__main__",
        "__file__": str(v2),
    })
except SystemExit as exc:
    if exc.code not in (0, None):
        raise

chain_path = Path("chain_nodes.py")
final_path = Path("web/h3_chain_review_final.js")
chain = chain_path.read_text(encoding="utf-8")
final = final_path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source block, got {count}")
    return text.replace(old, new, 1)


# Reroll seed is a seed-only operation. Keep both raw H3 grid length and the
# authored/delivered exact length in pending Review state so the backend never
# has to infer the exact duration from raw_frames.
old_pending = '''            "current_seed": int(shot["seed"]),
            "current_length": int(shot["raw_frames"]),
            "candidates": candidates,
'''
new_pending = '''            "current_seed": int(shot["seed"]),
            "current_length": int(shot["raw_frames"]),
            "current_requested_frames": int(shot.get(
                "requested_frames",
                shot.get("delivered_frames", shot["raw_frames"]))),
            "candidates": candidates,
'''
chain = replace_once(
    chain, old_pending, new_pending,
    "pending Review exact requested length",
)

# Retry may explicitly change Final frames. Reroll seed must ignore any UI/body
# duration value and reuse the exact frame count captured when the Review was
# opened. The exact-timeline validator accepts that authored count and computes
# H3 raw 17k+5 padding internally.
old_submit = '''        try:
            raw_frames = _validate_h3_length(
                body.get("length", pending.get("current_length")),
                "H3 review retry length")
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if action == "reroll":
'''
new_submit = '''        try:
            review_length = (
                pending.get("current_requested_frames",
                            pending.get("current_length"))
                if action == "reroll"
                else body.get("length", pending.get("current_length")))
            raw_frames = _validate_h3_length(
                review_length, "H3 review retry length")
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if action == "reroll":
'''
chain = replace_once(
    chain, old_submit, new_submit,
    "backend seed-only reroll exact length",
)

# Frontend mirrors the backend invariant: Retry reads the editable Final frames
# field; Reroll seed derives the current exact count from Review/Plan metadata
# and never from the duration input.
old_frontend = '''            const normalizedSeed = action === "retry" ? reviewSeed(seed.value) : seed.value;
            const normalizedLength = action === "retry" || action === "reroll"
                ? reviewFrameLength(duration.value) : null;
'''
new_frontend = '''            const normalizedSeed = action === "retry" ? reviewSeed(seed.value) : seed.value;
            const normalizedLength = action === "retry"
                ? reviewFrameLength(duration.value)
                : action === "reroll"
                    ? exactResponseLength(node, submittedReview, submittedReview)
                    : null;
'''
final = replace_once(
    final, old_frontend, new_frontend,
    "frontend seed-only reroll exact length",
)

chain_path.write_text(chain, encoding="utf-8")
final_path.write_text(final, encoding="utf-8")
print("PASS exact Review Reroll seed keeps authored final frames")
