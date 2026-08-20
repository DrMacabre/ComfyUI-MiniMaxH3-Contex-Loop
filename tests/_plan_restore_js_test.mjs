#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    refreshRestoredPlanEditors,
    restoreConnectedPolicyInputs,
} from "../web/h3_plan_restore_core.mjs";

function widget(name, value) {
    return {
        name,
        value,
        callback(next) { this.callbackValue = next; },
    };
}

const graph = {
    links: {
        10: {origin_id: 3, target_id: 1},
        12: {origin_id: 2, target_id: 3},
    },
    _nodes: [],
    beforeCount: 0,
    afterCount: 0,
    dirtyCount: 0,
    getNodeById(id) { return this._nodes.find((node) => node.id === id); },
    beforeChange() { this.beforeCount += 1; },
    afterChange() { this.afterCount += 1; },
    setDirtyCanvas() { this.dirtyCount += 1; },
};
const plan = {
    id: 1,
    type: "MiniMaxH3ChainPlan",
    graph,
    inputs: [{name: "chain_policy", link: 10}],
    widgets: [],
    _h3ChainEditorRefresh() { this.refreshCount = (this.refreshCount ?? 0) + 1; },
};
const audio = {
    id: 2,
    type: "MiniMaxH3ChainPolicy",
    graph,
    inputs: [],
    widgets: [
        widget("incoming_transition", "guide"),
        widget("final_audio", "generated"),
        widget("source_reference", "off"),
        widget("generated_continuity", "on"),
    ],
};
const reroute = {
    id: 3,
    type: "Reroute",
    graph,
    inputs: [{name: "", link: 12}],
    widgets: [],
};
const sceneEditor = {
    id: 5,
    type: "MiniMaxH3ChainScenePromptEditor",
    graph,
    _h3ScenePromptEditorRefresh() { this.refreshCount = (this.refreshCount ?? 0) + 1; },
};
const richEditor = {
    id: 6,
    type: "MiniMaxH3ChainRichScenePromptEditor",
    graph,
    _h3RichPromptRefresh() { this.refreshCount = (this.refreshCount ?? 0) + 1; },
};
const studio = {
    id: 7,
    type: "MiniMaxH3ChainPlanStudio",
    graph,
    _h3PlanStudioRefresh() { this.refreshCount = (this.refreshCount ?? 0) + 1; },
};
graph._nodes.push(plan, audio, reroute, sceneEditor, richEditor, studio);

const result = restoreConnectedPolicyInputs(plan, {
    audio_policy: {
        final_audio: "source",
        source_reference: "on",
        generated_continuity: "off",
    },
    transition_policy: {
        preset: "soft_av", expert_override: false,
        expert_continuation_mode: "audio_feathered_av",
        expert_context_length: 39,
    },
}, {audio_context_length: 39});
assert.deepEqual(result, {
    applied: ["audio_policy", "transition_policy"],
    unavailable: [],
});
assert.deepEqual(audio.widgets.map((item) => item.value), [
    "soft_av", "source", "on", "off",
]);
assert.ok(audio.widgets.every((item) => item.callbackValue === item.value));
assert.equal(graph.beforeCount, 1);
assert.equal(graph.afterCount, 1);

refreshRestoredPlanEditors(plan);
assert.equal(plan.refreshCount, 1);
assert.equal(sceneEditor.refreshCount, 1);
assert.equal(richEditor.refreshCount, 1);
assert.equal(studio.refreshCount, 1);

plan.inputs[0].link = null;
const missing = restoreConnectedPolicyInputs(plan, {
    audio_policy: {final_audio: "generated"},
});
assert.deepEqual(missing.applied, []);
assert.match(missing.unavailable[0], /chain_policy.*connect/);

const compactGraph = {
    links: {
        20: {origin_id: 9, target_id: 8},
    },
    _nodes: [],
    beforeChange() {}, afterChange() {}, setDirtyCanvas() {},
    getNodeById(id) { return this._nodes.find((node) => node.id === id); },
};
const compactPlan = {
    id: 8, type: "MiniMaxH3ChainPlan", graph: compactGraph,
    inputs: [{name: "chain_policy", link: 20}], widgets: [],
};
const compactPolicy = {
    id: 9, type: "MiniMaxH3ChainPolicy", graph: compactGraph, inputs: [],
    widgets: [
        widget("incoming_transition", "guide"),
        widget("final_audio", "generated"),
        widget("source_reference", "off"),
        widget("generated_continuity", "on"),
    ],
};
compactGraph._nodes.push(compactPlan, compactPolicy);
const compactResult = restoreConnectedPolicyInputs(compactPlan, {
    audio_policy: {
        final_audio: "source", source_reference: "on",
        generated_continuity: "off",
    },
    transition_policy: {
        preset: "hard_av", expert_override: false,
        expert_continuation_mode: "masked_av", expert_context_length: 39,
    },
}, {audio_context_length: 39});
assert.deepEqual(compactResult, {
    applied: ["audio_policy", "transition_policy"], unavailable: [],
});
assert.deepEqual(compactPolicy.widgets.map((item) => item.value), [
    "hard_av", "source", "on", "off",
]);
const compactMismatch = restoreConnectedPolicyInputs(compactPlan, {
    transition_policy: {
        preset: "hard_av", expert_override: false,
        expert_continuation_mode: "masked_av", expert_context_length: 39,
    },
}, {audio_context_length: 22});
assert.deepEqual(compactMismatch.applied, []);
assert.match(compactMismatch.unavailable[0], /Legacy \/ Expert Policy/);

compactPolicy.type = "MiniMaxH3Legacy04PolicyAdapter";
compactPolicy.widgets = [
    widget("audio_mode", "generated_audio"),
    widget("continuation_mode", "guide"),
    widget("context_length", 22),
    widget("audio_context_length", 22),
];
const legacyResult = restoreConnectedPolicyInputs(compactPlan, {
    audio_policy: {
        final_audio: "source", source_reference: "on",
        generated_continuity: "on",
    },
    transition_policy: {
        preset: "guide", expert_override: true,
        expert_continuation_mode: "drift_control_av",
        expert_context_length: 39,
    },
}, {audio_context_length: 17});
assert.deepEqual(legacyResult, {
    applied: ["audio_policy", "transition_policy"], unavailable: [],
});
assert.deepEqual(compactPolicy.widgets.map((item) => item.value), [
    "source_plus_timeline", "drift_control_av", 39, 17,
]);

console.log("H3 Plan restore: one-wire compact, 0.4 legacy/expert, and prompt refresh pass");
