#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    directOptimizerConfigurationError,
    makeDirectPromptOptimizeRequest,
    normalizePromptOptimizerApiFormat,
    normalizePromptOptimizerBackend,
} from "../web/h3_prompt_optimizer_core.mjs";

assert.equal(normalizePromptOptimizerBackend(undefined), "direct");
assert.equal(normalizePromptOptimizerBackend("MCP"), "mcp");
assert.equal(normalizePromptOptimizerBackend("unknown"), "direct");
assert.equal(normalizePromptOptimizerApiFormat("RESPONSES"), "responses");
assert.equal(normalizePromptOptimizerApiFormat("unknown"), "openai");

assert.match(directOptimizerConfigurationError({}), /URL/);
assert.match(directOptimizerConfigurationError({api_url:"http://localhost:1234"}), /model/);
assert.match(directOptimizerConfigurationError({
    api_url:"https://example.invalid", model:"gemini-test", api_format:"gemini",
}), /API key/);

const resources = [{type:"image", asset:{filename:"hero.png", storage:"input"}}];
const withoutMedia = makeDirectPromptOptimizeRequest({
    config:{api_format:"openai", api_url:"http://localhost:1234/v1", model:"local", allow_media:false},
    instruction:"Polish only the camera move.",
    context:{source_prompt:"A tracking shot."},
    resources,
});
assert.equal(withoutMedia.allow_media, false);
assert.deepEqual(withoutMedia.resources, []);
assert.equal(withoutMedia.api_format, "openai");

const withMedia = makeDirectPromptOptimizeRequest({
    config:{api_format:"gemini", api_url:"https://example.invalid", api_key:"secret", model:"models/gemini-test", allow_media:true},
    instruction:"Check visual continuity.",
    context:{source_prompt:"@hero walks forward."},
    resources,
});
assert.equal(withMedia.allow_media, true);
assert.deepEqual(withMedia.resources, resources);

const settingsSource = fs.readFileSync(
    new URL("../web/h3_prompt_optimizer_settings.js", import.meta.url), "utf8");
assert.match(settingsSource, /defaultValue: "direct"/);
assert.match(settingsSource, /Comfy\.ShowSettingsDialog/);
assert.match(settingsSource, /telemetry: \{trackChanges: false\}/);

console.log("H3 Direct prompt optimizer: settings and request contract pass");
