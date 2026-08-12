#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import {
    RICH_PROMPT_GUIDES,
    normalizeRichGuide,
    optimizerSource,
    richGenerationMode,
    richGuideInstruction,
    tokenizeRichPrompt,
} from "../web/h3_rich_prompt_editor_core.mjs";

const records = [
    {kind:"picture", token:"@hero", label:"<Picture 1>", active:true},
    {kind:"audio", token:"@voice", label:"<Audio 1>", active:true},
];
const tokens = tokenizeRichPrompt(
    "<Subject 1> uses @hero and <Audio 1>. <d>Hello.</d> @missing",
    records,
);
assert.deepEqual(
    tokens.filter((item) => item.type !== "text").map((item) => [item.type, item.kind, item.text, item.unresolved]),
    [
        ["subject", undefined, "<Subject 1>", undefined],
        ["reference", "picture", "@hero", false],
        ["reference", "audio", "<Audio 1>", false],
        ["dialogue", undefined, "<d>", undefined],
        ["dialogue", undefined, "</d>", undefined],
        ["reference", "unknown", "@missing", true],
    ],
);
assert.equal(richGenerationMode("scheduled"), "Ref2VA");
assert.equal(richGenerationMode("native_keyframes"), "I2VA/FL2VA");
assert.equal(normalizeRichGuide("bogus"), "auto");
assert.ok(RICH_PROMPT_GUIDES.some((item) => item.id === "music_video"));
const guidedRefRewrite = richGuideInstruction("music_video", "Ref2VA");
assert.match(guidedRefRewrite, /subject_definitions/);
assert.match(guidedRefRewrite, /lyrics/);
assert.match(guidedRefRewrite, /only when the user explicitly asks for a full H3 rewrite/);
assert.match(guidedRefRewrite, /change only what the request requires/);
assert.match(guidedRefRewrite, /Connected references prove only/);
assert.match(guidedRefRewrite, /Do not invent image content, motion, lyrics, voice, timbre/);
assert.match(guidedRefRewrite, /inside the supplied scene duration/);
const compactRewrite = richGuideInstruction("general", "I2VA/FL2VA");
assert.match(compactRewrite, /keyframe-alignment sentence only when/);
assert.match(compactRewrite, /do not force headings onto a compact prompt/);
assert.equal(optimizerSource("AI result", {source:"Original", result:"AI result"}), "Original");
assert.equal(optimizerSource("Manual edit", {source:"Original", result:"AI result"}), "Manual edit");

const source = fs.readFileSync(
    new URL("../web/h3_chain_rich_scene_prompt_editor.js", import.meta.url),
    "utf8",
);
assert.match(source, /MiniMaxH3ChainRichScenePromptEditor/);
assert.match(source, /edits only the selected scene prompt/i);
assert.match(source, /contentEditable = "true"/);
assert.match(source, /Keep the browser's live DOM and undo transaction intact/);
assert.match(source, /tokenizeRichPrompt/);
assert.match(source, /h3rp-token-picture/);
assert.match(source, /h3rp-token-audio/);
assert.match(source, /h3rp-token-thumb/);
assert.match(source, /h3rp-popover audio/);
assert.match(source, /mediaElement\.controls = true/);
assert.match(source, /Audio never autoplays/);
assert.match(source, /pointerdown.*preventDefault/);
assert.match(source, /produce @@hero/);
assert.match(source, /RICH_PROMPT_GUIDES/);
assert.match(source, /richGuideInstruction/);
assert.match(source, /PromptAssistantClient/);
assert.match(source, /prompt_assist_ready/);
assert.match(source, /optimizerProviders/);
assert.match(source, /providers before the user opens it/);
assert.match(source, /direct HTTP/);
assert.match(source, /Endpoint:/);
assert.match(source, /rebaseActivePromptOntoLivePlan/);
assert.match(source, /publishCompanionScene/);
assert.doesNotMatch(source, /state\.provider === "hermes"/);
assert.match(source, /Optimize/);
assert.match(source, /Apply changed result/);
assert.match(source, /scheduleHistoryDraft/);
assert.match(source, /flushHistoryDraft/);
assert.match(source, /serialize:false/);

console.log("H3 Rich Scene Prompt Editor: tokens, guides, previews, optimizer, and history pass");
