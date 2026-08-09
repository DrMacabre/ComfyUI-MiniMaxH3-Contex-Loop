import assert from "node:assert/strict";
import {
    applyReviewEdit,
    reviewCountdown,
    reviewSeed,
} from "../web/h3_chain_review_core.mjs";

assert.equal(reviewSeed("18446744073709551615"), "18446744073709551615");
assert.throws(() => reviewSeed("18446744073709551616"), /uint64/);

const plan = {
    prompt_prefix: ["Keep identity."],
    shots: [
        {id: "one", prompt: ["Old one."], seed: "1"},
        {id: "two", prompt: ["Old two."], seed: "2"},
    ],
};
applyReviewEdit(plan, 2, "New two.\n\nCAMERA: Close-up.", "9007199254740993");
assert.deepEqual(plan.shots[0].prompt, ["Old one."]);
assert.deepEqual(plan.shots[1].prompt, ["New two.", "", "CAMERA: Close-up."]);
assert.equal(plan.shots[1].seed, "9007199254740993");

assert.deepEqual(reviewCountdown(130, 100_000), {seconds: 30, text: "0:30"});
assert.deepEqual(reviewCountdown(100, 100_001), {seconds: 0, text: "0:00"});
assert.equal(reviewCountdown(null, 0), null);

console.log("H3 Chain Review editor helpers: ok");
