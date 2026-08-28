from pathlib import Path

core_path = Path("web/h3_chain_review_core.mjs")
final_path = Path("web/h3_chain_review_final.js")
core = core_path.read_text(encoding="utf-8")
final = final_path.read_text(encoding="utf-8")

required_core = (
    'export function reviewFrameLength(value)',
    'export function reviewAcceptedFrameLength(payload, fallback = null)',
    'export function reviewPlanSceneLength(plan, oneBasedIndex, shotId = "")',
    'const normalizedLength = reviewFrameLength(length);',
)
required_final = (
    'durationField.append("Final frames")',
    'length: normalizedLength',
    'exactResponseLength(',
    'reviewFrameLengthText(',
)
forbidden_final = (
    'body.scene_prompt, body.seed, body.length',
    'acceptedPrompt, body.seed, body.length',
    'reviewDurationText(data.raw_frames)',
)

fully_applied = (
    all(item in core for item in required_core)
    and all(item in final for item in required_final)
    and not any(item in final for item in forbidden_final)
)
if fully_applied:
    print("PATCH_EXACT_REVIEW_REROLL_FRAMES_0637_ALREADY_APPLIED")
    raise SystemExit(0)

# Adapt only exact source-shape differences already verified on the 0.6.37
# integration lineage. All functional replacements remain in the v1 patcher.
path = Path(__file__).with_name("ffl_patch_exact_review_reroll_frames_0637.py")
source = path.read_text(encoding="utf-8")

old = "review?.scene_id,"
new = "review?.shot_id,"
count = source.count(old)
if count != 2:
    raise SystemExit(f"v2 shot_id correction: expected 2 patch-source occurrences, got {count}")
source = source.replace(old, new)

# Upstream 0.6.37 has two text-identical candidate Plan-write blocks: approve
# and stop. The v1 patcher intentionally patches them sequentially, but its
# first replace_once would reject the initial count of 2. Preserve fail-closed
# behavior by requiring exactly 2, replacing only the first, then allowing the
# existing second replace_once to consume the remaining occurrence.
old_call = '''final = replace_once(final, old_approve, new_approve, "candidate approval exact length")'''
new_call = '''if final.count(old_approve) != 2:\n    raise SystemExit(\n        f"candidate approval exact length: expected exactly two pre-patch candidate blocks, "\n        f"got {final.count(old_approve)}")\nfinal = final.replace(old_approve, new_approve, 1)'''
count = source.count(old_call)
if count != 1:
    raise SystemExit(f"v2 duplicate candidate correction: expected 1 patch-source call, got {count}")
source = source.replace(old_call, new_call, 1)

exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})
