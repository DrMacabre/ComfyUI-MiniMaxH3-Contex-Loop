#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(
    new URL("../web/h3_chain_run_manager.js", import.meta.url), "utf8",
);

assert.match(source, /MiniMaxH3ChainRunManager/);
assert.match(source, /MiniMaxH3ChainPlan/);
assert.match(source, /\/minimax_h3_context_loop\/runs/);
assert.match(source, /\/minimax_h3_context_loop\/run\?/);
assert.match(source, /window\.confirm\(message\)/);
assert.match(source, /This replaces all active scene prompts and archived Plan settings/);
assert.match(source, /function applyPlanInputs/);
assert.match(source, /left === "plan_json"/);
assert.match(source, /widget\.callback\?\.\(inputs\[name\]\)/);
assert.match(source, /_h3ChainEditorRefresh/);
assert.match(source, /output\/h3_chains/);
assert.match(source, /Open folder/);
assert.match(source, /navigator\.clipboard\.writeText\(payload\.path\)/);

console.log("H3 Run Manager frontend: discovery, confirmation and Plan restore wiring pass");
