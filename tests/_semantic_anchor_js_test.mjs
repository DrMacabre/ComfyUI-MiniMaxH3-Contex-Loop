#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    richGuideInstruction,
    tokenizeRichPrompt,
} from "../web/h3_rich_prompt_editor_core.mjs";

const records = [
    {kind:"picture", token:"@replacement", label:"<Picture 1>", active:true},
    {kind:"video", token:"@performance", label:"<Video 1>", active:true},
];

const parts = tokenizeRichPrompt(
    "Use @replacement and #replacement[0.00s], #replacement[2.50], " +
    "then reject #performance[1.00s] and #missing[1.50s].",
    records,
);
const refs = parts.filter((item) => item.type === "reference");
assert.deepEqual(refs.map((item) => [
    item.text, item.kind, item.semantic, item.timestamp, item.unresolved,
]), [
    ["@replacement", "picture", false, null, false],
    ["#replacement[0.00s]", "picture", true, 0, false],
    ["#replacement[2.50]", "picture", true, 2.5, false],
    ["#performance[1.00s]", "video", true, 1, true],
    ["#missing[1.50s]", "unknown", true, 1.5, true],
]);
assert.equal(parts.map((item) => item.text).join(""),
    "Use @replacement and #replacement[0.00s], #replacement[2.50], " +
    "then reject #performance[1.00s] and #missing[1.50s].");

const instruction = richGuideInstruction("general", "Ref2VA");
assert.match(instruction, /#picture\[timestamp\]/);

console.log("H3 semantic-anchor prompt chips and optimizer preservation pass");
