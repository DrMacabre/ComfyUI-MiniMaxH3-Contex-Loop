import assert from "node:assert/strict";
import fs from "node:fs";
import {
    applySocketPresentation,
    hasSourceTimeline,
    presentationForNode,
    resolveAudioPolicy,
} from "../web/h3_socket_presentation_core.mjs";

class Graph {
    constructor(nodes, links) {
        this._nodes = nodes;
        this.links = links;
        for (const node of nodes) node.graph = this;
    }

    getNodeById(id) {
        return this._nodes.find((node) => node.id === id) ?? null;
    }
}

function node(id, type, inputs = [], outputs = [], widgets = []) {
    return {
        id,
        comfyClass: type,
        inputs: inputs.map(([name, link = null]) => ({name, link})),
        outputs: outputs.map(([name, links = null]) => ({name, links})),
        widgets: widgets.map(([name, value]) => ({name, value})),
        properties: {},
    };
}

const audioPolicy = node(1, "MiniMaxH3AudioPolicy", [], [["audio_policy", [10]]], [
    ["final_audio", "generated"],
    ["source_reference", "off"],
    ["generated_continuity", "on"],
]);
const plan = node(2, "MiniMaxH3ChainPlan", [
    ["audio_policy", 10],
], [["plan", [11]]], [["audio_mode", "source_track"]]);
const start = node(3, "MiniMaxH3ChainLoopStart", [
    ["plan", 11], ["source_audio", null], ["source_timeline", null],
], [["flow", null], ["state", [12]], ["status", null]]);
new Graph([audioPolicy, plan, start], {
    10: {origin_id: 1, target_id: 2},
    11: {origin_id: 2, target_id: 3},
});

assert.deepEqual(resolveAudioPolicy(start), {
    known: true,
    finalAudio: "generated",
    sourceReference: "off",
    generatedContinuity: "on",
    source: "typed",
});
assert.equal(hasSourceTimeline(start), false);

const inputOrder = start.inputs.map((slot) => slot.name);
const outputOrder = start.outputs.map((slot) => slot.name);
const linkIds = start.inputs.map((slot) => slot.link);
applySocketPresentation(start, false);
assert.equal(start.inputs[1].hidden, true, "unused legacy AUDIO is compact");
assert.equal(start.outputs[2].hidden, true, "diagnostic status is compact");
assert.deepEqual(start.inputs.map((slot) => slot.name), inputOrder);
assert.deepEqual(start.outputs.map((slot) => slot.name), outputOrder);
assert.deepEqual(start.inputs.map((slot) => slot.link), linkIds);

applySocketPresentation(start, true);
assert.equal(start.inputs[1].hidden, false);
assert.equal(start.outputs[2].hidden, false);

audioPolicy.widgets.find((item) => item.name === "source_reference").value = "on";
assert.equal(presentationForNode(start, false).hiddenInputs.has("source_audio"), false);

const timeline = node(4, "MiniMaxH3SourceTimeline", [], [["source_timeline", [13]]]);
start.inputs.find((slot) => slot.name === "source_timeline").link = 13;
start.graph = new Graph([audioPolicy, plan, timeline, start], {
    10: {origin_id: 1, target_id: 2},
    11: {origin_id: 2, target_id: 3},
    13: {origin_id: 4, target_id: 3},
});
assert.equal(hasSourceTimeline(start), true);
assert.equal(presentationForNode(start, false).hiddenInputs.has("source_audio"), true);

const current = node(5, "MiniMaxH3ChainCurrent", [["state", 12], ["source_audio", null]], [
    ["state", null], ["source_audio_slice", null], ["status", null],
], [["align_audio_reference", false]]);
start.graph._nodes.push(current);
current.graph = start.graph;
start.graph.links[12] = {origin_id: 3, target_id: 5};
const currentPresentation = presentationForNode(current, false);
assert.equal(currentPresentation.hiddenInputs.has("source_audio"), true);
assert.equal(currentPresentation.hiddenOutputs.has("source_audio_slice"), false,
    "source reference is on, so its output stays available");

const linkedStatus = node(6, "MiniMaxH3ChainSegmentSave", [], [
    ["segment", null], ["status", [22]],
]);
applySocketPresentation(linkedStatus, false);
assert.equal(linkedStatus.outputs[1].hidden, false,
    "existing diagnostic links stay visible and untouched");
assert.deepEqual(linkedStatus.outputs[1].links, [22]);

const transition = node(7, "MiniMaxH3TransitionPolicy", [], [
    ["transition_policy", null], ["continuation_mode", null],
    ["context_length", null], ["status", null],
], [
    ["preset", "guide"], ["expert_override", false],
    ["expert_continuation_mode", "guide"], ["expert_context_length", 22],
]);
let transitionPresentation = presentationForNode(transition, false);
assert.equal(transitionPresentation.hiddenWidgets.has("expert_context_length"), true);
transition.widgets.find((item) => item.name === "expert_override").value = true;
transitionPresentation = presentationForNode(transition, false);
assert.equal(transitionPresentation.hiddenWidgets.has("expert_context_length"), false);

const extensionSource = fs.readFileSync(
    new URL("../web/h3_socket_presentation.js", import.meta.url), "utf8");
assert.match(extensionSource, /Show advanced H3 sockets/);
assert.match(extensionSource, /Hide advanced H3 sockets/);
assert.doesNotMatch(extensionSource, /removeInput|removeOutput/);

console.log("H3 socket presentation: positional compatibility and policy visibility pass");
