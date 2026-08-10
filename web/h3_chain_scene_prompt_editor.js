import {app} from "/scripts/app.js";
import {
    parsePlanJson,
    planToJson,
    promptTextToLines,
    promptValueToText,
    sharedPrompt,
} from "./h3_chain_plan_core.mjs";
import {
    PROMPT_ASSIST_DEFAULT_INSTRUCTIONS,
    PROMPT_ASSIST_MODES,
    buildPromptAssistantContext,
    draftConflict,
    makePromptAssistRequest,
    promptSceneKey,
    promptSourceRevision,
} from "./h3_prompt_assistant_core.mjs";
import {PromptAssistantClient} from "./h3_prompt_assistant_client.mjs";

// The compact @ reference and # dialogue authoring interactions are inspired
// by nkxx188/ComfyUI-MiniMaxH3-Easy (MIT); see THIRD_PARTY_NOTICES.md.

const NODE_NAME = "MiniMaxH3ChainScenePromptEditor";
const PLAN_NAME = "MiniMaxH3ChainPlan";
const ACTIVE_SCENE_PROPERTY = "h3_scene_prompt_editor_active_scene";
const FONT_SIZE_PROPERTY = "h3_scene_prompt_editor_font_size";
const ASSIST_PROVIDER_PROPERTY = "h3_scene_prompt_editor_assist_provider";
const ASSIST_MODE_PROPERTY = "h3_scene_prompt_editor_assist_mode";
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
            display:flex; flex-direction:column; gap:8px; overflow:auto; padding:10px;
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
            width:100%; min-height:220px; flex:1 1 auto; resize:vertical; padding:12px 14px;
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
        .h3sp-assist { flex:0 0 auto; display:flex; flex-direction:column; gap:7px;
            padding:9px; border:1px solid var(--h3sp-border); border-radius:7px;
            background:var(--h3sp-panel); }
        .h3sp-assist-head, .h3sp-assist-controls, .h3sp-assist-actions,
        .h3sp-assist-contexts { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
        .h3sp-assist-head { justify-content:space-between; }
        .h3sp-assist-title { color:var(--h3sp-accent); font-size:13px; font-weight:750; }
        .h3sp-assist-status { color:var(--h3sp-muted); font-size:11px; }
        .h3sp-assist-controls select { flex:1 1 120px; min-width:100px; }
        .h3sp-assist-contexts label { display:flex; align-items:center; gap:4px;
            color:var(--h3sp-muted); cursor:pointer; }
        .h3sp-assist-contexts input { accent-color:var(--h3sp-accent); }
        .h3sp-assist-chat { display:flex; flex-direction:column; gap:5px; max-height:180px;
            overflow:auto; padding:6px; border:1px solid color-mix(in srgb,var(--h3sp-border) 70%,transparent);
            border-radius:6px; background:color-mix(in srgb,var(--comfy-input-bg,#11141a) 82%,transparent); }
        .h3sp-assist-message { padding:6px 8px; border-radius:6px; white-space:pre-wrap;
            overflow-wrap:anywhere; }
        .h3sp-assist-message-user { margin-left:12%; background:#23375b; }
        .h3sp-assist-message-agent { margin-right:7%; background:#263c34; }
        .h3sp-assist-message-system { color:var(--h3sp-muted); font-size:11px;
            border:1px dashed var(--h3sp-border); }
        .h3sp-assist-empty { color:var(--h3sp-muted); padding:5px; }
        .h3sp-assist-compose { display:flex; align-items:stretch; gap:6px; }
        .h3sp-assist-compose textarea, .h3sp-assist-draft textarea {
            width:100%; resize:vertical; min-height:58px; padding:7px 8px;
            border:1px solid var(--h3sp-border); border-radius:6px;
            outline:none; background:var(--comfy-input-bg,#11141a); color:var(--h3sp-text);
            font:12px/1.4 system-ui,sans-serif; }
        .h3sp-assist-compose textarea:focus, .h3sp-assist-draft textarea:focus {
            border-color:var(--h3sp-accent); }
        .h3sp-assist-compose button { align-self:stretch; }
        .h3sp-assist-draft { display:flex; flex-direction:column; gap:6px; padding:8px;
            border:1px solid #5d8a72; border-radius:6px; background:#182b25; }
        .h3sp-assist-draft-head { display:flex; justify-content:space-between;
            align-items:center; gap:6px; }
        .h3sp-assist-draft-title { font-weight:700; color:#9ad7b7; }
        .h3sp-assist-stale { color:#ffc08a; font-size:11px; }
        .h3sp-assist-original { color:var(--h3sp-muted); }
        .h3sp-assist-original pre { max-height:120px; overflow:auto; white-space:pre-wrap;
            padding:6px; border-radius:5px; background:var(--comfy-input-bg,#11141a); }
        .h3sp-assist-error { color:#ffb3b3; white-space:pre-wrap; }
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
        assistant: {
            client: null,
            host: null,
            status: "idle",
            statusDetail: "Connects through comfyui-mcp on the first request",
            provider: ["codex", "hermes"].includes(
                node.properties[ASSIST_PROVIDER_PROPERTY],
            ) ? node.properties[ASSIST_PROVIDER_PROPERTY] : "codex",
            mode: PROMPT_ASSIST_MODES.some(
                (item) => item.id === node.properties[ASSIST_MODE_PROPERTY],
            ) ? node.properties[ASSIST_MODE_PROPERTY] : "rewrite",
            includeShared: true,
            includeAdjacent: true,
            composer: "",
            messages: [],
            drafts: new Map(),
            requestContexts: new Map(),
            activeRequest: null,
            lastApplied: null,
            providers: null,
            error: "",
        },
        pollTimer: null,
    };
    node._h3ScenePromptEditorState = state;

    const assistant = state.assistant;
    assistant.client = new PromptAssistantClient({
        identityKey: node.id == null
            ? `node-new-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`
            : `node-${node.id}`,
        onFrame: (frame) => handleAssistantFrame(frame),
        onStatus: (status, detail) => {
            assistant.status = status;
            assistant.statusDetail = status === "connected"
                ? "Connected · isolated prompt session"
                : status === "connecting" ? "Connecting to comfyui-mcp…"
                    : "Disconnected · send to reconnect";
            if (status === "disconnected" && assistant.activeRequest) {
                assistant.requestContexts.delete(assistant.activeRequest);
                assistant.activeRequest = null;
                assistant.error = "The bridge disconnected before the agent returned a result.";
                assistantMessage("system", "Bridge disconnected. No change was made to the scene prompt.");
            }
            if (detail?.providers) assistant.providers = detail.providers;
            refreshAssistant();
        },
    });

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

    function assistantMessage(role, text) {
        const value = String(text ?? "").trim();
        if (!value) return;
        assistant.messages.push({role, text: value});
        assistant.messages = assistant.messages.slice(-24);
    }

    function refreshAssistant() {
        const host = assistant.host;
        const promptTextarea = root.querySelector(".h3sp-textarea");
        if (!host || !promptTextarea || !state.plan?.shots?.length) return;
        renderAssistant(host, promptTextarea);
    }

    function handleAssistantFrame(frame) {
        if (!frame || typeof frame !== "object") return;
        if (frame.type === "prompt_assist_ready") {
            assistant.providers = Array.isArray(frame.providers) ? frame.providers : null;
            assistant.error = "";
        } else if (frame.type === "prompt_assist_started") {
            if (frame.request_id === assistant.activeRequest) assistant.status = "working";
        } else if (frame.type === "prompt_assist_progress") {
            if (frame.request_id === assistant.activeRequest) assistant.statusDetail = "Agent is drafting…";
        } else if (frame.type === "prompt_assist_result") {
            const meta = assistant.requestContexts.get(frame.request_id);
            if (!meta) return;
            assistant.requestContexts.delete(frame.request_id);
            if (assistant.activeRequest === frame.request_id) assistant.activeRequest = null;
            assistant.status = "connected";
            assistant.statusDetail = "Connected · isolated prompt session";
            assistant.error = "";
            assistantMessage("agent", frame.message || "Draft ready.");
            if (typeof frame.rewritten_prompt === "string") {
                assistant.drafts.set(meta.sceneKey, {
                    sceneId: meta.sceneId,
                    sceneIndex: meta.sceneIndex,
                    sourcePrompt: meta.sourcePrompt,
                    sourceRevision: meta.sourceRevision,
                    proposed: frame.rewritten_prompt,
                    provider: frame.provider || meta.provider,
                });
            }
        } else if (frame.type === "prompt_assist_error") {
            const meta = assistant.requestContexts.get(frame.request_id);
            if (meta) assistant.requestContexts.delete(frame.request_id);
            if (!frame.request_id || assistant.activeRequest === frame.request_id) {
                assistant.activeRequest = null;
            }
            assistant.status = assistant.client?.socket ? "connected" : "disconnected";
            assistant.error = String(frame.error || "Prompt assistant failed.");
            assistantMessage("system", `Agent error: ${assistant.error}`);
        } else if (frame.type === "prompt_assist_cancelled") {
            assistant.requestContexts.delete(frame.request_id);
            if (assistant.activeRequest === frame.request_id) assistant.activeRequest = null;
            assistant.status = "connected";
            assistant.statusDetail = "Stopped · ready for another request";
            assistantMessage("system", "Request stopped. The scene prompt was not changed.");
        }
        refreshAssistant();
    }

    async function sendAssistant(promptTextarea) {
        if (assistant.activeRequest || !state.plan?.shots?.length) return;
        const shot = state.plan.shots[state.active];
        const sceneId = String(shot.id || `clip_${String(state.active + 1).padStart(4, "0")}`);
        const sceneKey = promptSceneKey(sceneId, state.active);
        const selectedText = promptTextarea.value.slice(
            promptTextarea.selectionStart ?? 0,
            promptTextarea.selectionEnd ?? 0,
        );
        const context = buildPromptAssistantContext(
            state.plan,
            state.active,
            promptTextarea.value,
            {
                includeShared: assistant.includeShared,
                includeAdjacent: assistant.includeAdjacent,
                selectedText,
            },
        );
        const requestId = `pa-${globalThis.crypto?.randomUUID?.()
            ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
        const request = makePromptAssistRequest({
            requestId,
            conversationId: assistant.client.conversationId,
            provider: assistant.provider,
            mode: assistant.mode,
            instruction: assistant.composer,
            context,
        });
        assistant.requestContexts.set(requestId, {
            sceneKey,
            sceneId,
            sceneIndex: state.active,
            sourcePrompt: promptTextarea.value,
            sourceRevision: request.source_revision,
            provider: assistant.provider,
        });
        assistant.activeRequest = requestId;
        assistant.status = "working";
        assistant.statusDetail = `Asking ${assistant.provider === "hermes" ? "Hermes" : "Codex"}…`;
        assistant.error = "";
        assistantMessage("user", request.instruction);
        assistant.composer = "";
        refreshAssistant();
        try {
            await assistant.client.send(request);
        } catch (error) {
            if (assistant.activeRequest !== requestId) return;
            assistant.activeRequest = null;
            assistant.requestContexts.delete(requestId);
            assistant.status = "disconnected";
            assistant.error = error.message || String(error);
            assistantMessage("system", `Could not send: ${assistant.error}`);
            refreshAssistant();
        }
    }

    function stopAssistant() {
        if (!assistant.activeRequest) return;
        if (!assistant.client.cancel(assistant.activeRequest)) {
            assistant.error = "The bridge is disconnected; the local request may finish without being delivered.";
            refreshAssistant();
        } else {
            assistant.statusDetail = "Stopping agent…";
            refreshAssistant();
        }
    }

    function resetAssistantChat() {
        if (assistant.activeRequest) assistant.client.cancel(assistant.activeRequest);
        assistant.client.reset();
        assistant.activeRequest = null;
        assistant.requestContexts.clear();
        assistant.messages = [];
        assistant.error = "";
        assistant.statusDetail = "New isolated conversation";
        refreshAssistant();
    }

    function copyAssistantDraft(draft) {
        const operation = navigator.clipboard?.writeText?.(draft.proposed);
        if (!operation) {
            assistant.error = "Clipboard access is unavailable. Select the proposed text and copy it manually.";
            refreshAssistant();
            return;
        }
        operation.then(() => {
            assistantMessage("system", "Proposed prompt copied.");
            refreshAssistant();
        }).catch(() => {
            assistant.error = "Clipboard access was refused. Select the proposed text and copy it manually.";
            refreshAssistant();
        });
    }

    function applyAssistantDraft(draft, promptTextarea, conflict) {
        if (conflict.stale && !window.confirm(
            `${conflict.reason}\n\nApply this draft anyway and replace the current scene prompt?`,
        )) return;
        const before = promptTextarea.value;
        const after = draft.proposed;
        assistant.lastApplied = {
            sceneKey: promptSceneKey(draft.sceneId, draft.sceneIndex),
            before,
            after,
        };
        promptTextarea.value = after;
        promptTextarea.dispatchEvent(new Event("input", {bubbles: true}));
        assistant.drafts.delete(promptSceneKey(draft.sceneId, draft.sceneIndex));
        assistantMessage("system", "Draft applied to the active scene and saved in the connected Plan.");
        refreshAssistant();
    }

    function undoAssistantApply(promptTextarea, sceneKey) {
        const undo = assistant.lastApplied;
        if (!undo || undo.sceneKey !== sceneKey || promptTextarea.value !== undo.after) return;
        promptTextarea.value = undo.before;
        promptTextarea.dispatchEvent(new Event("input", {bubbles: true}));
        assistant.lastApplied = null;
        assistantMessage("system", "The last assistant apply was undone.");
        refreshAssistant();
    }

    function renderAssistant(host, promptTextarea) {
        host.replaceChildren();
        const shot = state.plan.shots[state.active];
        const sceneId = String(shot.id || `clip_${String(state.active + 1).padStart(4, "0")}`);
        const sceneKey = promptSceneKey(sceneId, state.active);

        const head = element("div", "h3sp-assist-head");
        const heading = element("span", "h3sp-assist-title", "Prompt Assistant");
        const statusText = assistant.activeRequest
            ? assistant.statusDetail || "Agent is working…"
            : assistant.statusDetail;
        head.append(heading, element("span", "h3sp-assist-status", statusText));

        const controls = element("div", "h3sp-assist-controls");
        const provider = element("select");
        provider.title = "Choose which isolated local agent handles this prompt turn.";
        for (const [id, label] of [["codex", "Codex"], ["hermes", "Hermes"]]) {
            const option = element("option", "", label);
            option.value = id;
            const available = assistant.providers?.find((item) => item.id === id)?.available;
            if (available === false) {
                option.textContent = `${label} (not found)`;
                option.disabled = true;
            }
            provider.append(option);
        }
        provider.value = assistant.provider;
        provider.disabled = Boolean(assistant.activeRequest);
        provider.addEventListener("change", () => {
            assistant.provider = provider.value;
            node.properties[ASSIST_PROVIDER_PROPERTY] = assistant.provider;
            persistView();
        });
        const mode = element("select");
        mode.title = "Choose the kind of help to request.";
        for (const item of PROMPT_ASSIST_MODES) {
            const option = element("option", "", item.label);
            option.value = item.id;
            mode.append(option);
        }
        mode.value = assistant.mode;
        mode.disabled = Boolean(assistant.activeRequest);
        mode.addEventListener("change", () => {
            assistant.mode = mode.value;
            node.properties[ASSIST_MODE_PROPERTY] = assistant.mode;
            persistView();
            refreshAssistant();
        });
        controls.append(provider, mode, button("New chat", "Clear agent conversation; staged drafts remain.", resetAssistantChat));

        const chat = element("div", "h3sp-assist-chat");
        if (!assistant.messages.length) {
            chat.append(element(
                "div", "h3sp-assist-empty",
                "Ask for a rewrite, continuity pass, critique, or a specific change. Nothing is applied until you press Apply.",
            ));
        } else {
            for (const message of assistant.messages) {
                chat.append(element(
                    "div",
                    `h3sp-assist-message h3sp-assist-message-${message.role}`,
                    message.text,
                ));
            }
            setTimeout(() => { chat.scrollTop = chat.scrollHeight; }, 0);
        }

        const draft = assistant.drafts.get(sceneKey);
        let draftPanel = null;
        if (draft) {
            const conflict = draftConflict(draft, sceneId, promptTextarea.value);
            draftPanel = element("div", "h3sp-assist-draft");
            const draftHead = element("div", "h3sp-assist-draft-head");
            draftHead.append(
                element("span", "h3sp-assist-draft-title", `Staged ${draft.provider || "agent"} proposal`),
                conflict.stale ? element("span", "h3sp-assist-stale", conflict.reason) : element("span"),
            );
            const proposed = element("textarea");
            proposed.value = draft.proposed;
            proposed.title = "You can edit the staged proposal before applying it.";
            proposed.addEventListener("input", () => { draft.proposed = proposed.value; });
            const original = element("details", "h3sp-assist-original");
            original.append(
                element("summary", "", "Compare with original"),
                element("pre", "", draft.sourcePrompt),
            );
            const actions = element("div", "h3sp-assist-actions");
            actions.append(
                button(
                    conflict.stale ? "Apply anyway…" : "Apply to scene",
                    "Replace the real active scene prompt in the connected Plan.",
                    () => applyAssistantDraft(draft, promptTextarea, conflict),
                ),
                button("Copy", "Copy the proposed prompt without changing the Plan.", () => copyAssistantDraft(draft)),
                button("Discard", "Remove this staged proposal without changing the Plan.", () => {
                    assistant.drafts.delete(sceneKey);
                    refreshAssistant();
                }),
            );
            draftPanel.append(draftHead, proposed, original, actions);
        }

        const contexts = element("div", "h3sp-assist-contexts");
        const contextToggle = (label, checked, change, title) => {
            const wrapper = element("label");
            wrapper.title = title;
            const input = element("input");
            input.type = "checkbox";
            input.checked = checked;
            input.disabled = Boolean(assistant.activeRequest);
            input.addEventListener("change", () => change(input.checked));
            wrapper.append(input, document.createTextNode(label));
            return wrapper;
        };
        contexts.append(
            contextToggle("Shared prompt", assistant.includeShared, (value) => {
                assistant.includeShared = value;
            }, "Include the Plan's shared/global prompt as read-only context."),
            contextToggle("Previous + next", assistant.includeAdjacent, (value) => {
                assistant.includeAdjacent = value;
            }, "Include adjacent scene prompts for continuity advice."),
            element("span", "h3sp-assist-status", "Selected text is included automatically"),
        );

        const compose = element("div", "h3sp-assist-compose");
        const composer = element("textarea");
        composer.value = assistant.composer;
        composer.placeholder = PROMPT_ASSIST_DEFAULT_INSTRUCTIONS[assistant.mode];
        composer.disabled = Boolean(assistant.activeRequest);
        composer.addEventListener("input", () => { assistant.composer = composer.value; });
        composer.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                void sendAssistant(promptTextarea);
            }
        });
        const send = button("Ask agent", "Send (Ctrl/Cmd+Enter). The response is staged, never auto-applied.", () => {
            void sendAssistant(promptTextarea);
        });
        send.disabled = Boolean(assistant.activeRequest);
        compose.append(composer, send);
        if (assistant.activeRequest) {
            compose.append(button("Stop", "Interrupt this prompt-assist request.", stopAssistant));
        }

        const error = assistant.error
            ? element("div", "h3sp-assist-error", assistant.error) : null;
        const undo = assistant.lastApplied;
        const undoButton = undo?.sceneKey === sceneKey && promptTextarea.value === undo.after
            ? button("Undo last apply", "Restore the prompt that existed before the last assistant Apply.", () => {
                undoAssistantApply(promptTextarea, sceneKey);
            }) : null;

        host.append(head, controls, chat);
        if (draftPanel) host.append(draftPanel);
        host.append(contexts, compose);
        if (undoButton) host.append(undoButton);
        if (error) host.append(error);
    }

    function showFailure(message) {
        assistant.host = null;
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
        assistant.host = null;
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
            refreshAssistant();
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

        const assistantHost = element("div", "h3sp-assist");
        assistant.host = assistantHost;
        renderAssistant(assistantHost, textarea);
        root.append(head, nav, tools, refs, textarea, assistantHost, footer);
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
        {serialize: false, hideOnZoom: false, getMinHeight: () => 760},
    );
    widget.serialize = false;
    node.setSize?.([
        Math.max(node.size?.[0] ?? 760, 760),
        Math.max(node.size?.[1] ?? 900, 900),
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
        assistant.client?.close();
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
