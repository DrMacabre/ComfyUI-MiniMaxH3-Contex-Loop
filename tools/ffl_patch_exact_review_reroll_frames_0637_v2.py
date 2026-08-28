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

# The first strict patcher correctly failed closed because current 0.6.37 names
# the Review payload identity field `shot_id`, while the historical patch source
# used `scene_id`. Reuse the already-reviewed patch logic with only that exact
# source-identity correction; do not loosen any other source assertions.
path = Path(__file__).with_name("ffl_patch_exact_review_reroll_frames_0637.py")
source = path.read_text(encoding="utf-8")
old = "review?.scene_id,"
new = "review?.shot_id,"
count = source.count(old)
if count != 2:
    raise SystemExit(f"v2 shot_id correction: expected 2 patch-source occurrences, got {count}")
source = source.replace(old, new)
exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})
