export const PLAN_STUDIO_NODE_TYPE = "MiniMaxH3ChainPlanStudio";
export const PROMPT_EDITOR_NODE_TYPES = Object.freeze([
    "MiniMaxH3ChainScenePromptEditor",
    "MiniMaxH3ChainRichScenePromptEditor",
]);

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function graphLink(graph, linkId) {
    return graph?.links?.[linkId] ?? graph?.links?.get?.(linkId) ?? null;
}

/** Direct PLAN neighbours in either direction. Keeping this adjacency-scoped
 * means two independent editor branches may share a Plan without unexpectedly
 * taking over each other's scene selection. */
export function adjacentPlanCompanions(node) {
    const graph = node?.graph;
    const found = [];
    const seen = new Set();
    const add = (candidate) => {
        if (!candidate || candidate === node || seen.has(candidate)) return;
        seen.add(candidate);
        found.push(candidate);
    };
    for (const input of node?.inputs ?? []) {
        if (input.link == null) continue;
        const link = graphLink(graph, input.link);
        add(link ? graph?.getNodeById?.(link.origin_id) : null);
    }
    for (const output of node?.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = graphLink(graph, linkId);
            add(link ? graph?.getNodeById?.(link.target_id) : null);
        }
    }
    return found;
}

export function connectedPromptEditors(node) {
    const allowed = new Set(PROMPT_EDITOR_NODE_TYPES);
    return adjacentPlanCompanions(node).filter((candidate) => allowed.has(nodeType(candidate)));
}

export function connectedPlanStudios(node) {
    return adjacentPlanCompanions(node).filter(
        (candidate) => nodeType(candidate) === PLAN_STUDIO_NODE_TYPE,
    );
}

/** Merge a dedicated editor's active prompt onto a freshly parsed Plan while
 * preserving the local Plan and active-shot object identities. DOM input
 * handlers commonly close over that shot object; replacing it after the first
 * keystroke would make later keystrokes write into a detached object. */
export function rebaseScenePrompt(localPlan, livePlan, sceneIndex) {
    if (!Array.isArray(localPlan?.shots) || !Array.isArray(livePlan?.shots)) return -1;
    const localIndex = Math.max(0, Math.trunc(Number(sceneIndex) || 0));
    const editedShot = localPlan.shots[localIndex];
    if (!editedShot) return -1;
    const editedId = String(editedShot.id ?? "").trim();
    const targetIndex = editedId
        ? livePlan.shots.findIndex((shot) => String(shot?.id ?? "").trim() === editedId)
        : localIndex;
    if (targetIndex < 0 || targetIndex >= livePlan.shots.length) return -1;

    const targetShot = livePlan.shots[targetIndex];
    targetShot.prompt = Array.isArray(editedShot.prompt)
        ? [...editedShot.prompt] : editedShot.prompt;
    for (const key of Object.keys(editedShot)) delete editedShot[key];
    Object.assign(editedShot, targetShot);
    livePlan.shots[targetIndex] = editedShot;

    for (const key of Object.keys(localPlan)) delete localPlan[key];
    Object.assign(localPlan, livePlan);
    return targetIndex;
}

/** Transient UI coordination only: no selection state is added to the Plan or
 * workflow. Receivers verify that they currently resolve the same Plan node. */
export function publishCompanionScene(source, planNode, sceneIndex) {
    const index = Math.max(0, Math.trunc(Number(sceneIndex) || 0));
    let delivered = 0;
    for (const candidate of adjacentPlanCompanions(source)) {
        const apply = candidate?._h3PromptCompanionSetActiveScene;
        if (typeof apply !== "function") continue;
        try {
            if (apply.call(candidate, planNode, index, source) !== false) delivered += 1;
        } catch (_error) {
            // A companion UI must never break navigation in the source node.
        }
    }
    return delivered;
}
