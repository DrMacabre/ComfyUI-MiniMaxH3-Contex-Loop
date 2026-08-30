from pathlib import Path

# Preserve the existing requested-vs-raw and backend seed-only reroll contract.
v3 = Path(__file__).with_name("ffl_patch_exact_review_reroll_frames_0637_v3.py")
try:
    exec(compile(v3.read_text(encoding="utf-8"), str(v3), "exec"), {
        "__name__": "__main__",
        "__file__": str(v3),
    })
except SystemExit as exc:
    if exc.code not in (0, None):
        raise

final_path = Path("web/h3_chain_review_final.js")
final = final_path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source block, got {count}")
    return text.replace(old, new, 1)


# A recovered/polled Review payload can lose exact-frame metadata after the UI
# already resolved it successfully. Latch the exact value per live Review token
# instead of recomputing it from the transient payload at click time.
final = replace_once(
    final,
    '''    let current = null;\n    let countdownTimer = null;\n''',
    '''    let current = null;\n    let currentExactFrames = null;\n    let countdownTimer = null;\n''',
    "Review exact-frame latch state",
)

final = replace_once(
    final,
    '''            const normalizedLength = action === "retry"\n                ? reviewFrameLength(duration.value)\n                : action === "reroll"\n                    ? exactResponseLength(node, submittedReview, submittedReview)\n                    : null;\n''',
    '''            const normalizedLength = action === "retry"\n                ? reviewFrameLength(duration.value)\n                : action === "reroll"\n                    ? reviewFrameLength(currentExactFrames)\n                    : null;\n''',
    "Reroll uses latched exact frames",
)

final = replace_once(
    final,
    '''        if (!sameToken) {\n            prompt.value = data.scene_prompt ?? "";\n            promptEditedInGate = false;\n            seed.value = data.seed ?? "";\n            duration.value = reviewFrameLengthText(\n                exactResponseLength(node, data, data));\n''',
    '''        if (!sameToken) {\n            const incomingExactFrames = exactResponseLength(node, data, data);\n            currentExactFrames = incomingExactFrames;\n            prompt.value = data.scene_prompt ?? "";\n            promptEditedInGate = false;\n            seed.value = data.seed ?? "";\n            duration.value = reviewFrameLengthText(incomingExactFrames);\n''',
    "Latch exact frames when Review token arrives",
)

final = replace_once(
    final,
    '''                const acceptedFrames = reviewFrameLengthText(acceptedLength);\n                const saved = updatePlan(\n''',
    '''                const acceptedFrames = reviewFrameLengthText(acceptedLength);\n                currentExactFrames = acceptedLength;\n                const saved = updatePlan(\n''',
    "Refresh exact-frame latch after retry/reroll",
)

final_path.write_text(final, encoding="utf-8")
print("PASS Review reroll exact frames are latched per token")
