from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match, got {count}")
    return text.replace(old, new, 1)


core_path = Path("web/h3_chain_review_core.mjs")
final_path = Path("web/h3_chain_review_final.js")
core = core_path.read_text(encoding="utf-8")
final = final_path.read_text(encoding="utf-8")

# Keep the legacy seconds/H3 helpers for compatibility, but add a separate
# exact-final-frame API. Runtime Review retry/reroll will use only this API.
marker = '''export function reviewPlanScenePrompt(plan, oneBasedIndex, shotId = "") {
'''
insert = '''export function reviewFrameLength(value) {
    const length = Number(value);
    if (!Number.isInteger(length) || length < 1 || length > MAX_H3_FRAMES) {
        throw new Error(`Final frame count must be an integer between 1 and ${MAX_H3_FRAMES}.`);
    }
    return length;
}

export function reviewFrameLengthText(value) {
    return String(reviewFrameLength(value));
}

export function reviewAcceptedFrameLength(payload, fallback = null) {
    for (const value of [payload?.requested_frames, payload?.delivered_frames, fallback]) {
        if (value === null || value === undefined || value === "") continue;
        return reviewFrameLength(value);
    }
    throw new Error("Review response does not expose an exact final frame count.");
}

export function reviewPlanScenePrompt(plan, oneBasedIndex, shotId = "") {
'''
core = replace_once(core, marker, insert, "insert exact Review frame helpers")

prompt_block = '''export function applyReviewEdit(plan, oneBasedIndex, scenePrompt, seed, length = null) {
'''
plan_length_helper = '''export function reviewPlanSceneLength(plan, oneBasedIndex, shotId = "") {
    if (!Array.isArray(plan?.shots)) return null;
    const index = Number(oneBasedIndex) - 1;
    const wantedId = String(shotId ?? "").trim();
    const shot = (wantedId
        ? plan.shots.find((item) => String(item?.id ?? "").trim() === wantedId)
        : null) ?? (Number.isInteger(index) ? plan.shots[index] : null);
    if (!shot) return null;
    const value = shot.length ?? shot.frames;
    if (value === null || value === undefined || value === "") return null;
    return reviewFrameLength(value);
}

export function applyReviewEdit(plan, oneBasedIndex, scenePrompt, seed, length = null) {
'''
core = replace_once(core, prompt_block, plan_length_helper, "insert authored Plan exact-length helper")

old_apply = '''    if (length !== null && length !== undefined) {
        const normalizedLength = Number(length);
        if (!Number.isInteger(normalizedLength) || normalizedLength < 5
                || normalizedLength > MAX_H3_FRAMES
                || normalizedLength % 17 !== 5) {
            throw new Error("Length must be an H3-valid frame count (17k+5).");
        }
        plan.shots[index].length = normalizedLength;
        delete plan.shots[index].frames;
        delete plan.shots[index].duration_seconds;
    }
'''
new_apply = '''    if (length !== null && length !== undefined) {
        const normalizedLength = reviewFrameLength(length);
        plan.shots[index].length = normalizedLength;
        delete plan.shots[index].frames;
        delete plan.shots[index].duration_seconds;
    }
'''
core = replace_once(core, old_apply, new_apply, "make applyReviewEdit final-frame exact")

old_restore = '''        const length = Number(revision.raw_frames);
        if (!Number.isInteger(length) || length < 5 || length > MAX_H3_FRAMES
                || length % 17 !== 5) {
            throw new Error(`Restored scene ${scene} has an invalid H3 frame length.`);
        }
'''
new_restore = '''        const hasExactLength = revision.requested_frames !== null
            && revision.requested_frames !== undefined
            || revision.delivered_frames !== null
            && revision.delivered_frames !== undefined;
        const length = hasExactLength
            ? reviewAcceptedFrameLength(revision)
            : Number(revision.raw_frames);
        if (!hasExactLength && (!Number.isInteger(length) || length < 5
                || length > MAX_H3_FRAMES || length % 17 !== 5)) {
            throw new Error(`Restored legacy scene ${scene} has an invalid H3 frame length.`);
        }
'''
core = replace_once(core, old_restore, new_restore, "restore exact requested checkpoint length")

# Review Final must operate on exact integer frame counts. Never let body.length
# or raw_frames become the authored Plan duration.
old_import = '''    checkpointRevisionChain,
    checkpointResumeOptions,
    reviewCountdown,
    reviewDuration,
    reviewDurationText,
    reviewLocalDeadline,
    reviewPlanScenePrompt,
    reviewSeed,
'''
new_import = '''    checkpointRevisionChain,
    checkpointResumeOptions,
    reviewAcceptedFrameLength,
    reviewCountdown,
    reviewFrameLength,
    reviewFrameLengthText,
    reviewLocalDeadline,
    reviewPlanSceneLength,
    reviewPlanScenePrompt,
    reviewSeed,
'''
final = replace_once(final, old_import, new_import, "switch Review Final imports to exact-frame API")

old_ui = '''    durationField.append("Duration (s)");
    const duration = document.createElement("input");
    duration.className = "h3r-duration";
    duration.type = "number";
    duration.inputMode = "decimal";
    duration.min = String(5 / 24);
    duration.max = String(3592 / 24);
    duration.step = String(17 / 24);
    duration.title = "Generated scene duration. Retry and Reroll round this upward to H3's exact 17k+5 frame grid, revise the full Plan, and retime downstream scenes. Prompt wording and written timestamps are not changed.";
'''
new_ui = '''    durationField.append("Final frames");
    const duration = document.createElement("input");
    duration.className = "h3r-duration";
    duration.type = "number";
    duration.inputMode = "numeric";
    duration.min = "1";
    duration.max = "3592";
    duration.step = "1";
    duration.title = "Exact final timeline frame count. H3 raw 17k+5 padding is computed internally and never replaces this authored duration.";
'''
final = replace_once(final, old_ui, new_ui, "make Review UI exact final frames")

old_norm = '''            const normalizedDuration = action === "retry" || action === "reroll"
                ? reviewDuration(duration.value) : null;
'''
new_norm = '''            const normalizedLength = action === "retry" || action === "reroll"
                ? reviewFrameLength(duration.value) : null;
'''
final = replace_once(final, old_norm, new_norm, "normalize exact retry/reroll frames")
final = replace_once(
    final,
    '''                    length: normalizedDuration?.length,\n''',
    '''                    length: normalizedLength,\n''',
    "submit exact requested length",
)

# Add a safe authored-length resolver next to the existing Plan prompt resolver.
needle = '''function planScenePrompt(reviewNode, review) {
    try {
        const planNode = upstreamPlanNode(reviewNode);
        const widget = widgetByName(planNode, "plan_json");
        if (!widget) return null;
        return reviewPlanScenePrompt(
            parsePlanJson(String(widget.value ?? "")),
            review?.clip_index,
            review?.scene_id,
        );
    } catch (_error) {
        return null;
    }
}
'''
replacement = needle + '''\nfunction planSceneLength(reviewNode, review) {
    try {
        const planNode = upstreamPlanNode(reviewNode);
        const widget = widgetByName(planNode, "plan_json");
        if (!widget) return null;
        return reviewPlanSceneLength(
            parsePlanJson(String(widget.value ?? "")),
            review?.clip_index,
            review?.scene_id,
        );
    } catch (_error) {
        return null;
    }
}

function exactResponseLength(reviewNode, review, payload, fallback = null) {
    const authored = fallback ?? planSceneLength(reviewNode, review);
    return reviewAcceptedFrameLength(payload, authored);
}
'''
final = replace_once(final, needle, replacement, "add exact Review response resolver")

# Checkpoint lineage activation: body.length is ambiguous/raw in upstream.
old_checkpoint = '''    const saved = updatePlan(
        reviewNode, clipIndex, body.scene_prompt, body.seed, body.length);
'''
new_checkpoint = '''    const acceptedLength = exactResponseLength(
        reviewNode,
        {clip_index: clipIndex, scene_id: body.scene_id ?? ""},
        body,
    );
    const saved = updatePlan(
        reviewNode, clipIndex, body.scene_prompt, body.seed, acceptedLength);
'''
final = replace_once(final, old_checkpoint, new_checkpoint, "checkpoint activation exact length")

old_approve = '''                const selected = Number(body.candidate_count) > 1;
                const saved = selected && updatePlan(
                    node, submittedIndex, body.scene_prompt, body.seed, body.length);
'''
new_approve = '''                const selected = Number(body.candidate_count) > 1;
                const acceptedLength = selected
                    ? exactResponseLength(node, submittedReview, body)
                    : null;
                const saved = selected && updatePlan(
                    node, submittedIndex, body.scene_prompt, body.seed, acceptedLength);
'''
final = replace_once(final, old_approve, new_approve, "candidate approval exact length")

old_retry = '''            } else if (action === "retry" || action === "reroll") {
                const acceptedPrompt = typeof body.scene_prompt === "string"
                    ? body.scene_prompt : submittedPrompt.trim();
                const acceptedDuration = reviewDurationText(body.length);
                const saved = updatePlan(
                    node, submittedIndex, acceptedPrompt, body.seed, body.length);
                if (current?.token === submittedToken) {
                    prompt.value = acceptedPrompt;
                    promptEditedInGate = false;
                    seed.value = body.seed;
                    duration.value = acceptedDuration;
                }
                status.textContent = `Retrying scene with seed ${body.seed} at ${body.length} frames (${acceptedDuration}s).` +
                    (saved ? " The Plan editor was updated." : "");
'''
new_retry = '''            } else if (action === "retry" || action === "reroll") {
                const acceptedPrompt = typeof body.scene_prompt === "string"
                    ? body.scene_prompt : submittedPrompt.trim();
                const acceptedLength = exactResponseLength(
                    node, submittedReview, body, normalizedLength);
                const acceptedFrames = reviewFrameLengthText(acceptedLength);
                const saved = updatePlan(
                    node, submittedIndex, acceptedPrompt, body.seed, acceptedLength);
                if (current?.token === submittedToken) {
                    prompt.value = acceptedPrompt;
                    promptEditedInGate = false;
                    seed.value = body.seed;
                    duration.value = acceptedFrames;
                }
                status.textContent = `Retrying scene with seed ${body.seed} at ${acceptedLength} final frames.` +
                    (saved ? " The Plan editor was updated." : "");
'''
final = replace_once(final, old_retry, new_retry, "retry/reroll ignores ambiguous body.length")

old_stop = '''                const selected = Number(body.candidate_count) > 1;
                const saved = selected && updatePlan(
                    node, submittedIndex, body.scene_prompt, body.seed, body.length);
'''
new_stop = '''                const selected = Number(body.candidate_count) > 1;
                const acceptedLength = selected
                    ? exactResponseLength(node, submittedReview, body)
                    : null;
                const saved = selected && updatePlan(
                    node, submittedIndex, body.scene_prompt, body.seed, acceptedLength);
'''
final = replace_once(final, old_stop, new_stop, "candidate stop exact length")

old_open = '''            duration.value = reviewDurationText(data.raw_frames);
'''
new_open = '''            duration.value = reviewFrameLengthText(
                exactResponseLength(node, data, data));
'''
final = replace_once(final, old_open, new_open, "open Review from authored/requested length")

# No duration-writing path may still feed body.length into the Plan.
for forbidden in (
    "body.scene_prompt, body.seed, body.length",
    "acceptedPrompt, body.seed, body.length",
    "reviewDuration(duration.value)",
    "reviewDurationText(data.raw_frames)",
):
    if forbidden in final:
        raise SystemExit(f"forbidden raw/ambiguous Review duration path remains: {forbidden}")

core_path.write_text(core, encoding="utf-8")
final_path.write_text(final, encoding="utf-8")
print("PATCH_EXACT_REVIEW_REROLL_FRAMES_0637_PASS")
