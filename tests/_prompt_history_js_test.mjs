#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    orderedPromptRevisions,
    promptRevisionHelp,
    promptRevisionLabel,
    promptRevisionNavigation,
} from "../web/h3_prompt_history_core.mjs";

const history = {
    active_revision: "c",
    revisions: [
        {id: "c", parent_id: "a", created_at: "2026-08-12T12:02:00Z", updated_at: "2026-08-12T12:03:00Z"},
        {id: "a", parent_id: null, created_at: "2026-08-12T12:00:00Z", executed_at: "2026-08-12T12:01:00Z", execution_count: 1},
        {id: "b", parent_id: "a", created_at: "2026-08-12T12:01:30Z", executed_at: "2026-08-12T12:01:45Z", execution_count: 2},
    ],
};

assert.deepEqual(orderedPromptRevisions(history).map((item) => item.id), ["a", "b", "c"]);
const navigation = promptRevisionNavigation(history, "c");
assert.equal(navigation.position, 3);
assert.equal(navigation.total, 3);
assert.equal(navigation.previous.id, "b");
assert.equal(navigation.next, null);
assert.equal(navigation.parentPosition, 1);
assert.match(promptRevisionLabel(navigation, "en-US"), /^Active draft · .* · branched from 1$/);
assert.equal(navigation.isActive, true);
assert.equal(navigation.isExecuted, false);
assert.equal(navigation.isImmutable, false);
assert.match(promptRevisionHelp(navigation), /draft is active in the Plan/);
assert.match(
    promptRevisionLabel(promptRevisionNavigation(history, "b"), "en-US"),
    /^Executed history · .* · branched from 1 · executed 2×$/,
);

console.log("H3 prompt history navigation: ChatGPT-style ordering and labels pass");
