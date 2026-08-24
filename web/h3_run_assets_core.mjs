export const MAX_ASSET_BINDINGS = 12;
export const ASSET_ROLES = Object.freeze([
    ["picture", "Picture"],
    ["video", "Video"],
    ["audio_reference", "Audio reference"],
    ["source_track", "Source track"],
]);
export const SEMANTIC_ANCHOR_BUNDLE_NODE = "MiniMaxH3SemanticAnchorBundle";
export const SEMANTIC_PICTURE_ANCHOR_NODE = "MiniMaxH3SemanticPictureAnchor";

const MEDIA_WIDGET_NAMES = ["image", "audio", "file", "video", "path", "filename"];
const MEDIA_EXTENSION = /\.(?:png|jpe?g|webp|gif|bmp|tiff?|wav|mp3|flac|ogg|m4a|aac|mp4|mov|mkv|webm|avi)(?:\s+\[(?:input|output|temp)\])?$/i;

export function assetInputNumber(input) {
    const match = /^asset_(\d+)$/.exec(String(input?.name ?? ""));
    return match ? Number(match[1]) : null;
}

export function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? "";
}

export function mediaWidget(node, preferred = "") {
    const widgets = node?.widgets ?? [];
    if (preferred) {
        const exact = widgets.find((widget) => widget.name === preferred);
        if (exact) return exact;
    }
    for (const name of MEDIA_WIDGET_NAMES) {
        const widget = widgets.find((item) => item.name === name
            && typeof item.value === "string");
        if (widget) return widget;
    }
    return widgets.find((widget) => typeof widget.value === "string"
        && MEDIA_EXTENSION.test(widget.value.trim())) ?? null;
}

export function inferAssetRole(outputType, sourceType = "") {
    const type = String(outputType ?? "").toUpperCase();
    if (type === "VIDEO" || /video/i.test(sourceType)) return "video";
    if (type === "AUDIO" || /audio/i.test(sourceType)) return "audio_reference";
    return "picture";
}

function randomBindingId() {
    if (typeof globalThis.crypto?.randomUUID === "function") {
        return globalThis.crypto.randomUUID();
    }
    const random = Math.random().toString(16).slice(2);
    return `asset-${Date.now().toString(16)}-${random}`;
}

function sourceForInput(manager, input) {
    const link = input?.link == null ? null : manager?.graph?.links?.[input.link];
    const source = link ? manager.graph?.getNodeById?.(link.origin_id) : null;
    return source ? {source, link} : null;
}

function inputByName(node, name) {
    return node?.inputs?.find((input) => input.name === name) ?? null;
}

function linkedNode(node, inputName) {
    const input = inputByName(node, inputName);
    const link = input?.link == null ? null : node?.graph?.links?.[input.link];
    const source = link ? node.graph?.getNodeById?.(link.origin_id) : null;
    return source ? {source, link, input} : null;
}

function sourceBinding(manager, source, link, createId, {
    input = null, roleOverride = "", labelPrefix = "",
} = {}) {
    source.properties ??= {};
    const outputSlot = Number(link.origin_slot) || 0;
    source.properties.h3_asset_binding_ids ??= {};
    source.properties.h3_asset_binding_ids[outputSlot] ||= (
        (outputSlot === 0 && source.properties.h3_asset_binding_id)
        || createId()
    );
    const bindingId = source.properties.h3_asset_binding_ids[outputSlot];
    const output = source.outputs?.[outputSlot] ?? {};
    const widget = mediaWidget(source);
    const inferred = roleOverride || inferAssetRole(output.type, nodeType(source));
    const role = manager.properties.h3_asset_roles[bindingId] ?? inferred;
    manager.properties.h3_asset_roles[bindingId] = role;
    const title = String(source.title || nodeType(source) || `Node ${source.id}`);
    if (input) input.label = `${assetInputNumber(input)}: ${title}`;
    return {
        binding_id: bindingId,
        label: labelPrefix ? `${labelPrefix} · ${title}` : title,
        role,
        node_id: String(source.id ?? ""),
        node_type: nodeType(source),
        node_title: String(source.title ?? ""),
        output_slot: outputSlot,
        output_type: String(output.type ?? ""),
        widget_name: String(widget?.name ?? ""),
        original_value: typeof widget?.value === "string" ? widget.value : "",
    };
}

export function collectSemanticAnchorBindings(manager, createId = randomBindingId) {
    manager.properties ??= {};
    manager.properties.h3_asset_roles ??= {};
    const bundleLink = linkedNode(manager, "tagged_references");
    if (!bundleLink || nodeType(bundleLink.source) !== SEMANTIC_ANCHOR_BUNDLE_NODE) {
        return [];
    }
    const bindings = [];
    const seenNodes = new Set();
    let linked = linkedNode(bundleLink.source, "anchors");
    while (linked && nodeType(linked.source) === SEMANTIC_PICTURE_ANCHOR_NODE
            && !seenNodes.has(linked.source)) {
        const anchor = linked.source;
        seenNodes.add(anchor);
        const tag = String(anchor.widgets?.find((item) => item.name === "tag")?.value
            ?? "semantic").trim();
        const image = linkedNode(anchor, "image");
        if (image) {
            bindings.push(sourceBinding(manager, image.source, image.link, createId, {
                roleOverride: "picture",
                labelPrefix: `#${tag || "semantic"}`,
            }));
        }
        linked = linkedNode(anchor, "previous");
    }
    return bindings.reverse();
}

export function collectAssetBindings(manager, createId = randomBindingId) {
    manager.properties ??= {};
    manager.properties.h3_asset_roles ??= {};
    const bindings = [];
    for (const input of manager.inputs ?? []) {
        const number = assetInputNumber(input);
        if (number == null || input.link == null) continue;
        const linked = sourceForInput(manager, input);
        if (!linked) continue;
        const {source, link} = linked;
        bindings.push(sourceBinding(
            manager, source, link, createId, {input}));
    }
    const seen = new Set(bindings.map((binding) => binding.binding_id));
    for (const binding of collectSemanticAnchorBindings(manager, createId)) {
        if (seen.has(binding.binding_id)) continue;
        seen.add(binding.binding_id);
        bindings.push(binding);
    }
    return bindings;
}

function graphNodes(graph) {
    return graph?._nodes ?? graph?.nodes ?? [];
}

function compatibleLoader(node, binding) {
    const widget = mediaWidget(node, binding.widget_name);
    if (!widget) return false;
    const output = node.outputs?.[Number(binding.output_slot)]
        ?? node.outputs?.find((item) => item.type === binding.output_type);
    return !binding.output_type || output?.type === binding.output_type;
}

export function findAssetTarget(graph, binding) {
    const nodes = graphNodes(graph);
    const persistent = nodes.filter((node) =>
        (node?.properties?.h3_asset_binding_ids?.[Number(binding.output_slot)]
            === binding.binding_id
        || node?.properties?.h3_asset_binding_id === binding.binding_id)
        && compatibleLoader(node, binding));
    if (persistent.length === 1) return {node: persistent[0], match: "binding"};

    const byId = graph?.getNodeById?.(binding.node_id)
        ?? graph?.getNodeById?.(Number(binding.node_id));
    if (byId && nodeType(byId) === binding.node_type
            && compatibleLoader(byId, binding)) {
        return {node: byId, match: "node_id"};
    }

    const sameType = nodes.filter((node) => nodeType(node) === binding.node_type
        && compatibleLoader(node, binding));
    if (sameType.length === 1) return {node: sameType[0], match: "compatible_type"};

    const compatible = nodes.filter((node) => compatibleLoader(node, binding));
    if (compatible.length === 1) return {node: compatible[0], match: "compatible_loader"};
    return {
        node: null,
        match: compatible.length || sameType.length || persistent.length
            ? "ambiguous" : "missing",
    };
}

export function applyAssetBinding(graph, binding) {
    if (!binding?.restore_value) {
        return {applied: false, reason: "media_missing", binding};
    }
    const target = findAssetTarget(graph, binding);
    if (!target.node) return {applied: false, reason: target.match, binding};
    const widget = mediaWidget(target.node, binding.widget_name);
    if (!widget) return {applied: false, reason: "widget_missing", binding};
    const previous = widget.value;
    const options = widget.options?.values;
    if (Array.isArray(options) && !options.includes(binding.restore_value)) {
        options.push(binding.restore_value);
        options.sort((left, right) => String(left).localeCompare(String(right)));
    }
    widget.value = binding.restore_value;
    widget.callback?.(binding.restore_value);
    target.node.onWidgetChanged?.(
        widget.name, binding.restore_value, previous, widget);
    target.node.properties ??= {};
    target.node.properties.h3_asset_binding_ids ??= {};
    target.node.properties.h3_asset_binding_ids[Number(binding.output_slot) || 0]
        = binding.binding_id;
    return {applied: true, match: target.match, node: target.node, binding};
}
