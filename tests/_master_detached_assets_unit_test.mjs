import assert from "node:assert/strict";
import {
    collectAssetBindings,
    collectDetachedAssetNodes,
} from "../web/h3_run_assets_core.mjs";

const loader = {
    id: 101,
    type: "LoadAudio",
    comfyClass: "LoadAudio",
    title: "AUDIO REF 1 — LOAD AUDIO",
    properties: {h3_asset_binding_ids: {0: "h3-audio-ref-01"}},
    outputs: [{type: "AUDIO"}],
    widgets: [{name: "audio", value: ""}],
};
const graph = {
    _nodes: [loader],
    links: {},
    getNodeById(id) {
        return String(id) === String(loader.id) ? loader : null;
    },
};
const template = {
    binding_id: "h3-audio-ref-01",
    label: "OLD PROJECT AUDIO LABEL",
    role: "audio_reference",
    node_id: "101",
    node_type: "LoadAudio",
    node_title: "OLD PROJECT AUDIO LABEL",
    output_slot: 0,
    output_type: "AUDIO",
    widget_name: "audio",
    original_value: "",
};
const manager = {
    id: 200,
    graph,
    inputs: [],
    properties: {
        h3_asset_roles: {"h3-audio-ref-01": "audio_reference"},
        h3_persist_detached_asset_bindings: true,
        h3_detached_asset_templates: [template],
    },
    widgets: [{name: "asset_bindings_json", value: "[]"}],
};

// Blank master placeholders remain watchable but are not active archive
// bindings, so the backend never sees them as missing source files.
let bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 0);
assert.deepEqual(collectDetachedAssetNodes(manager), [loader]);

// Selecting media activates the binding automatically and refreshes legacy
// labels from the current generic master loader.
loader.widgets[0].value = "voice.wav";
bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 1);
assert.equal(bindings[0].binding_id, "h3-audio-ref-01");
assert.equal(bindings[0].original_value, "voice.wav");
assert.equal(bindings[0].label, "AUDIO REF 1 — LOAD AUDIO");
assert.equal(bindings[0].node_id, "101");

// Clearing the loader makes the same persistent template inactive again.
loader.widgets[0].value = "";
bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 0);
assert.equal(manager.properties.h3_detached_asset_templates.length, 1);

console.log("PASS detached master asset templates stay watchable while blank media stays inactive");
