#!/usr/bin/env node

import assert from "node:assert/strict";
import {createH3PromptSchemaController} from "../web/h3_prompt_schema_ui.mjs";

class FakeClassList {
    constructor(owner) {
        this.owner = owner;
    }

    values() {
        return new Set(String(this.owner.className || "").split(/\s+/).filter(Boolean));
    }

    toggle(name, force) {
        const values = this.values();
        const enabled = force === undefined ? !values.has(name) : Boolean(force);
        if (enabled) values.add(name);
        else values.delete(name);
        this.owner.className = [...values].join(" ");
        return enabled;
    }

    contains(name) {
        return this.values().has(name);
    }
}

class FakeElement {
    constructor(tagName = "") {
        this.tagName = String(tagName).toUpperCase();
        this.children = [];
        this.listeners = new Map();
        this.attributes = new Map();
        this.className = "";
        this.classList = new FakeClassList(this);
        this.textContent = "";
        this.value = "";
    }

    append(...items) {
        this.children.push(...items);
    }

    replaceChildren(...items) {
        this.children = [...items];
    }

    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) ?? [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
    }

    fire(type) {
        for (const listener of this.listeners.get(type) ?? []) {
            listener({preventDefault() {}});
        }
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }
}

const created = [];
const head = new FakeElement("head");
globalThis.document = {
    head,
    createElement(tagName) {
        const item = new FakeElement(tagName);
        created.push(item);
        return item;
    },
    createTextNode(text) {
        return {nodeType:3, textContent:String(text)};
    },
    getElementById(id) {
        return created.find((item) => item.id === id) ?? null;
    },
};

function descendants(root) {
    const result = [];
    const queue = [root];
    while (queue.length) {
        const item = queue.shift();
        if (!item || typeof item !== "object") continue;
        result.push(item);
        queue.push(...(item.children ?? []));
    }
    return result;
}

function itemWithText(root, text, tagName = null) {
    return descendants(root).find((item) => item.textContent === text
        && (!tagName || item.tagName === tagName));
}

const node = {properties:{}};
let prompt = "";
let replacementMessage = "";
const controller = createH3PromptSchemaController({
    node,
    propertyPrefix:"test_editor",
    scopeKey:"scene-a",
    defaultMode:"ref2va",
    defaultDuration:7.25,
    getText:() => prompt,
    replaceText:(result, message) => {
        prompt = result.text;
        replacementMessage = message;
    },
    getRecords:() => [{token:"@hero", label:"<Picture 1>"}],
});

assert.equal(controller.getMode(), "ref2va");
assert.equal(controller.counts.textContent, "0 words · 0 chars");
controller.toggle.fire("click");
assert.equal(node.properties.test_editor_structure_open, true);
assert.equal(controller.panel.classList.contains("h3schema-open"), true);

itemWithText(controller.panel, "Add missing", "BUTTON").fire("click");
controller.refresh();
assert.match(replacementMessage, /Added 6 missing sections/);
assert.match(prompt, /^subject_definitions:/);
assert.match(prompt, /non_diegetic_music:\nN\/A$/);
assert.equal(controller.analysis.missing.length, 0);
assert.match(controller.counts.textContent, /words · \d+ chars/);

controller.modeSelect.value = "fl2va";
controller.modeSelect.fire("change");
assert.equal(node.properties.test_editor_schema_mode, "fl2va");
const duration = descendants(controller.panel).find(
    (item) => item.tagName === "INPUT" && item.step === "0.01",
);
duration.value = "8.5";
duration.fire("change");
assert.deepEqual(node.properties.test_editor_schema_alignment_by_scene["scene-a"], {
    duration:8.5,
    finalShot:1,
});

let secondPrompt = "";
const second = createH3PromptSchemaController({
    node,
    propertyPrefix:"test_editor",
    scopeKey:"scene-b",
    defaultMode:"fl2va",
    defaultDuration:12.25,
    getText:() => secondPrompt,
    replaceText:(result) => { secondPrompt = result.text; },
});
second.toggle.fire("click");
itemWithText(second.panel, "Add missing", "BUTTON").fire("click");
assert.match(secondPrompt, /12\.25-second mark/);
assert.doesNotMatch(secondPrompt, /8\.50-second mark/);

console.log("H3 schema UI: panel, repair, mode, counts, and scene-scoped alignment pass");
