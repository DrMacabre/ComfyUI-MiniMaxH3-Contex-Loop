import {app} from "/scripts/app.js";
import {api} from "/scripts/api.js";
import {parsePlanJson, planToJson} from "./h3_chain_plan_core.mjs";
import {applyReviewEdit, reviewSeed} from "./h3_chain_review_core.mjs";

const NODE_NAME = "MiniMaxH3ChainReview";
const PLAN_NAME = "MiniMaxH3ChainPlan";

function injectStyles() {
    if (document.getElementById("h3-chain-review-style")) return;
    const style = document.createElement("style");
    style.id = "h3-chain-review-style";
    style.textContent = `
        .h3r-root { box-sizing:border-box; display:flex; flex-direction:column; gap:8px;
            min-height:500px; padding:9px; overflow:auto; border:1px solid #56637e;
            border-radius:8px; background:#181a20; color:#e8eaf0; font:12px/1.35 system-ui,sans-serif; }
        .h3r-root * { box-sizing:border-box; }
        .h3r-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .h3r-title { font-weight:750; color:#a9c2ff; }
        .h3r-badge { color:#d5d9e3; opacity:.75; }
        .h3r-video { width:100%; min-height:220px; max-height:420px; border-radius:6px;
            background:#08090c; object-fit:contain; }
        .h3r-label { display:flex; flex-direction:column; gap:4px; color:#aeb5c5; }
        .h3r-prompt { width:100%; min-height:120px; resize:vertical; padding:7px;
            border:1px solid #56637e; border-radius:5px; background:#101218; color:#eef1f7; }
        .h3r-row { display:flex; align-items:center; gap:7px; }
        .h3r-seed { flex:1; min-width:0; padding:6px 7px; border:1px solid #56637e;
            border-radius:5px; background:#101218; color:#eef1f7; }
        .h3r-actions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }
        .h3r-button { padding:7px; border:1px solid #63708b; border-radius:5px;
            background:#292e3a; color:#eef1f7; cursor:pointer; }
        .h3r-button:hover { background:#343b4b; }
        .h3r-approve { border-color:#4b9d72; background:#204332; }
        .h3r-retry { border-color:#b58b45; background:#4a3820; }
        .h3r-stop { border-color:#8a6171; background:#3b252d; }
        .h3r-status { min-height:18px; color:#aeb5c5; white-space:pre-wrap; }
        .h3r-warning { color:#f2bd67; }
        .h3r-prefix { margin:0; padding:6px 7px; max-height:90px; overflow:auto;
            border-left:2px solid #56637e; color:#aeb5c5; white-space:pre-wrap; }
        .h3r-root.h3r-busy .h3r-button { opacity:.45; pointer-events:none; }
    `;
    document.head.appendChild(style);
}

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function findNodeByQualifiedId(qid) {
    if (!app.graph || qid == null) return null;
    const parts = String(qid).split(":");
    let graph = app.graph;
    for (let i = 0; i < parts.length - 1; i += 1) {
        const id = Number(parts[i]);
        const parent = Number.isFinite(id) ? graph?.getNodeById?.(id) : null;
        if (!parent?.subgraph) return null;
        graph = parent.subgraph;
    }
    const leaf = Number(parts.at(-1));
    return Number.isFinite(leaf) ? graph?.getNodeById?.(leaf) ?? null : null;
}

function allNodes(graph, output = []) {
    for (const node of graph?._nodes ?? []) {
        output.push(node);
        if (node.subgraph) allNodes(node.subgraph, output);
    }
    return output;
}

function findUpstreamNode(start, wantedType) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (node !== start && nodeType(node) === wantedType) return node;
        for (const input of node.inputs ?? []) {
            if (input.link == null) continue;
            const link = node.graph?.links?.[input.link];
            const parent = link ? node.graph?.getNodeById?.(link.origin_id) : null;
            if (parent) queue.push(parent);
        }
    }
    return null;
}

function videoUrl(item) {
    const query = new URLSearchParams({
        filename: item.filename,
        subfolder: item.subfolder ?? "",
        type: item.type ?? "output",
    });
    return api.apiURL(`/view?${query.toString()}`);
}

function updatePlan(reviewNode, index, prompt, seed) {
    const planNode = findUpstreamNode(reviewNode, PLAN_NAME) ??
        allNodes(app.graph).find((item) => nodeType(item) === PLAN_NAME);
    const widget = planNode?.widgets?.find((item) => item.name === "plan_json");
    if (!widget) return false;
    const plan = applyReviewEdit(
        parsePlanJson(String(widget.value ?? "")), index, prompt, seed,
    );
    const value = planToJson(plan);
    widget.value = value;
    widget.callback?.(value);
    planNode._h3ChainEditorRefresh?.();
    planNode.graph?.setDirtyCanvas?.(true, true);
    return true;
}

function prepareResume(reviewNode, nextIndex) {
    const startNode = findUpstreamNode(reviewNode, "MiniMaxH3ChainLoopStart") ??
        allNodes(app.graph).find((item) => nodeType(item) === "MiniMaxH3ChainLoopStart");
    const widget = startNode?.widgets?.find((item) => item.name === "start_clip");
    if (!widget) return false;
    widget.value = nextIndex;
    widget.callback?.(nextIndex);
    startNode.graph?.setDirtyCanvas?.(true, true);
    return true;
}

async function fetchPending() {
    try {
        const response = await api.fetchApi("/h3_motion_context/reviews");
        if (!response.ok) return;
        const body = await response.json();
        for (const review of body.reviews ?? []) routeReview(review);
    } catch (error) {
        console.warn("[H3 Chain Review] Could not recover pending reviews:", error);
    }
}

function routeReview(data) {
    const node = findNodeByQualifiedId(data?.node_id);
    node?._h3ReviewHandler?.(data);
}

function mount(node) {
    if (node._h3ReviewMounted || typeof node.addDOMWidget !== "function") return;
    node._h3ReviewMounted = true;
    injectStyles();

    const root = document.createElement("div");
    root.className = "h3r-root";
    root.addEventListener("mousedown", (event) => event.stopPropagation());
    root.addEventListener("wheel", (event) => event.stopPropagation());

    const head = document.createElement("div");
    head.className = "h3r-head";
    const title = document.createElement("span");
    title.className = "h3r-title";
    title.textContent = "H3 Segment Review";
    const badge = document.createElement("span");
    badge.className = "h3r-badge";
    badge.textContent = "waiting for segment…";
    head.append(title, badge);

    const video = document.createElement("video");
    video.className = "h3r-video";
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;

    const prefix = document.createElement("pre");
    prefix.className = "h3r-prefix";
    prefix.hidden = true;

    const promptLabel = document.createElement("label");
    promptLabel.className = "h3r-label";
    promptLabel.append("Scene prompt (used when retrying)");
    const prompt = document.createElement("textarea");
    prompt.className = "h3r-prompt";
    promptLabel.append(prompt);

    const seedRow = document.createElement("label");
    seedRow.className = "h3r-row";
    seedRow.append("Seed");
    const seed = document.createElement("input");
    seed.className = "h3r-seed";
    seed.inputMode = "numeric";
    seedRow.append(seed);

    const actions = document.createElement("div");
    actions.className = "h3r-actions";
    function actionButton(label, className, action) {
        const button = document.createElement("button");
        button.className = `h3r-button ${className}`;
        button.textContent = label;
        button.type = "button";
        button.addEventListener("click", () => submit(action));
        actions.append(button);
        return button;
    }
    actionButton("Approve & continue", "h3r-approve", "approve");
    actionButton("Retry prompt / seed", "h3r-retry", "retry");
    actionButton("Reroll seed", "h3r-retry", "reroll");
    actionButton("Approve & stop", "h3r-stop", "stop");

    const status = document.createElement("div");
    status.className = "h3r-status";
    status.textContent = "The loop will pause here after each saved segment.";
    root.append(head, video, prefix, promptLabel, seedRow, actions, status);

    let current = null;
    async function submit(action) {
        if (!current?.token) return;
        try {
            const normalizedSeed = action === "retry" ? reviewSeed(seed.value) : seed.value;
            root.classList.add("h3r-busy");
            status.className = "h3r-status";
            status.textContent = action === "approve" ? "Continuing…" :
                action === "stop" ? "Stopping at the saved checkpoint…" : "Preparing retry…";
            const response = await api.fetchApi("/h3_motion_context/review", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    token: current.token,
                    action,
                    scene_prompt: prompt.value,
                    seed: normalizedSeed,
                }),
            });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
            if (action === "retry" || action === "reroll") {
                seed.value = body.seed;
                const saved = updatePlan(node, current.clip_index, prompt.value, body.seed);
                status.textContent = `Retrying scene with seed ${body.seed}.` +
                    (saved ? " The Plan editor was updated." : "");
            } else if (action === "stop") {
                const prepared = current.clip_index < current.clip_count &&
                    prepareResume(node, current.clip_index + 1);
                status.textContent = "Stopped at the accepted checkpoint." +
                    (prepared ? ` Loop Start is ready at clip ${current.clip_index + 1}.` : "");
            }
        } catch (error) {
            root.classList.remove("h3r-busy");
            status.className = "h3r-status h3r-warning";
            status.textContent = error.message;
        }
    }

    node._h3ReviewHandler = (data) => {
        current = data;
        root.classList.remove("h3r-busy");
        badge.textContent = `clip ${data.clip_index}/${data.clip_count} · ${data.shot_id}`;
        video.src = videoUrl(data.video);
        video.load();
        prompt.value = data.scene_prompt ?? "";
        seed.value = data.seed ?? "";
        prefix.textContent = data.prompt_prefix ? `Shared prompt (unchanged)\n${data.prompt_prefix}` : "";
        prefix.hidden = !data.prompt_prefix;
        status.className = `h3r-status${data.warning ? " h3r-warning" : ""}`;
        status.textContent = data.warning || "Review the synchronized picture and sound, then choose an action.";
    };

    const widget = node.addDOMWidget("h3_chain_review", "h3-chain-review", root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 500,
    });
    widget.serialize = false;
    node.setSize?.([Math.max(node.size?.[0] ?? 540, 540), Math.max(node.size?.[1] ?? 650, 650)]);
    setTimeout(fetchPending, 0);
}

api.addEventListener("h3_chain_review", (event) => routeReview(event.detail));

app.registerExtension({
    name: "h3_motion_context.chain_review",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            setTimeout(() => mount(this), 0);
            return result;
        };
    },
    async afterConfigureGraph() {
        await fetchPending();
    },
});
