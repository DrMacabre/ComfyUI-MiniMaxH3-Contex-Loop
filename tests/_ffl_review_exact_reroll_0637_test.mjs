import assert from "node:assert/strict";
import fs from "node:fs";
import {
    applyCheckpointRevisionSet,
    applyReviewEdit,
    reviewAcceptedFrameLength,
    reviewFrameLength,
    reviewFrameLengthText,
    reviewPlanSceneLength,
} from "../web/h3_chain_review_core.mjs";

// Exact timeline target from the real Fool for Love Scene 14.
const REQUESTED = 129;
const RAW = 141;
assert.equal(reviewFrameLength(REQUESTED), REQUESTED);
assert.equal(reviewFrameLengthText(REQUESTED), "129");
assert.throws(() => reviewFrameLength(129.5), /integer/);

// Explicit exact metadata always outranks ambiguous/raw response fields.
const exactPayload = {
    length: RAW,
    raw_frames: RAW,
    requested_frames: REQUESTED,
    delivered_frames: REQUESTED,
};
assert.equal(reviewAcceptedFrameLength(exactPayload, REQUESTED), REQUESTED);

// Even if an upstream retry response exposes only the ambiguous raw length,
// the submitted/authored exact length remains authoritative.
assert.equal(reviewAcceptedFrameLength({length: RAW, raw_frames: RAW}, REQUESTED), REQUESTED);
assert.throws(
    () => reviewAcceptedFrameLength({length: RAW, raw_frames: RAW}),
    /exact final frame count/i,
);

const plan = {
    shots: [
        {id: "scene_14", prompt: ["original"], seed: "1", length: REQUESTED},
        {id: "scene_15", prompt: ["next"], seed: "2", length: 255},
    ],
};
assert.equal(reviewPlanSceneLength(plan, 1, "scene_14"), REQUESTED);

// Simulate repeated Review operations. Seed/prompt may change; exact duration may not.
for (const [seed, prompt] of [
    ["2", "reroll one"],
    ["3", "reroll two"],
    ["4", "prompt retry"],
    ["5", "reroll after prompt retry"],
]) {
    const accepted = reviewAcceptedFrameLength(
        {length: RAW, raw_frames: RAW},
        reviewPlanSceneLength(plan, 1, "scene_14"),
    );
    applyReviewEdit(plan, 1, prompt, seed, accepted);
    assert.equal(plan.shots[0].length, REQUESTED);
}

// Candidate acceptance with exact candidate metadata must also stay at 129.
const candidateAccepted = reviewAcceptedFrameLength({
    length: RAW,
    raw_frames: RAW,
    requested_frames: REQUESTED,
    delivered_frames: REQUESTED,
}, reviewPlanSceneLength(plan, 1, "scene_14"));
applyReviewEdit(plan, 1, "accepted candidate", "6", candidateAccepted);
assert.equal(plan.shots[0].length, REQUESTED);

// Exact checkpoint save/reload restores requested/delivered, never RAW 141.
const restored = applyCheckpointRevisionSet({
    prompt_prefix: ["keep"],
    shots: [
        {id: "scene_14", prompt: ["current"], length: REQUESTED, steps: 10, seed: "9"},
        {id: "scene_15", prompt: ["next"], length: 255, steps: 10, seed: "10"},
    ],
}, [{
    scene: 1,
    scene_id: "scene_14",
    scene_prompt: "restored",
    seed: "8",
    requested_frames: REQUESTED,
    delivered_frames: REQUESTED,
    raw_frames: RAW,
    steps: 10,
    prompt_prefix: "keep",
}]);
assert.equal(restored.shots[0].length, REQUESTED);
assert.equal(restored.shots[1].length, 255);

// Serialization round-trip must not promote RAW metadata into authored Plan length.
const roundTrip = JSON.parse(JSON.stringify(restored));
assert.equal(roundTrip.shots[0].length, REQUESTED);

// Downstream edit offsets depend only on delivered/authored lengths.
const offsets = [0];
for (const shot of roundTrip.shots) offsets.push(offsets.at(-1) + shot.length);
assert.deepEqual(offsets, [0, 129, 384]);

// Static guard: Review Final may receive body.length from upstream, but it must
// never write that ambiguous field into the Plan or initialize UI from raw_frames.
const finalSource = fs.readFileSync(
    new URL("../web/h3_chain_review_final.js", import.meta.url), "utf8",
);
assert.doesNotMatch(finalSource, /body\.scene_prompt, body\.seed, body\.length/);
assert.doesNotMatch(finalSource, /acceptedPrompt, body\.seed, body\.length/);
assert.doesNotMatch(finalSource, /reviewDurationText\(data\.raw_frames\)/);
assert.match(finalSource, /Final frames/);
assert.match(finalSource, /exactResponseLength/);
assert.match(finalSource, /length: normalizedLength/);

console.log("PASS Fool for Love Review exact reroll 129 requested / 141 raw regression");
