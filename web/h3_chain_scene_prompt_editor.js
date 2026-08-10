import {app} from "/scripts/app.js";
import {
    parsePlanJson,
    planToJson,
    promptTextToLines,
    promptValueToText,
    sharedPrompt,
} from "./h3_chain_plan_core.mjs";

// The compact @ reference and # dialogue authoring interactions are inspired
// by nkxx188/ComfyUI-MiniMaxH3-Easy (MIT); see THIRD_PARTY_NOTICES.md.

const NODE_NAME = "MiniMaxH3ChainScenePromptEditor";
const PLAN_NAME = "MiniMaxH3ChainPlan";
const ACTIVE_SCENE_PROPERTY = "h3_scene_prompt_editor_active_scene";
const FONT_SIZE_PROPERTY = "h3_scene_prompt_editor_font_size";
const DEFAULT_FONT_SIZE = 18;
const MIN_FONT_SIZE = 12;
const MAX_FONT_SIZE = 36;

function injectStyles() {
    if (document.getElementById("h3-scene-prompt-editor-style")) return;
    const style = document.createElement("style");
    style.id = "h3-scene-prompt-editor-style";
    style.textContent = `
        .h3sp-root {
            --h3sp-bg: color-mix(in srgb, var(--comfy-menu-bg, #202124) 92%, #101827);
            --h3sp-panel: color-mix(in srgb, var(--comfy-input-bg, #111827) 84%, #263552);
            --h3sp-border: color-mix(in srgb, var(--border-color, #555) 68%, #7891bf);
            --h3sp-text: var(--input-text, #eef1f7);
            --h3sp-muted: color-mix(in srgb, var(--h3sp-text) 58%, transparent);
            --h3sp-accent: #84aaff;
            --h3sp-font-size: 18px;
            box-sizing:border-box; width:100%; height:100%; min-height:420px;
            display:flex; flex-direction:column; gap:8px; overflow:hidden; padding:10px;
            border:1px solid var(--h3sp-border); border-radius:8px; background:var(--h3sp-bg);
            color:var(--h3sp-text); font:12px/1.35 system-ui,sans-serif;
        }
        .h3sp-root *, .h3sp-root *::before, .h3sp-root *::after { box-sizing:border-box; }
        .h3sp-head, .h3sp-nav, .h3sp-tools, .h3sp-font, .h3sp-footer {
            display:flex; align-items:center; gap:6px;
        }
        .h3sp-head { justify-content:space-between; }
        .h3sp-title { color:var(--h3sp-accent); font-size:15px; font-weight:750; }
        .h3sp-context { color:var(--h3sp-muted); white-space:nowrap; overflow:hidden;
            text-overflow:ellipsis; text-align:right; }
        .h3sp-nav select { flex:1; min-width:0; }
        .h3sp-root button, .h3sp-root select {
            color:var(--h3sp-text); font:inherit; border:1px solid var(--h3sp-border);
            border-radius:5px; background:var(--comfy-input-bg,#171a21);
        }
        .h3sp-root button { padding:6px 9px; cursor:pointer; white-space:nowrap; }
        .h3sp-root button:hover { border-color:var(--h3sp-accent); }
        .h3sp-root button:disabled { cursor:not-allowed; opacity:.4; }
        .h3sp-root select { min-height:30px; padding:5px 7px; }
        .h3sp-font { margin-left:auto; }
        .h3sp-font-value { min-width:38px; color:var(--h3sp-muted); text-align:center; }
        .h3sp-textarea {
            width:100%; min-height:240px; flex:1 1 auto; resize:none; padding:12px 14px;
            border:1px solid var(--h3sp-border); border-radius:7px;
            outline:none; background:var(--comfy-input-bg,#11141a); color:var(--h3sp-text);
            font:var(--h3sp-font-size)/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;
            tab-size:4; white-space:pre-wrap;
        }
        .h3sp-textarea:focus { border-color:var(--h3sp-accent);
            box-shadow:0 0 0 1px color-mix(in srgb,var(--h3sp-accent) 45%,transparent); }
        .h3sp-tools { position:relative; flex-wrap:wrap; }
        .h3sp-hint { color:var(--h3sp-muted); margin-left:auto; }
        .h3sp-refs { display:none; flex:0 0 auto; max-height:118px; overflow:auto;
            padding:7px; gap:5px; flex-wrap:wrap; border:1px solid var(--h3sp-border);
            border-radius:6px; background:var(--h3sp-panel); }
        .h3sp-refs.h3sp-open { display:flex; }
        .h3sp-refs button { padding:4px 7px; }
        .h3sp-footer { justify-content:space-between; color:var(--h3sp-muted); }
        .h3sp-error { padding:12px; border:1px solid #a76565; border-radius:6px;
            color:#ffb3b3; background:#351f24; white-space:pre-wrap; }
    `;
    document.head.appendChild(style);
}

function element(tag, className = "", text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
}

function button(label, title, action) {
    const item = element("button", "", label);
    item.type = "button";
    item.title = title;
    item.addEventListener("click", action);
    return item;
}

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function allNodes(graph, output = []) {
    for (const node of graph?._nodes ?? []) {
        output.push(node);
        if (node.subgraph) allNodes(node.subgraph, output);
    }
    return output;
}

function upstreamPlanNode(start) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (node !== start && nodeType(node) === PLAN_NAME) return node;
        for (const input of node.inputs ?? []) {
            if (input.link == null) continue;
            const link = node.graph?.links?.[input.link];
            const parent = link ? node.graph?.getNodeById?.(link.origin_id) : null;
            if (parent) queue.push(parent);
        }
    }
    return null;
}

function insertText(textarea, text, selectionOffset = text.length) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.setRangeText(text, start, end, "end");
    const caret = start + selectionOffset;
    textarea.setSelectionRange(caret, caret);
    textarea.dispatchEvent(new Event("input", {bubbles: true}));
    textarea.focus();
}

function insertDialogue(textarea) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const selected = textarea.value.slice(start, end);
    const markup = `<d>${selected}</d>`;
    insertText(textarea, markup, selected ? markup.length : 3);
}

function clamp(value, minimum, maximum, fallback) {
    const numeric = Number(value);
    return Number.isFinite(numeric)
        ? Math.max(minimum, Math.min(maximum, Math.round(numeric))) : fallback;
}

function mount(node) {
    if (node._h3ScenePromptEditorMounted || typeof node.addDOMWidget !== "function") return;
    node._h3ScenePromptEditorMounted = true;
    injectStyles();

    node.properties ??= {};
    const root = element("div", "h3sp-root");
    root.title = "Edit the active scene prompt stored in the connected H3 Chain Plan.";
    for (const eventName of [
        "pointerdown", "pointerup", "mousedown", "mouseup", "click", "dblclick",
    ]) {
        root.addEventListener(eventName, (event) => event.stopPropagation());
    }
    root.addEventListener("wheel", (event) => event.stopPropagation());

    const state = {
        plan: null,
        planNode: null,
        planWidget: null,
        lastValue: "",
        active: Math.max(0, Number(node.properties[ACTIVE_SCENE_PROPERTY]) || 0),
        fontSize: clamp(
            node.properties[FONT_SIZE_PROPERTY], MIN_FONT_SIZE, MAX_FONT_SIZE,
            DEFAULT_FONT_SIZE,
        ),
        pollTimer: null,
    };
    node._h3ScenePromptEditorState = state;

    function dirty() {
        node.graph?.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas?.(true, true);
    }

    function persistView() {
        node.properties[ACTIVE_SCENE_PROPERTY] = state.active;
        node.properties[FONT_SIZE_PROPERTY] = state.fontSize;
        dirty();
    }

    function writePlan(status) {
        if (!state.plan || !state.planWidget || !state.planNode) return;
        const value = planToJson(state.plan);
        state.lastValue = value;
        state.planWidget.value = value;
        state.planWidget.callback?.(value);
        state.planNode._h3ChainEditorRefresh?.();
        state.planNode.graph?.setDirtyCanvas?.(true, true);
        if (status) status.textContent = "Saved to connected Plan";
        dirty();
    }

    function showFailure(message) {
        root.replaceChildren();
        root.append(
            element("div", "h3sp-title", "MiniMax H3 Scene Prompt Editor"),
            element("div", "h3sp-error", message),
            element("div", "h3sp-context", "Connect the Plan output to this node's plan input."),
        );
    }

    function navigate(offset, absolute = null) {
        if (!state.plan?.shots?.length) return;
        const requested = absolute == null ? state.active + offset : Number(absolute);
        state.active = Math.max(0, Math.min(state.plan.shots.length - 1, requested));
        persistView();
        render();
        root.querySelector(".h3sp-textarea")?.focus();
    }

    function render() {
        if (!state.plan?.shots?.length) {
            showFailure("The connected Plan has no scenes.");
            return;
        }
        state.active = Math.max(0, Math.min(state.active, state.plan.shots.length - 1));
        root.style.setProperty("--h3sp-font-size", `${state.fontSize}px`);
        root.replaceChildren();

        const shot = state.plan.shots[state.active];
        const shotId = String(shot.id || `clip_${String(state.active + 1).padStart(4, "0")}`);
        const head = element("div", "h3sp-head");
        head.append(
            element("span", "h3sp-title", "Scene Prompt Editor"),
            element("span", "h3sp-context", sharedPrompt(state.plan).text.trim()
                ? "Shared prompt active (unchanged)" : "No shared prompt"),
        );

        const nav = element("div", "h3sp-nav");
        const previous = button("←", "Previous scene (Alt+Left)", () => navigate(-1));
        const next = button("→", "Next scene (Alt+Right)", () => navigate(1));
        previous.disabled = state.active === 0;
        next.disabled = state.active === state.plan.shots.length - 1;
        const sceneSelect = element("select");
        for (let index = 0; index < state.plan.shots.length; index += 1) {
            const option = element("option", "", `Scene ${index + 1} — ${state.plan.shots[index].id || `clip_${String(index + 1).padStart(4, "0")}`}`);
            option.value = String(index);
            sceneSelect.append(option);
        }
        sceneSelect.value = String(state.active);
        sceneSelect.title = "Jump directly to another scene prompt.";
        sceneSelect.addEventListener("change", () => navigate(0, sceneSelect.value));

        const font = element("div", "h3sp-font");
        const fontValue = element("span", "h3sp-font-value", `${state.fontSize}px`);
        const smaller = button("A−", "Decrease editor font size", () => {
            state.fontSize = clamp(state.fontSize - 2, MIN_FONT_SIZE, MAX_FONT_SIZE, DEFAULT_FONT_SIZE);
            persistView();
            render();
        });
        const larger = button("A+", "Increase editor font size", () => {
            state.fontSize = clamp(state.fontSize + 2, MIN_FONT_SIZE, MAX_FONT_SIZE, DEFAULT_FONT_SIZE);
            persistView();
            render();
        });
        smaller.disabled = state.fontSize <= MIN_FONT_SIZE;
        larger.disabled = state.fontSize >= MAX_FONT_SIZE;
        font.append(smaller, fontValue, larger);
        nav.append(previous, sceneSelect, next, font);

        const textarea = element("textarea", "h3sp-textarea");
        textarea.value = promptValueToText(shot.prompt, `Scene ${state.active + 1} prompt`);
        textarea.placeholder = "Write this scene's action, camera, performance, dialogue, and ending continuity…";
        textarea.spellcheck = true;
        textarea.title = "This is the actual active scene prompt in the connected H3 Chain Plan.";

        const tools = element("div", "h3sp-tools");
        const refs = element("div", "h3sp-refs");
        const referenceButton = button("@ Reference", "Open MiniMax reference tags (@)", () => {
            refs.classList.toggle("h3sp-open");
        });
        const dialogueButton = button("# Dialogue", "Wrap selection in <d> dialogue tags (#)", () => {
            insertDialogue(textarea);
        });
        tools.append(
            referenceButton,
            dialogueButton,
            element("span", "h3sp-hint", "Alt+←/→ scenes · @ refs · # dialogue"),
        );
        for (const [kind, count] of [["Picture", 9], ["Video", 3], ["Audio", 6]]) {
            for (let ordinal = 1; ordinal <= count; ordinal += 1) {
                const tag = `<${kind} ${ordinal}>`;
                refs.append(button(tag, `Insert ${tag}`, () => {
                    insertText(textarea, tag);
                    refs.classList.remove("h3sp-open");
                }));
            }
        }

        const footer = element("div", "h3sp-footer");
        const identity = element(
            "span", "", `Scene ${state.active + 1}/${state.plan.shots.length} · ${shotId}`,
        );
        const status = element("span", "", "Synchronized with Plan");
        footer.append(identity, status);

        textarea.addEventListener("input", () => {
            shot.prompt = promptTextToLines(textarea.value);
            writePlan(status);
        });
        textarea.addEventListener("keydown", (event) => {
            if (event.altKey && event.key === "ArrowLeft") {
                event.preventDefault();
                navigate(-1);
            } else if (event.altKey && event.key === "ArrowRight") {
                event.preventDefault();
                navigate(1);
            } else if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "@") {
                event.preventDefault();
                refs.classList.add("h3sp-open");
                referenceButton.focus();
            } else if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "#") {
                event.preventDefault();
                insertDialogue(textarea);
            }
        });

        root.append(head, nav, tools, refs, textarea, footer);
    }

    function loadPlan(force = false) {
        const planNode = upstreamPlanNode(node);
        const planWidget = planNode?.widgets?.find((item) => item.name === "plan_json");
        if (!planNode || !planWidget) {
            if (force || state.planNode) {
                state.plan = null;
                state.planNode = null;
                state.planWidget = null;
                state.lastValue = "";
                showFailure("No connected H3 Chain Plan was found.");
            }
            return;
        }
        const value = String(planWidget.value ?? "");
        if (!force && planNode === state.planNode && value === state.lastValue) return;
        try {
            state.plan = parsePlanJson(value);
            state.planNode = planNode;
            state.planWidget = planWidget;
            state.lastValue = value;
            render();
        } catch (error) {
            showFailure(`Connected Plan JSON is invalid:\n${error.message}`);
        }
    }

    const widget = node.addDOMWidget(
        "h3_scene_prompt_editor", "h3-scene-prompt-editor", root,
        {serialize: false, hideOnZoom: false, getMinHeight: () => 420},
    );
    widget.serialize = false;
    node.setSize?.([
        Math.max(node.size?.[0] ?? 700, 700),
        Math.max(node.size?.[1] ?? 620, 620),
    ]);

    const connectionsChanged = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = connectionsChanged?.apply(this, arguments);
        setTimeout(() => loadPlan(true), 0);
        return result;
    };
    const removed = node.onRemoved;
    node.onRemoved = function () {
        if (state.pollTimer != null) window.clearInterval(state.pollTimer);
        return removed?.apply(this, arguments);
    };
    node._h3ScenePromptEditorRefresh = () => loadPlan(true);
    state.pollTimer = window.setInterval(() => loadPlan(false), 500);
    loadPlan(true);
}

app.registerExtension({
    name: "minimax_h3_context_loop.scene_prompt_editor",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            setTimeout(() => mount(this), 0);
            return result;
        };
    },
    async nodeCreated(node) {
        if (nodeType(node) === NODE_NAME) mount(node);
    },
    async afterConfigureGraph() {
        for (const node of allNodes(app.graph)) {
            if (nodeType(node) === NODE_NAME) {
                setTimeout(() => node._h3ScenePromptEditorRefresh?.(), 0);
            }
        }
    },
});
