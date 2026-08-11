import assert from "node:assert/strict";
import {
    collectScheduleNodes,
    findScheduledRef2VA,
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

console.log("H3 reference preview: schedule discovery and scene-local mappings pass");
