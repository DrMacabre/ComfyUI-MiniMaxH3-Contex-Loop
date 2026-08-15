export const SCHEDULED_REF2VA_TYPE = "MiniMaxH3ScheduledReferenceToVideo";
export const VIDEO_REF_TYPE = "MiniMaxH3ScheduledVideoReference";

export function nodeType(node) {
    return node?.comfyClass ?? node?.type ?? null;
}

function widget(node, name) {
    return node?.widgets?.find((item) => item.name === name) ?? null;
}

function setWidget(node, name, value) {
    const target = widget(node, name);
    if (!target) return false;
    target.value = value;
    target.callback?.(target.value);
    return true;
}

export function migrateLegacyVideoScheduleWidgets(node, info) {
    const values = info?.widgets_values;
    if (nodeType(node) !== VIDEO_REF_TYPE || !Array.isArray(values)
            || values.length < 5) return false;
    // v0.3.10 stored [tag, scenes, declaration, audio_tag,
    // audio_declaration]. The current scheduler stores
    // [tag, scenes, audio_tag, timeline_mode], so only the five-value legacy
    // shape may be migrated here.
    const audioMigrated = setWidget(node, "audio_tag", values[3] ?? "");
    const timelineReset = setWidget(
        node, "timeline_mode", "restart_each_scene");
    return audioMigrated || timelineReset;
}

export function migrateReferenceComplianceWidget(node) {
    if (nodeType(node) !== SCHEDULED_REF2VA_TYPE) return false;
    const target = widget(node, "prompt_compliance");
    if (!target || typeof target.value !== "boolean") return false;
    target.value = target.value ? "strict" : "soft";
    target.callback?.(target.value);
    return true;
}
