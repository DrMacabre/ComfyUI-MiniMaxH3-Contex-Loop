#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    applyAssetBinding,
    collectAssetBindings,
    findAssetTarget,
    inferAssetRole,
} from "../web/h3_run_assets_core.mjs";

function loader(id, type, outputType, widgetName, value) {
    return {
        id,
        type,
        title: `${type} ${id}`,
        properties: {},
        outputs: [{type: outputType}],
        widgets: [{name: widgetName, value, options: {values: [value]}}],
    };
}

const image = loader(911, "LoadImage", "IMAGE", "image", "hero.png");
const audio = loader(940, "LoadAudio", "AUDIO", "audio", "voice.wav");
const nodes = [image, audio];
const graph = {
    _nodes: nodes,
    links: {
        1: {origin_id: 911, origin_slot: 0},
        2: {origin_id: 940, origin_slot: 0},
    },
    getNodeById(id) {
        return nodes.find((node) => String(node.id) === String(id));
    },
};
const manager = {
    graph,
    properties: {},
    inputs: [
        {name: "plan", link: 9},
        {name: "asset_0", link: 1},
        {name: "asset_1", link: 2},
        {name: "asset_2", link: null},
    ],
};
let ordinal = 0;
const bindings = collectAssetBindings(manager, () => `binding-${++ordinal}`);
assert.equal(bindings.length, 2);
assert.equal(bindings[0].node_id, "911");
assert.equal(bindings[0].role, "picture");
assert.equal(bindings[1].role, "audio_reference");
assert.equal(inferAssetRole("VIDEO", "LoadVideo"), "video");

// A loader may expose media on more than one output. Each output needs its
// own persistent identity so video and audio roles cannot overwrite one another.
image.outputs.push({type: "AUDIO"});
manager.inputs.push({name: "asset_2", link: 12});
graph.links[12] = {origin_id: 911, origin_slot: 1};
const multiOutput = collectAssetBindings(manager, () => `binding-${++ordinal}`);
assert.notEqual(multiOutput[0].binding_id, multiOutput[2].binding_id);
assert.equal(multiOutput[2].role, "audio_reference");
manager.inputs.pop();
delete graph.links[12];

manager.properties.h3_asset_roles[bindings[1].binding_id] = "source_track";
assert.equal(collectAssetBindings(manager)[1].role, "source_track");

const archived = {
    ...bindings[0],
    restore_value: "h3_project_hash_hero.png",
    restore_source: "archived_fallback",
};
assert.equal(findAssetTarget(graph, archived).match, "binding");
const restored = applyAssetBinding(graph, archived);
assert(restored.applied);
assert.equal(image.widgets[0].value, archived.restore_value);
assert(image.widgets[0].options.values.includes(archived.restore_value));

const missing = applyAssetBinding(graph, {...archived, restore_value: ""});
assert.equal(missing.reason, "media_missing");

console.log("H3 run asset bindings: capture, roles, matching and loader restore pass");
