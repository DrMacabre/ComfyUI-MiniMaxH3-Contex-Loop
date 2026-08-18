const POLICY_SPECS = Object.freeze({
    audio_policy: Object.freeze({
        nodeType: "MiniMaxH3AudioPolicy",
        widgets: Object.freeze([
            "final_audio", "source_reference", "generated_continuity",
        ]),
    }),
    transition_policy: Object.freeze({
        nodeType: "MiniMaxH3TransitionPolicy",
        widgets: Object.freeze([
            "preset", "expert_override", "expert_continuation_mode",
            "expert_context_length",
        ]),
    }),
});

function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function graphLink(graph, linkId) {
    return graph?.links?.[linkId] ?? graph?.links?.get?.(linkId) ?? null;
}

function widgetByName(node, name) {
    return node?.widgets?.find((item) => item.name === name);
}

function allNodes(graph, output = []) {
    for (const node of graph?._nodes ?? []) {
        output.push(node);
        if (node.subgraph) allNodes(node.subgraph, output);
    }
    return output;
}

function linkedInputOrigin(node, inputName) {
    const input = node?.inputs?.find((item) => item.name === inputName);
    if (input?.link == null) return null;
    const link = graphLink(node.graph, input.link);
    return link ? node.graph?.getNodeById?.(link.origin_id) ?? null : null;
}

function findUpstreamType(start, wantedType) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (nodeType(node) === wantedType) return node;
        for (const input of node.inputs ?? []) {
            if (input.link == null) continue;
            const link = graphLink(node.graph, input.link);
            const parent = link ? node.graph?.getNodeById?.(link.origin_id) : null;
            if (parent) queue.push(parent);
        }
    }
    return null;
}

/** Restore normalized 0.5 policy records onto the policy nodes already wired
 * into Plan. Connections are never replaced or invented. */
export function restoreConnectedPolicyInputs(planNode, policyInputs) {
    const applied = [];
    const unavailable = [];
    if (!policyInputs || typeof policyInputs !== "object") {
        return {applied, unavailable};
    }
    const graph = planNode?.graph;
    graph?.beforeChange?.();
    try {
        for (const [inputName, spec] of Object.entries(POLICY_SPECS)) {
            const values = policyInputs[inputName];
            if (!values || typeof values !== "object") continue;
            const origin = linkedInputOrigin(planNode, inputName);
            const policyNode = findUpstreamType(origin, spec.nodeType);
            if (!policyNode) {
                unavailable.push(`${inputName} (no connected ${spec.nodeType})`);
                continue;
            }
            let complete = true;
            for (const name of spec.widgets) {
                if (!Object.hasOwn(values, name)) continue;
                const widget = widgetByName(policyNode, name);
                if (!widget) {
                    unavailable.push(`${inputName}.${name}`);
                    complete = false;
                    continue;
                }
                widget.value = values[name];
                widget.callback?.(values[name]);
            }
            policyNode.graph?.setDirtyCanvas?.(true, true);
            if (complete) applied.push(inputName);
        }
    } finally {
        graph?.afterChange?.();
    }
    return {applied, unavailable};
}

/** Force every authoring surface bound to the restored Plan to reparse it.
 * This avoids waiting for polling and prevents a prompt editor from continuing
 * to display a stale pre-restore scene prompt. */
export function refreshRestoredPlanEditors(planNode) {
    planNode?._h3ChainEditorRefresh?.();
    const graph = planNode?.graph?.rootGraph ?? planNode?.graph;
    for (const node of allNodes(graph)) {
        if (node === planNode) continue;
        node._h3ScenePromptEditorRefresh?.();
        node._h3RichPromptRefresh?.();
        node._h3PlanStudioRefresh?.();
    }
    planNode?.graph?.setDirtyCanvas?.(true, true);
    graph?.setDirtyCanvas?.(true, true);
}
