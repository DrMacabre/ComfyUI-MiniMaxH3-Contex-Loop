#!/usr/bin/env node

import assert from "node:assert/strict";
import {
    adjacentPlanCompanions,
    connectedPlanStudios,
    connectedPromptEditors,
    publishCompanionScene,
    rebaseScenePrompt,
} from "../web/h3_prompt_companion_sync.mjs";

const plan = {id:1, type:"MiniMaxH3ChainPlan"};
const studio = {id:2, type:"MiniMaxH3ChainPlanStudio", inputs:[{link:10}], outputs:[{links:[11]}]};
const editor = {id:3, type:"MiniMaxH3ChainRichScenePromptEditor", inputs:[{link:11}], outputs:[]};
const nodes = new Map([[1,plan],[2,studio],[3,editor]]);
const links = {
    10:{origin_id:1,target_id:2},
    11:{origin_id:2,target_id:3},
};
const graph = {links, getNodeById:(id) => nodes.get(id)};
for (const node of nodes.values()) node.graph = graph;

assert.deepEqual(adjacentPlanCompanions(studio), [plan, editor]);
assert.deepEqual(connectedPromptEditors(studio), [editor]);
assert.deepEqual(connectedPlanStudios(editor), [studio]);

let received = null;
editor._h3PromptCompanionSetActiveScene = (receivedPlan, index, source) => {
    received = {receivedPlan,index,source};
};
assert.equal(publishCompanionScene(studio, plan, 2.9), 1);
assert.deepEqual(received, {receivedPlan:plan,index:2,source:studio});

editor._h3PromptCompanionSetActiveScene = () => false;
assert.equal(publishCompanionScene(studio, plan, 4), 0);

const localPlan = {shared:"old", shots:[
    {id:"one", prompt:["old one"], seed:"1"},
    {id:"two", prompt:["edited two"], seed:"2"},
]};
const editedShot = localPlan.shots[1];
const livePlan = {shared:"new", shots:[
    {id:"two", prompt:["stale two"], seed:"22", steps:20},
    {id:"one", prompt:["live one"], seed:"11"},
]};
assert.equal(rebaseScenePrompt(localPlan, livePlan, 1), 0);
assert.equal(localPlan.shared, "new");
assert.equal(localPlan.shots[0], editedShot, "active shot identity survives rebase");
assert.deepEqual(localPlan.shots[0], {id:"two", prompt:["edited two"], seed:"22", steps:20});
assert.deepEqual(localPlan.shots[1], {id:"one", prompt:["live one"], seed:"11"});
assert.equal(rebaseScenePrompt({shots:[{id:"gone",prompt:[]}]}, livePlan, 0), -1);

console.log("H3 prompt companions: adjacency and active-scene synchronization pass");
