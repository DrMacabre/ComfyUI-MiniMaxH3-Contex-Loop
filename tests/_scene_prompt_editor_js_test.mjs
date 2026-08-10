import assert from "node:assert/strict";
import fs from "node:fs";
import {
    parsePlanJson,
    planToJson,
    promptTextToLines,
    promptValueToText,
} from "../web/h3_chain_plan_core.mjs";

const plan = parsePlanJson(JSON.stringify({
    prompt_prefix: "Shared identity.",
    shots: [
        {id: "one", prompt: "Old one."},
        {id: "two", prompt: ["Old two.", "", "CAMERA: Wide."]},
    ],
}));
plan.shots[1].prompt = promptTextToLines(
    "Continue the action.\n\n<Picture 1> remains the identity reference.",
);
const saved = parsePlanJson(planToJson(plan));
assert.equal(promptValueToText(saved.shots[0].prompt), "Old one.");
assert.equal(
    promptValueToText(saved.shots[1].prompt),
    "Continue the action.\n\n<Picture 1> remains the identity reference.",
);

const source = fs.readFileSync(
    new URL("../web/h3_chain_scene_prompt_editor.js", import.meta.url),
    "utf8",
);
assert.match(source, /MiniMaxH3ChainScenePromptEditor/);
assert.match(source, /item\.name === "plan_json"/);
assert.match(source, /shot\.prompt = promptTextToLines\(textarea\.value\)/);
assert.match(source, /state\.planWidget\.value = value/);
assert.match(source, /_h3ChainEditorRefresh/);
assert.match(source, /Alt\+Left/);
assert.match(source, /Alt\+Right/);
assert.match(source, /@ Reference/);
assert.match(source, /# Dialogue/);
assert.match(source, /FONT_SIZE_PROPERTY/);
assert.match(source, /window\.setInterval\(\(\) => loadPlan\(false\), 500\)/);

console.log("H3 Scene Prompt companion: Plan synchronization and controls pass");
