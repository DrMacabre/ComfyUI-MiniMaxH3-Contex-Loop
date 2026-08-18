export const AUDIO_POLICY_NODE = "MiniMaxH3AudioPolicy";
export const LEGACY_POLICY_NODE = "MiniMaxH3Legacy04PolicyAdapter";
export const PLAN_NODE = "MiniMaxH3ChainPlan";
export const TRANSITION_POLICY_NODE = "MiniMaxH3TransitionPolicy";

const LEGACY_AUDIO_POLICIES = Object.freeze({
    source_track: ["source", "on", "off"],
    generated_audio: ["generated", "off", "on"],
    source_plus_timeline: ["source", "on", "on"],
});

const TRANSITION_PRESETS = Object.freeze({
    cut: ["guide", 0],
    guide: ["guide", 22],
    detail_guide: ["tapered_guide", 22],
    hard_av: ["masked_av", 39],
    soft_av: ["feathered_av", 39],
    audio_feather_av: ["audio_feathered_av", 39],
});

const CONDITIONAL_SOURCE_AUDIO_NODES = new Set([
    "MiniMaxH3ChainLoopStart",
    "MiniMaxH3ChainPlanStudio",
    "MiniMaxH3ChainPreflight",
    "MiniMaxH3ChainManifestLoad",
]);

const CURRENT_NODE = "MiniMaxH3ChainCurrent";
const REVIEW_NODE = "MiniMaxH3ChainReview";
const ASSEMBLE_NODE = "MiniMaxH3ChainAssemble";

const ADVANCED_OUTPUTS = Object.freeze({
    MiniMaxH3TransitionPolicy: [
        "continuation_mode", "context_length", "status",
    ],
    MiniMaxH3ChainPlanStudio: ["status", "report_json"],
    MiniMaxH3ChainPreflight: ["status", "report_json"],
    MiniMaxH3LazyMotionAVLoader: ["source_audio", "skip_first_frames", "status"],
    MiniMaxH3ChainCurrent: [
        "clip_count", "shot_id", "steps", "audio_start", "audio_duration",
        "status",
    ],
    MiniMaxH3ChainLoopEnd: [
        "manifest_json", "last_context_frames", "last_context_latent",
    ],
    MiniMaxH3ChainManifestLoad: ["manifest_json", "status"],
});

const ALWAYS_ADVANCED_WIDGETS = Object.freeze({
    MiniMaxH3ChainPlanStudio: ["verify_resume_history"],
    MiniMaxH3ChainPreflight: ["verify_resume_history"],
});

export function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

export function widgetByName(node, name) {
    return node?.widgets?.find((widget) => widget.name === name) ?? null;
}

export function inputByName(node, name) {
    return node?.inputs?.find((input) => input.name === name) ?? null;
}

export function outputByName(node, name) {
    return node?.outputs?.find((output) => output.name === name) ?? null;
}

function graphLink(graph, id) {
    if (id == null) return null;
    return graph?.links?.[id] ?? graph?.links?.get?.(id) ?? null;
}

function linkedOrigin(node, input) {
    const link = graphLink(node?.graph, input?.link);
    return link ? node.graph?.getNodeById?.(link.origin_id) ?? null : null;
}

export function policyPlanConsumers(policyNode) {
    const type = nodeType(policyNode);
    const inputNames = type === AUDIO_POLICY_NODE
        ? ["audio_policy"]
        : type === TRANSITION_POLICY_NODE
            ? ["transition_policy"]
            : type === LEGACY_POLICY_NODE
                ? ["audio_policy", "transition_policy"]
                : [];
    if (!inputNames.length) return [];
    const graph = policyNode?.graph;
    return (graph?._nodes ?? []).filter((candidate) =>
        nodeType(candidate) === PLAN_NODE
        && inputNames.some((name) => linkedOrigin(
            candidate, inputByName(candidate, name),
        ) === policyNode),
    );
}

function linked(slot, output = false) {
    if (!slot) return false;
    if (!output) return slot.link != null;
    return Array.isArray(slot.links) ? slot.links.length > 0 : slot.links != null;
}

export function upstreamNodes(start) {
    const result = [];
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        result.push(node);
        for (const input of node.inputs ?? []) {
            const parent = linkedOrigin(node, input);
            if (parent) queue.push(parent);
        }
    }
    return result;
}

function audioPolicyFromWidgets(node) {
    if (nodeType(node) === LEGACY_POLICY_NODE) {
        const mode = String(widgetByName(node, "audio_mode")?.value ?? "");
        const mapped = LEGACY_AUDIO_POLICIES[mode];
        if (!mapped) return null;
        return {
            known: true,
            finalAudio: mapped[0],
            sourceReference: mapped[1],
            generatedContinuity: mapped[2],
            source: "legacy_adapter",
        };
    }
    if (nodeType(node) !== AUDIO_POLICY_NODE) return null;
    const finalAudio = widgetByName(node, "final_audio")?.value;
    const sourceReference = widgetByName(node, "source_reference")?.value;
    const generatedContinuity = widgetByName(node, "generated_continuity")?.value;
    if (finalAudio == null || sourceReference == null
            || generatedContinuity == null) return null;
    return {
        known: true,
        finalAudio: String(finalAudio),
        sourceReference: String(sourceReference),
        generatedContinuity: String(generatedContinuity),
        source: "typed",
    };
}

function legacyAudioPolicy(plan) {
    const mode = widgetByName(plan, "audio_mode")?.value;
    if (mode == null) return null;
    const mapped = LEGACY_AUDIO_POLICIES[String(mode)];
    if (!mapped) return null;
    return {
        known: true,
        finalAudio: mapped[0],
        sourceReference: mapped[1],
        generatedContinuity: mapped[2],
        source: "legacy",
    };
}

export function resolveAudioPolicy(start) {
    for (const node of upstreamNodes(start)) {
        const direct = audioPolicyFromWidgets(node);
        if (direct) return direct;
        if (nodeType(node) !== PLAN_NODE) continue;
        const policyNode = linkedOrigin(node, inputByName(node, "audio_policy"));
        const typed = audioPolicyFromWidgets(policyNode);
        if (typed) return typed;
        const legacy = legacyAudioPolicy(node);
        if (legacy) return legacy;
    }
    return {
        known: false,
        finalAudio: null,
        sourceReference: null,
        generatedContinuity: null,
        source: "unknown",
    };
}

function transitionPolicyFromWidgets(node) {
    const type = nodeType(node);
    if (type === LEGACY_POLICY_NODE) {
        const continuationMode = String(
            widgetByName(node, "continuation_mode")?.value ?? "");
        const contextLength = Number(
            widgetByName(node, "context_length")?.value);
        if (!Number.isInteger(contextLength) || !continuationMode) return null;
        const preset = Object.entries(TRANSITION_PRESETS).find(
            ([, pair]) => pair[0] === continuationMode
                && pair[1] === contextLength,
        )?.[0] ?? "custom";
        return {
            known: true, preset, continuationMode, contextLength,
            expertOverride: preset === "custom", source: "legacy_adapter",
        };
    }
    if (type !== TRANSITION_POLICY_NODE) return null;
    const preset = String(widgetByName(node, "preset")?.value ?? "");
    const pair = TRANSITION_PRESETS[preset];
    if (!pair) return null;
    const expertOverride = Boolean(
        widgetByName(node, "expert_override")?.value);
    const continuationMode = expertOverride
        ? String(widgetByName(node, "expert_continuation_mode")?.value ?? "")
        : pair[0];
    const contextLength = expertOverride
        ? Number(widgetByName(node, "expert_context_length")?.value)
        : pair[1];
    if (!continuationMode || !Number.isInteger(contextLength)) return null;
    return {
        known: true, preset, continuationMode, contextLength,
        expertOverride, source: "typed",
    };
}

function legacyTransitionPolicy(plan) {
    const continuationMode = widgetByName(plan, "continuation_mode")?.value;
    const contextLength = Number(widgetByName(plan, "context_length")?.value);
    if (continuationMode == null || !Number.isInteger(contextLength)) return null;
    const preset = Object.entries(TRANSITION_PRESETS).find(
        ([, pair]) => pair[0] === String(continuationMode)
            && pair[1] === contextLength,
    )?.[0] ?? "custom";
    return {
        known: true,
        preset,
        continuationMode: String(continuationMode),
        contextLength,
        expertOverride: preset === "custom",
        source: "legacy",
    };
}

export function resolveTransitionPolicy(start) {
    for (const node of upstreamNodes(start)) {
        const direct = transitionPolicyFromWidgets(node);
        if (direct) return direct;
        if (nodeType(node) !== PLAN_NODE) continue;
        const policyNode = linkedOrigin(
            node, inputByName(node, "transition_policy"));
        const typed = transitionPolicyFromWidgets(policyNode);
        if (typed) return typed;
        const legacy = legacyTransitionPolicy(node);
        if (legacy) return legacy;
    }
    return {
        known: false,
        preset: null,
        continuationMode: null,
        contextLength: null,
        expertOverride: false,
        source: "unknown",
    };
}

export function hasSourceTimeline(start) {
    return upstreamNodes(start).some((node) =>
        linked(inputByName(node, "source_timeline")));
}

function sourceAudioInputNeeded(node, policy) {
    const type = nodeType(node);
    if (hasSourceTimeline(node)) return false;
    if (type === CURRENT_NODE) {
        return !policy.known || policy.sourceReference === "on";
    }
    if (type === REVIEW_NODE) {
        return String(widgetByName(node, "partial_audio_source")?.value)
            === "source";
    }
    if (type === ASSEMBLE_NODE) {
        const selection = String(widgetByName(node, "audio_source")?.value ?? "plan");
        if (selection === "source") return true;
        if (selection !== "plan") return false;
        return !policy.known || policy.finalAudio === "source";
    }
    if (CONDITIONAL_SOURCE_AUDIO_NODES.has(type)) {
        return !policy.known || policy.finalAudio === "source"
            || policy.sourceReference === "on";
    }
    return true;
}

function advancedOutputNames(node) {
    const configured = ADVANCED_OUTPUTS[nodeType(node)] ?? [];
    const names = new Set(configured);
    // Status is a human diagnostic for every node in this pack. Keeping this
    // generic means new 0.5 nodes inherit the same presentation rule without
    // changing their backend result tuple.
    if (outputByName(node, "status")) names.add("status");
    return names;
}

function advancedWidgetNames(node, policy) {
    const names = new Set(ALWAYS_ADVANCED_WIDGETS[nodeType(node)] ?? []);
    if (nodeType(node) === PLAN_NODE) {
        names.add("audio_mode");
        names.add("continuation_mode");
        names.add("context_length");
    }
    if (nodeType(node) === TRANSITION_POLICY_NODE
            && !Boolean(widgetByName(node, "expert_override")?.value)) {
        names.add("expert_continuation_mode");
        names.add("expert_context_length");
    }
    if (nodeType(node) === CURRENT_NODE
            && policy.known && policy.sourceReference !== "on") {
        names.add("align_audio_reference");
    }
    return names;
}

export function presentationForNode(node, showAdvanced = false) {
    const policy = resolveAudioPolicy(node);
    const hiddenInputs = new Set();
    const hiddenOutputs = new Set();
    const hiddenWidgets = new Set();
    if (!showAdvanced) {
        for (const name of advancedOutputNames(node)) hiddenOutputs.add(name);
        for (const name of advancedWidgetNames(node, policy)) hiddenWidgets.add(name);
        const sourceAudio = inputByName(node, "source_audio");
        if (sourceAudio && !sourceAudioInputNeeded(node, policy)) {
            hiddenInputs.add("source_audio");
        }
        if (nodeType(node) === CURRENT_NODE && policy.known
                && policy.sourceReference !== "on") {
            hiddenOutputs.add("source_audio_slice");
        }
        // Converted widgets retain their backend input names. Apply the same
        // presentation decision without removing their slot from the array.
        for (const name of hiddenWidgets) {
            if (inputByName(node, name)) hiddenInputs.add(name);
        }
    }
    return {hiddenInputs, hiddenOutputs, hiddenWidgets, policy};
}

function setSlotPresentation(slot, hide, output = false) {
    if (!slot) return;
    const effective = Boolean(hide) && !linked(slot, output);
    slot.hidden = effective;
    slot.h3Advanced = Boolean(hide);
    slot.h3PresentationHidden = effective;
}

export function applySocketPresentation(node, showAdvanced = undefined) {
    const advanced = showAdvanced ?? Boolean(
        node?.properties?.h3_show_advanced_sockets);
    const presentation = presentationForNode(node, advanced);
    for (const slot of node?.inputs ?? []) {
        setSlotPresentation(
            slot, presentation.hiddenInputs.has(slot.name), false);
    }
    for (const slot of node?.outputs ?? []) {
        setSlotPresentation(
            slot, presentation.hiddenOutputs.has(slot.name), true);
    }
    return presentation;
}

export function hasAdvancedPresentation(node) {
    const compact = presentationForNode(node, false);
    return compact.hiddenInputs.size > 0 || compact.hiddenOutputs.size > 0
        || compact.hiddenWidgets.size > 0;
}
