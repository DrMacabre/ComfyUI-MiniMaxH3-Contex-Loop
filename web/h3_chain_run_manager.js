import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";

const NODE_NAME = "MiniMaxH3ChainRunManager";
const PLAN_NAME = "MiniMaxH3ChainPlan";

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
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

function widgetByName(node, name) {
    return node?.widgets?.find((item) => item.name === name);
}

function element(tag, className = "", text = undefined) {
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

function injectStyles() {
    if (document.getElementById("h3-run-manager-style")) return;
    const style = document.createElement("style");
    style.id = "h3-run-manager-style";
    style.textContent = `
        .h3rm-root { --h3rm-bg:color-mix(in srgb,var(--comfy-menu-bg,#202124) 91%,#111827);
            --h3rm-panel:var(--comfy-input-bg,#15171d); --h3rm-border:var(--border-color,#586174);
            --h3rm-text:var(--input-text,#eceef5); --h3rm-muted:color-mix(in srgb,var(--h3rm-text) 58%,transparent);
            box-sizing:border-box; width:100%; height:100%; min-height:210px; display:flex;
            flex-direction:column; gap:9px; overflow:auto; padding:10px; border:1px solid var(--h3rm-border);
            border-radius:8px; background:var(--h3rm-bg); color:var(--h3rm-text);
            font:12px/1.4 system-ui,sans-serif; }
        .h3rm-root *, .h3rm-root *::before, .h3rm-root *::after { box-sizing:border-box; }
        .h3rm-title { font-size:15px; font-weight:750; }
        .h3rm-select { width:100%; min-width:0; padding:7px 8px; border:1px solid var(--h3rm-border);
            border-radius:6px; background:var(--h3rm-panel); color:var(--h3rm-text); }
        .h3rm-details { min-height:48px; padding:8px; border:1px solid color-mix(in srgb,var(--h3rm-border) 72%,transparent);
            border-radius:6px; background:var(--h3rm-panel); color:var(--h3rm-muted);
            white-space:pre-wrap; overflow-wrap:anywhere; }
        .h3rm-actions { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
        .h3rm-actions button { padding:6px 9px; border:1px solid var(--h3rm-border); border-radius:6px;
            background:var(--h3rm-panel); color:var(--h3rm-text); cursor:pointer; }
        .h3rm-actions button:hover { border-color:#7fa8ff; }
        .h3rm-actions button:disabled { cursor:not-allowed; opacity:.45; }
        .h3rm-load { font-weight:700; border-color:#6d91d8 !important; }
        .h3rm-status { min-width:0; flex:1 1 170px; color:var(--h3rm-muted); text-align:right;
            white-space:pre-wrap; overflow-wrap:anywhere; }
        .h3rm-error { color:#ffb3b3; }
    `;
    document.head.appendChild(style);
}

function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 1) return "0 KB";
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function localTime(value) {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString() : "unknown time";
}

async function jsonRequest(path) {
    const response = await api.fetchApi(path);
    let payload = {};
    try {
        payload = await response.json();
    } catch (_error) {
        // Preserve a useful HTTP error when a proxy emits a non-JSON body.
    }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
}

function applyPlanInputs(planNode, inputs) {
    if (!planNode) throw new Error("Connect this Run Manager to the active H3 Chain Plan.");
    if (!inputs || typeof inputs !== "object") throw new Error("The saved run has no Plan inputs.");
    const names = Object.keys(inputs).sort((left, right) =>
        Number(left === "plan_json") - Number(right === "plan_json"));
    const applied = [];
    const unavailable = [];
    const graph = planNode.graph ?? app.graph;
    graph?.beforeChange?.();
    try {
        for (const name of names) {
            const widget = widgetByName(planNode, name);
            if (!widget) {
                unavailable.push(name);
                continue;
            }
            widget.value = inputs[name];
            widget.callback?.(inputs[name]);
            applied.push(name);
        }
    } finally {
        graph?.afterChange?.();
    }
    if (!applied.includes("plan_json")) {
        throw new Error("The connected Plan does not expose an editable plan_json widget.");
    }
    planNode._h3ChainEditorRefresh?.();
    planNode.graph?.setDirtyCanvas?.(true, true);
    app.graph?.setDirtyCanvas?.(true, true);
    return {applied, unavailable};
}

function mount(node) {
    if (node._h3RunManagerMounted || typeof node.addDOMWidget !== "function") return;
    node._h3RunManagerMounted = true;
    injectStyles();

    const root = element("div", "h3rm-root");
    for (const eventName of [
        "pointerdown", "pointerup", "mousedown", "mouseup", "click", "dblclick",
    ]) root.addEventListener(eventName, (event) => event.stopPropagation());
    root.addEventListener("wheel", (event) => event.stopPropagation());

    const state = {runs: [], selected: "", busy: false};
    const title = element("div", "h3rm-title", "H3 Run Manager");
    const select = element("select", "h3rm-select");
    select.title = "Saved projects discovered under the ComfyUI host's output/h3_chains folder.";
    const details = element("div", "h3rm-details", "Loading saved runs…");
    const actions = element("div", "h3rm-actions");
    const status = element("span", "h3rm-status");

    function selectedRun() {
        return state.runs.find((item) => item.run_name === state.selected) ?? null;
    }

    function setBusy(value) {
        state.busy = Boolean(value);
        select.disabled = state.busy;
        refresh.disabled = state.busy;
        load.disabled = state.busy || !selectedRun()?.restorable;
        open.disabled = state.busy || !selectedRun();
    }

    function renderSelection() {
        const run = selectedRun();
        if (!run) {
            details.textContent = state.runs.length
                ? "Select a saved H3 run." : "No saved H3 runs were found.";
            load.disabled = true;
            open.disabled = true;
            return;
        }
        const scenes = run.scene_count == null ? "unknown scenes" : `${run.scene_count} scenes`;
        const source = Object.entries(run.sources ?? {}).filter(([, ready]) => ready)
            .map(([name]) => name.replace("_", " ")).join(", ") || "no archive";
        details.textContent =
            `${scenes} · ${run.checkpoint_count} checkpoints · ${formatBytes(run.archive_bytes)}\n` +
            `Modified ${localTime(run.modified_at)} · ${source}`;
        load.disabled = state.busy || !run.restorable;
        open.disabled = state.busy;
    }

    async function refreshRuns() {
        setBusy(true);
        status.className = "h3rm-status";
        status.textContent = "Scanning host output…";
        try {
            const payload = await jsonRequest("/minimax_h3_context_loop/runs");
            const previous = state.selected;
            state.runs = Array.isArray(payload.runs) ? payload.runs : [];
            state.selected = state.runs.some((item) => item.run_name === previous)
                ? previous
                : state.runs.find((item) => item.restorable)?.run_name
                    ?? state.runs[0]?.run_name ?? "";
            select.replaceChildren();
            for (const run of state.runs) {
                const suffix = run.scene_count == null ? "" : ` · ${run.scene_count} scenes`;
                const option = element("option", "", `${run.run_name}${suffix}`);
                option.value = run.run_name;
                option.disabled = !run.restorable;
                select.append(option);
            }
            select.value = state.selected;
            status.textContent = `${state.runs.length} saved run${state.runs.length === 1 ? "" : "s"}`;
        } catch (error) {
            state.runs = [];
            state.selected = "";
            select.replaceChildren();
            status.className = "h3rm-status h3rm-error";
            status.textContent = error?.message || String(error);
        } finally {
            setBusy(false);
            renderSelection();
        }
    }

    async function loadRun() {
        const run = selectedRun();
        const planNode = upstreamPlanNode(node);
        if (!run || !planNode || state.busy) {
            if (!planNode) {
                status.className = "h3rm-status h3rm-error";
                status.textContent = "Connect the active Plan first.";
            }
            return;
        }
        const current = String(widgetByName(planNode, "run_name")?.value ?? "").trim();
        const message = `Load saved run “${run.run_name}” into the connected Plan?\n\n` +
            `This replaces all active scene prompts and archived Plan settings${current ? ` from “${current}”` : ""}.`;
        if (!window.confirm(message)) return;
        setBusy(true);
        status.className = "h3rm-status";
        status.textContent = "Loading archive…";
        try {
            const query = new URLSearchParams({run_name: run.run_name});
            const payload = await jsonRequest(`/minimax_h3_context_loop/run?${query}`);
            const result = applyPlanInputs(planNode, payload.plan_inputs);
            const warning = [
                ...(payload.warnings ?? []),
                ...(result.unavailable.length
                    ? [`Unavailable current widgets: ${result.unavailable.join(", ")}`] : []),
            ];
            status.className = warning.length
                ? "h3rm-status h3rm-error" : "h3rm-status";
            status.textContent = warning.length
                ? `Loaded ${payload.scene_count ?? "saved"} scenes · ${warning.join(" · ")}`
                : `Loaded ${payload.scene_count ?? "saved"} scenes into Plan`;
        } catch (error) {
            status.className = "h3rm-status h3rm-error";
            status.textContent = error?.message || String(error);
        } finally {
            setBusy(false);
        }
    }

    async function openRunFolder() {
        const run = selectedRun();
        if (!run || state.busy) return;
        setBusy(true);
        status.className = "h3rm-status";
        status.textContent = "Opening run folder…";
        try {
            const response = await api.fetchApi(
                "/minimax_h3_context_loop/open-run-folder",
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({run_name: run.run_name}),
                },
            );
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            if (payload.opened) status.textContent = "Opened on ComfyUI host";
            else {
                try {
                    await navigator.clipboard.writeText(payload.path);
                    status.textContent = "Host path copied";
                } catch (_error) {
                    status.textContent = payload.path;
                }
                status.title = `${payload.path}${payload.error ? `\n${payload.error}` : ""}`;
            }
        } catch (error) {
            status.className = "h3rm-status h3rm-error";
            status.textContent = error?.message || String(error);
        } finally {
            setBusy(false);
        }
    }

    select.addEventListener("change", () => {
        state.selected = select.value;
        status.className = "h3rm-status";
        status.textContent = "";
        renderSelection();
    });
    const load = button("Load into Plan", "Replace the connected Plan after confirmation", () => {
        void loadRun();
    });
    load.classList.add("h3rm-load");
    const refresh = button("Refresh", "Rescan output/h3_chains on the ComfyUI host", () => {
        void refreshRuns();
    });
    const open = button("Open folder", "Open the selected run folder on the ComfyUI host", () => {
        void openRunFolder();
    });
    actions.append(load, refresh, open, status);
    root.append(title, select, details, actions);

    const widget = node.addDOMWidget("h3_run_manager", "h3-run-manager", root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 210,
    });
    widget.serialize = false;
    node.setSize?.([
        Math.max(Number(node.size?.[0]) || 0, 520),
        Math.max(Number(node.size?.[1]) || 0, 330),
    ]);
    const connectionsChanged = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const result = connectionsChanged?.apply(this, arguments);
        window.setTimeout(renderSelection, 0);
        return result;
    };
    void refreshRuns();
}

app.registerExtension({
    name: "minimax_h3_context_loop.run_manager",
    async beforeRegisterNodeDef(nodeTypeClass, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeTypeClass.prototype.onNodeCreated;
        nodeTypeClass.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            window.setTimeout(() => mount(this), 0);
            return result;
        };
    },
    async nodeCreated(node) {
        if (nodeType(node) === NODE_NAME) mount(node);
    },
});
