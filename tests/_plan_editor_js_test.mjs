#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    calculatePlanTiming,
    duplicateShot,
    h3FrameLength,
    moveShot,
    parsePlanJson,
    planToJson,
    promptValueToText,
    setSharedPrompt,
    sharedPrompt,
    validateH3Length,
} from "../web/h3_chain_plan_core.mjs";

const plan = parsePlanJson(JSON.stringify({
    prompt_prefix: ["Identity.", "", "Wardrobe."],
    defaults: {duration_seconds: 15, steps: 20},
    shots: [
        {id: "one", prompt: "Opening.\nKeep moving.", seed: 18446744073709551615n.toString()},
        {id: "two", prompt: ["Continue.", "", "End turning."], length: 260},
    ],
}));

assert.equal(sharedPrompt(plan).text, "Identity.\n\nWardrobe.");
assert.equal(promptValueToText(plan.shots[0].prompt), "Opening.\nKeep moving.");
setSharedPrompt(plan, "New identity.\n\nNew wardrobe.");
assert.deepEqual(plan.prompt_prefix, ["New identity.", "", "New wardrobe."]);
assert.equal(JSON.parse(planToJson(plan)).shots[0].seed, "18446744073709551615");

const numericSeed = parsePlanJson(
    '{"shots":[{"id":"seed","prompt":"x","seed":18446744073709551615}]}',
);
assert.equal(numericSeed.shots[0].seed, "18446744073709551615");
const promptContainingSeedText = parsePlanJson(
    '{"shots":[{"prompt":"Literal \\\"seed\\\": 18446744073709551615 text"}]}',
);
assert.equal(
    promptValueToText(promptContainingSeedText.shots[0].prompt),
    'Literal "seed": 18446744073709551615 text',
);

assert.equal(h3FrameLength(5), 124);
assert.equal(h3FrameLength(10), 243);
assert.equal(h3FrameLength(15), 362);
assert.equal(validateH3Length(260), 260);
assert.throws(() => validateH3Length(240), /length % 17/);

const timing = calculatePlanTiming(plan, {
    contextLength: 22,
    anchorMode: "head",
    defaultDurationSeconds: 5,
    defaultSteps: 10,
});
assert.deepEqual(timing.shots.map((shot) => shot.rawFrames), [362, 260]);
assert.deepEqual(timing.shots.map((shot) => shot.deliveredFrames), [362, 238]);
assert.equal(timing.shots[1].generationStartFrame, 340);
assert.equal(timing.totalFrames, 600);
assert.deepEqual(timing.errors, []);

const longPlan = parsePlanJson(JSON.stringify({
    defaults: {duration_seconds: 15, steps: 5},
    shots: Array.from({length: 14}, (_, index) => ({
        id: `clip_${String(index + 1).padStart(2, "0")}`,
        prompt: `Scene ${index + 1}`,
        ...(index === 13 ? {duration_seconds: 5} : {}),
    })),
}));
const longTiming = calculatePlanTiming(longPlan, {
    contextLength: 22,
    anchorMode: "head",
    defaultDurationSeconds: 15,
    defaultSteps: 20,
});
assert.equal(longTiming.totalFrames, 4544);
assert.equal(longTiming.totalSeconds, 189 + 1 / 3);
assert.deepEqual(longTiming.errors, []);

duplicateShot(plan.shots, 0);
assert.equal(plan.shots.length, 3);
assert.equal(plan.shots[1].id, "one_copy");
moveShot(plan.shots, 1, 2);
assert.equal(plan.shots[2].id, "one_copy");

const readable = JSON.parse(planToJson(plan));
assert.deepEqual(readable.prompt_prefix, ["New identity.", "", "New wardrobe."]);
assert.deepEqual(readable.shots[0].prompt, ["Opening.", "Keep moving."]);

const editorSource = fs.readFileSync(
    new URL("../web/h3_chain_plan_editor.js", import.meta.url),
    "utf8",
);
assert.match(editorSource, /collapseWidget\(planWidget\)/);
assert.match(editorSource, /display[^\n]+none[^\n]+important/);

console.log("H3 Chain Plan editor core: parsing, uint64 seeds, timing and edits pass");
