import assert from "node:assert/strict";
import {collectAssetBindings} from "../web/h3_run_assets_core.mjs";

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
const stored = [{
    binding_id: "h3-audio-ref-01",
    label: "AUDIO REF 1 — LOAD AUDIO",
    role: "audio_reference",
    node_id: "101",
    node_type: "LoadAudio",
    node_title: "AUDIO REF 1 — LOAD AUDIO",
    output_slot: 0,
    output_type: "AUDIO",
    widget_name: "audio",
    original_value: "",
}];
const manager = {
    id: 200,
    graph,
    inputs: [],
    properties: {
        h3_asset_roles: {"h3-audio-ref-01": "audio_reference"},
        h3_persist_detached_asset_bindings: true,
    },
    widgets: [{name: "asset_bindings_json", value: JSON.stringify(stored)}],
};

let bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 1);
assert.equal(bindings[0].binding_id, "h3-audio-ref-01");
assert.equal(bindings[0].original_value, "");
assert.equal(bindings[0].node_id, "101");

loader.widgets[0].value = "voice.wav";
bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 1);
assert.equal(bindings[0].original_value, "voice.wav");

manager.properties.h3_persist_detached_asset_bindings = false;
bindings = collectAssetBindings(manager);
assert.equal(bindings.length, 0);

console.log("PASS detached Run Manager asset bindings remain metadata-only");
