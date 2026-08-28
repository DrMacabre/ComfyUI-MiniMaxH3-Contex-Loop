#!/usr/bin/env python3
"""Patch the 0.6.37 Plan Studio frontend to mirror Fool for Love exact-final timing.

Authored scene lengths remain exact delivered timeline frames. H3 raw 17k+5
lengths are derived internally from delivered frames plus repeated head context.
This script is intentionally narrow and refuses to apply if the expected 0.6.37
source text has drifted.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "web" / "h3_chain_plan_core.mjs"
TEST = ROOT / "tests" / "_plan_editor_js_test.mjs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


core = CORE.read_text(encoding="utf-8")

core = replace_once(
    core,
    '    const replacement = mode === "frames" ? h3FrameLength(currentSeconds)\n'
    '        : mode === "seconds" ? currentSeconds : null;',
    '    const replacement = mode === "frames" ? requestedFrameLength(currentSeconds)\n'
    '        : mode === "seconds" ? currentSeconds : null;',
    "frame-mode conversion",
)

old_length_block = '''export function validateH3Length(value) {
    const length = Number(value);
    if (!Number.isInteger(length) || length < 5 || length > MAX_H3_FRAMES || length % 17 !== 5) {
        throw new Error(
            `Exact length must be 5..${MAX_H3_FRAMES} frames with length % 17 == 5.`,
        );
    }
    return length;
}

function sceneRawFrames(shot, defaultDuration) {
    if (shot.length !== undefined && shot.length !== null && shot.length !== "") {
        return validateH3Length(shot.length);
    }
    if (shot.frames !== undefined && shot.frames !== null && shot.frames !== "") {
        return validateH3Length(shot.frames);
    }
    const duration = shot.duration_seconds ?? defaultDuration;
    return h3FrameLength(duration);
}
'''

new_length_block = '''export function validateH3Length(value) {
    const length = Number(value);
    if (!Number.isInteger(length) || length < 5 || length > MAX_H3_FRAMES || length % 17 !== 5) {
        throw new Error(
            `Native H3 length must be 5..${MAX_H3_FRAMES} frames with length % 17 == 5.`,
        );
    }
    return length;
}

export function validateRequestedFrameLength(value, label = "Final length") {
    const length = Number(value);
    if (!Number.isInteger(length) || length < 1 || length > MAX_H3_FRAMES) {
        throw new Error(
            `${label} must be 1..${MAX_H3_FRAMES} exact final frames.`,
        );
    }
    return length;
}

export function requestedFrameLength(seconds) {
    const numeric = Number(seconds);
    if (!Number.isFinite(numeric) || numeric <= 0) {
        throw new Error("Duration must be a finite positive number.");
    }
    return validateRequestedFrameLength(
        Math.max(1, Math.round(numeric * FPS)), "Final duration",
    );
}

export function quantizedH3Delivery(deliveredFrames, repeatedHeadFrames = 0) {
    const delivered = validateRequestedFrameLength(deliveredFrames);
    const repeatedHead = Number(repeatedHeadFrames);
    if (!Number.isInteger(repeatedHead) || repeatedHead < 0) {
        throw new Error("Repeated head context must be a non-negative integer.");
    }
    const targetRaw = delivered + repeatedHead;
    let raw = targetRaw + ((5 - (targetRaw % 17)) % 17);
    raw = Math.max(5, raw);
    if (raw > MAX_H3_FRAMES) {
        throw new Error(
            `Final length ${delivered} with ${repeatedHead} repeated context frames needs ${raw} raw frames; H3's largest valid native length is ${MAX_H3_FRAMES}.`,
        );
    }
    return Object.freeze({
        rawFrames: raw,
        deliveredFrames: delivered,
        tailTrimFrames: raw - repeatedHead - delivered,
    });
}

function sceneRequestedFrames(shot, defaultDuration) {
    if (shot.length !== undefined && shot.length !== null && shot.length !== "") {
        return validateRequestedFrameLength(shot.length, "Scene final length");
    }
    if (shot.frames !== undefined && shot.frames !== null && shot.frames !== "") {
        return validateRequestedFrameLength(shot.frames, "Scene final length");
    }
    const duration = shot.duration_seconds ?? defaultDuration;
    return requestedFrameLength(duration);
}
'''
core = replace_once(core, old_length_block, new_length_block, "exact length helpers")

old_timing_block = '''        let rawFrames = 0;
        try {
            rawFrames = sceneRawFrames(shot, planDefaultDuration);
        } catch (error) {
            rowErrors.push(error.message);
        }

        let deliveredFrames = rawFrames;
        let generationStartFrame = stitchedFrames;
        if (index > 1 && anchorMode === "head") {
            if (sceneContext > 0 && rawFrames <= sceneContext) {
                rowErrors.push(
                    `${rawFrames} raw frames are not longer than the ${sceneContext}-frame overlap.`,
                );
            }
            deliveredFrames = Math.max(0, rawFrames - sceneContext);
            generationStartFrame = stitchedFrames - sceneContext;
        }
'''

new_timing_block = '''        let requestedFrames = 0;
        let rawFrames = 0;
        let deliveredFrames = 0;
        let tailTrimFrames = 0;
        let generationStartFrame = stitchedFrames;
        try {
            requestedFrames = sceneRequestedFrames(shot, planDefaultDuration);
            const repeatedHeadFrames = index > 1 && anchorMode === "head"
                ? sceneContext : 0;
            const delivery = quantizedH3Delivery(
                requestedFrames, repeatedHeadFrames,
            );
            rawFrames = delivery.rawFrames;
            deliveredFrames = delivery.deliveredFrames;
            tailTrimFrames = delivery.tailTrimFrames;
            if (index > 1 && anchorMode === "head") {
                generationStartFrame = stitchedFrames - sceneContext;
            }
        } catch (error) {
            rowErrors.push(error.message);
        }
'''
core = replace_once(core, old_timing_block, new_timing_block, "timing calculation")

core = replace_once(
    core,
    '''            rawFrames,
            rawSeconds: rawFrames / FPS,
            deliveredFrames,
            deliveredSeconds: deliveredFrames / FPS,
            generationStartFrame,''',
    '''            requestedFrames,
            rawFrames,
            rawSeconds: rawFrames / FPS,
            deliveredFrames,
            deliveredSeconds: deliveredFrames / FPS,
            tailTrimFrames,
            generationStartFrame,''',
    "timing row fields",
)

CORE.write_text(core, encoding="utf-8")

# Update focused editor/core expectations from legacy authored-raw semantics to
# exact-final authored semantics. Native H3 helpers remain strict and tested.
test = TEST.read_text(encoding="utf-8")
replacements = [
    ('assert.deepEqual(requestedSecondsShot, {length: 243});',
     'assert.deepEqual(requestedSecondsShot, {length: 240});'),
    ('assert.deepEqual(requestedSecondsShot, {duration_seconds: 243 / 24});',
     'assert.deepEqual(requestedSecondsShot, {duration_seconds: 10});'),
    ('assert.deepEqual(inheritedLengthShot, {length: 362});',
     'assert.deepEqual(inheritedLengthShot, {length: 360});'),
    ('assert.throws(() => validateH3Length(240), /length % 17/);',
     'assert.throws(() => validateH3Length(240), /length % 17/);\n'
     'const exactFinalTiming = calculatePlanTiming({shots:[\n'
     '    {id:"exact_a", prompt:"A", length:240},\n'
     '    {id:"exact_b", prompt:"B", length:129},\n'
     ']}, {contextLength:39, anchorMode:"head", defaultDurationSeconds:5});\n'
     'assert.deepEqual(exactFinalTiming.errors, []);\n'
     'assert.deepEqual(exactFinalTiming.shots.map((shot) => shot.deliveredFrames), [240, 129]);\n'
     'assert.deepEqual(exactFinalTiming.shots.map((shot) => shot.rawFrames), [243, 175]);\n'
     'assert.deepEqual(exactFinalTiming.shots.map((shot) => shot.tailTrimFrames), [3, 7]);\n'
     'assert.equal(exactFinalTiming.totalFrames, 369);'),
    ('assert.deepEqual(timing.shots.map((shot) => shot.rawFrames), [362, 260]);',
     'assert.deepEqual(timing.shots.map((shot) => shot.rawFrames), [362, 294]);'),
    ('assert.deepEqual(timing.shots.map((shot) => shot.deliveredFrames), [362, 238]);',
     'assert.deepEqual(timing.shots.map((shot) => shot.deliveredFrames), [360, 260]);'),
    ('assert.equal(timing.shots[1].generationStartFrame, 340);',
     'assert.equal(timing.shots[1].generationStartFrame, 338);'),
    ('assert.equal(timing.totalFrames, 600);',
     'assert.equal(timing.totalFrames, 620);'),
    ('assert.equal(longTiming.totalFrames, 4544);',
     'assert.equal(longTiming.totalFrames, 4800);'),
    ('assert.equal(longTiming.totalSeconds, 189 + 1 / 3);',
     'assert.equal(longTiming.totalSeconds, 200);'),
    ('assert.equal(composedTiming.shots[4].visualContextStartFrame, 17);',
     'assert.equal(composedTiming.shots[4].visualContextStartFrame, 56);'),
    ('assert.equal(composedTiming.shots[4].visualContextLeadStartFrame, 46);',
     'assert.equal(composedTiming.shots[4].visualContextLeadStartFrame, 85);'),
    ('windowedComposition.shots[4].visual_context_start_frame = 0;',
     'windowedComposition.shots[4].visual_context_start_frame = 5;'),
    ('windowedComposition.shots[4].visual_context_lead_start_frame = 29;',
     'windowedComposition.shots[4].visual_context_lead_start_frame = 17;'),
    ('assert.equal(windowedTiming.shots[4].visualContextStartFrame, 0);',
     'assert.equal(windowedTiming.shots[4].visualContextStartFrame, 5);'),
    ('assert.equal(windowedTiming.shots[4].visualContextLeadStartFrame, 29);',
     'assert.equal(windowedTiming.shots[4].visualContextLeadStartFrame, 17);'),
]
for old, new in replacements:
    test = replace_once(test, old, new, f"test expectation: {old[:48]}")
TEST.write_text(test, encoding="utf-8")

print("PASS patched exact-final Plan Studio core and focused JS expectations")
