export const SCHEDULED_REF2VA_TYPE = "MiniMaxH3ScheduledReferenceToVideo";
export const PICTURE_REF_TYPE = "MiniMaxH3ScheduledPictureReference";
export const VIDEO_REF_TYPE = "MiniMaxH3ScheduledVideoReference";
export const AUDIO_REF_TYPE = "MiniMaxH3ScheduledAudioReference";

const SCHEDULE_TYPES = new Set([
    PICTURE_REF_TYPE,
    VIDEO_REF_TYPE,
    AUDIO_REF_TYPE,
]);

export function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function widgetValue(node, name, fallback = "") {
    return node?.widgets?.find((item) => item.name === name)?.value ?? fallback;
}

export function referenceTag(value) {
    return String(value ?? "").trim().replace(/^@+/, "");
}

function inputSource(node, name) {
    const input = node?.inputs?.find((item) => item.name === name);
    const link = input?.link == null ? null : node.graph?.links?.[input.link];
    return link ? node.graph?.getNodeById?.(link.origin_id) ?? null : null;
}

function outputTargets(node) {
    const targets = [];
    for (const output of node?.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = node.graph?.links?.[linkId];
            const target = link ? node.graph?.getNodeById?.(link.target_id) : null;
            if (target) targets.push(target);
        }
    }
    return targets;
}

export function findScheduledRef2VA(start) {
    const queue = [start];
    const seen = new Set();
    while (queue.length) {
        const node = queue.shift();
        if (!node || seen.has(node)) continue;
        seen.add(node);
        if (node !== start && nodeType(node) === SCHEDULED_REF2VA_TYPE) return node;
        queue.push(...outputTargets(node));
    }
    return null;
}

export function collectScheduleNodes(wrapper) {
    const result = [];
    const seen = new Set();
    let current = inputSource(wrapper, "reference_schedule");
    while (current && SCHEDULE_TYPES.has(nodeType(current)) && !seen.has(current)) {
        seen.add(current);
        result.unshift(current);
        current = inputSource(current, "previous");
    }
    return result;
}

export function referenceIsActive(selector, scene) {
    const text = String(selector ?? "").trim().toLowerCase();
    if (!text || text === "all" || text === "*") return true;
    const target = Number(scene);
    if (!Number.isInteger(target) || target < 1) return false;
    return text.split(",").some((piece) => {
        const match = piece.trim().match(/^(\d+)(?::(\d+))?$/);
        if (!match) return false;
        const first = Number(match[1]);
        const last = Number(match[2] ?? match[1]);
        return first <= target && target <= last;
    });
}

function baseRecord(node, kind, scene, inputName, tagName = "tag") {
    const selector = String(widgetValue(node, "scenes", ""));
    return {
        node,
        kind,
        tag: referenceTag(widgetValue(node, tagName, "")),
        selector: selector.trim() || "all",
        active: referenceIsActive(selector, scene),
        source: inputSource(node, inputName),
        label: null,
    };
}

export function scheduledReferenceRecords(editorNode, scene) {
    const wrapper = findScheduledRef2VA(editorNode);
    if (!wrapper) return {wrapper: null, records: []};
    const nodes = collectScheduleNodes(wrapper);
    const pictures = [];
    const videos = [];
    const pairedAudios = [];
    const audios = [];

    for (const node of nodes) {
        const type = nodeType(node);
        if (type === PICTURE_REF_TYPE) {
            pictures.push(baseRecord(node, "picture", scene, "image"));
        } else if (type === VIDEO_REF_TYPE) {
            const video = baseRecord(node, "video", scene, "video");
            videos.push(video);
            const audioSource = inputSource(node, "audio");
            if (audioSource) {
                const explicit = referenceTag(widgetValue(node, "audio_tag", ""));
                pairedAudios.push({
                    node,
                    kind: "audio",
                    tag: explicit || `${video.tag}_audio`,
                    selector: video.selector,
                    active: video.active,
                    source: audioSource,
                    label: null,
                    pairedWith: video,
                });
            }
        } else if (type === AUDIO_REF_TYPE) {
            audios.push(baseRecord(node, "audio", scene, "audio"));
        }
    }

    let ordinal = 0;
    for (const item of pictures) {
        if (item.active) item.label = `<Picture ${++ordinal}>`;
    }
    ordinal = 0;
    for (const item of videos) {
        if (item.active) item.label = `<Video ${++ordinal}>`;
    }
    ordinal = 0;
    // Core Ref2VA numbers paired video soundtracks before standalone audio.
    for (const item of pairedAudios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }
    for (const item of audios) {
        if (item.active) item.label = `<Audio ${++ordinal}>`;
    }

    return {
        wrapper,
        records: [...pictures, ...videos, ...pairedAudios, ...audios]
            .filter((item) => item.tag),
    };
}

