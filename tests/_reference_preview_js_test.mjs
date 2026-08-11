import assert from "node:assert/strict";
import {
    collectScheduleNodes,
    coreReferenceRecords,
    findScheduledRef2VA,
    referencePreviewRecords,
    referenceIsActive,
    scheduledReferenceRecords,
} from "../web/h3_reference_preview_core.mjs";

function makeNode(id, type, widgets = {}) {
    return {
        id,
        type,
        title: type,
        widgets: Object.entries(widgets).map(([name, value]) => ({name, value})),
        inputs: [],
        outputs: [{name: "output", links: []}],
    };
}

const graph = {
    _nodes: [],
    links: {},
    getNodeById(id) { return this._nodes.find((node) => node.id === id); },
};
let nextLink = 1;
function add(node) {
    node.graph = graph;
    graph._nodes.push(node);
    return node;
}
function connect(source, target, targetName) {
    const id = nextLink++;
    source.outputs[0].links.push(id);
    target.inputs.push({name: targetName, link: id});
    graph.links[id] = {
        origin_id: source.id,
        origin_slot: 0,
        target_id: target.id,
        target_slot: target.inputs.length - 1,
    };
}

const editor = add(makeNode(1, "MiniMaxH3ChainScenePromptEditor"));
const relay = add(makeNode(2, "MiniMaxH3ChainCurrent"));
const wrapper = add(makeNode(3, "MiniMaxH3ScheduledReferenceToVideo"));
const firstImage = add(makeNode(4, "LoadImage", {image: "first.png"}));
const secondImage = add(makeNode(5, "LoadImage", {image: "second.png"}));
const audioFile = add(makeNode(6, "LoadAudio", {audio: "score.wav"}));
const first = add(makeNode(7, "MiniMaxH3ScheduledPictureReference", {
    tag: "picture_1", scenes: "1", declaration: "Use {ref} first.",
}));
const second = add(makeNode(8, "MiniMaxH3ScheduledPictureReference", {
    tag: "picture_2", scenes: "", declaration: "Use {ref} second.",
}));
const audio = add(makeNode(9, "MiniMaxH3ScheduledAudioReference", {
    tag: "score", scenes: "all", declaration: "Use {ref} for sound.",
}));

connect(editor, relay, "state");
connect(relay, wrapper, "prompt");
connect(firstImage, first, "image");
connect(first, second, "previous");
connect(secondImage, second, "image");
connect(second, audio, "previous");
connect(audioFile, audio, "audio");
connect(audio, wrapper, "reference_schedule");

assert.equal(findScheduledRef2VA(editor), wrapper);
assert.deepEqual(collectScheduleNodes(wrapper), [first, second, audio]);
assert.equal(referenceIsActive("1,3:5", 4), true);
assert.equal(referenceIsActive("1,3:5", 2), false);

const sceneOne = scheduledReferenceRecords(editor, 1).records;
assert.deepEqual(sceneOne.map(({tag, label, active}) => ({tag, label, active})), [
    {tag: "picture_1", label: "<Picture 1>", active: true},
    {tag: "picture_2", label: "<Picture 2>", active: true},
    {tag: "score", label: "<Audio 1>", active: true},
]);
const sceneTwo = scheduledReferenceRecords(editor, 2).records;
assert.deepEqual(sceneTwo.map(({tag, label, active}) => ({tag, label, active})), [
    {tag: "picture_1", label: null, active: false},
    {tag: "picture_2", label: "<Picture 1>", active: true},
    {tag: "score", label: "<Audio 1>", active: true},
]);

const coreEditor = add(makeNode(10, "MiniMaxH3ChainScenePromptEditor"));
const coreRelay = add(makeNode(11, "MiniMaxH3ChainCurrent"));
const core = add(makeNode(12, "MiniMaxH3ReferenceToVideo"));
const coreImage = add(makeNode(13, "LoadImage", {image: "core.png"}));
const coreAudio = add(makeNode(14, "LoadAudio", {audio: "core.wav"}));
connect(coreEditor, coreRelay, "state");
connect(coreRelay, core, "prompt");
connect(coreImage, core, "ref_images.ref_image_0");
connect(coreAudio, core, "ref_audios.ref_audio_0");
const native = coreReferenceRecords(coreEditor);
assert.equal(native.mode, "native");
assert.deepEqual(native.records.map(({kind, token, label}) => ({kind, token, label})), [
    {kind: "picture", token: "<Picture 1>", label: "<Picture 1>"},
    {kind: "audio", token: "<Audio 1>", label: "<Audio 1>"},
]);
assert.equal(referencePreviewRecords(coreEditor, 1).mode, "native");

console.log("H3 reference preview: scheduled and core Ref2VA discovery pass");
