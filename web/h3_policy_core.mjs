// Shared authoring vocabulary for compact 0.5 policy controls. Runtime Python
// remains authoritative; this module prevents the editor, Studio, socket
// presentation, and restore UI from inventing different preset mappings.

export const PRIMARY_TRANSITION_PRESETS = Object.freeze([
    "cut", "guide", "hard_av", "soft_av",
]);

export const TRANSITION_PRESETS = Object.freeze({
    cut: Object.freeze({
        continuationMode: "guide", contextLength: 0,
        label: "Visual Cut", description: "No carried picture",
    }),
    guide: Object.freeze({
        continuationMode: "guide", contextLength: 22,
        label: "Guide", description: "22-frame RGB continuation",
    }),
    tone_guide: Object.freeze({
        continuationMode: "tone_carry_guide", contextLength: 22,
        label: "Tone Guide", description: "Experimental corrected RGB guide",
    }),
    latent_guide: Object.freeze({
        continuationMode: "latent_guide", contextLength: 22,
        label: "Latent Guide", description: "Direct generated-latent guide",
    }),
    detail_guide: Object.freeze({
        continuationMode: "tapered_guide", contextLength: 22,
        label: "Detail Guide", description: "Experimental tapered chroma guide",
    }),
    detail_av: Object.freeze({
        continuationMode: "tapered_av", contextLength: 39,
        label: "Detail AV", description: "Experimental latent taper",
    }),
    drift_av: Object.freeze({
        continuationMode: "drift_control_av", contextLength: 39,
        label: "Drift-Control AV", description: "Experimental schedule-matched mask",
    }),
    hard_av: Object.freeze({
        continuationMode: "masked_av", contextLength: 39,
        label: "Hard AV", description: "Protected 39-frame AV prefix",
    }),
    soft_av: Object.freeze({
        continuationMode: "audio_feathered_av", contextLength: 39,
        label: "Soft AV", description: "Hard picture with a short audio release",
    }),
    // Read-only migration alias. Never expose this as a normal selector item.
    audio_feather_av: Object.freeze({
        continuationMode: "audio_feathered_av", contextLength: 39,
        label: "Soft AV", description: "Legacy preset alias",
    }),
});

export const LEGACY_AUDIO_POLICIES = Object.freeze({
    source_track: Object.freeze(["source", "on", "off"]),
    generated_audio: Object.freeze(["generated", "off", "on"]),
    source_plus_timeline: Object.freeze(["source", "on", "on"]),
});

export function transitionPreset(name) {
    return TRANSITION_PRESETS[String(name)] ?? null;
}

export function transitionPresetName(
    continuationMode, contextLength, {includeAlias = false} = {},
) {
    const mode = String(continuationMode ?? "");
    const context = Number(contextLength);
    for (const [name, preset] of Object.entries(TRANSITION_PRESETS)) {
        if (!includeAlias && name === "audio_feather_av") continue;
        if (preset.continuationMode === mode && preset.contextLength === context) {
            return name;
        }
    }
    return "custom";
}

export function transitionPresetLabel(name) {
    if (name === "inherit") return "Inherit Chain Policy";
    if (name === "custom") return "Custom · Legacy / Expert controls";
    return transitionPreset(name)?.label ?? String(name ?? "Unknown");
}

export function sceneTransitionPreset(
    shot, defaultContinuationMode = "guide", defaultContextLength = 22,
) {
    const hasAudioContext = Object.hasOwn(shot ?? {}, "audio_context_length")
        && shot.audio_context_length !== null
        && !(typeof shot.audio_context_length === "string"
            && !String(shot.audio_context_length).trim());
    const hasMode = Object.hasOwn(shot ?? {}, "continuation_mode")
        && shot.continuation_mode !== null
        && !(typeof shot.continuation_mode === "string"
            && !shot.continuation_mode.trim());
    const hasContext = Object.hasOwn(shot ?? {}, "context_length")
        && shot.context_length !== null
        && !(typeof shot.context_length === "string"
            && !String(shot.context_length).trim());
    if (!hasMode && !hasContext && !hasAudioContext) {
        return "inherit";
    }
    if (hasAudioContext) return "custom";
    return transitionPresetName(
        hasMode ? shot.continuation_mode : defaultContinuationMode,
        hasContext ? shot.context_length : defaultContextLength,
    );
}

export function applySceneTransitionPreset(shot, name) {
    if (!shot || typeof shot !== "object" || Array.isArray(shot)) {
        throw new Error("A scene transition requires a scene object.");
    }
    const selected = String(name);
    if (selected === "custom") return shot;
    if (selected === "inherit") {
        delete shot.continuation_mode;
        delete shot.context_length;
        delete shot.audio_context_length;
        return shot;
    }
    if (!PRIMARY_TRANSITION_PRESETS.includes(selected)) {
        throw new Error(`Unknown compact scene transition “${selected}”.`);
    }
    const preset = transitionPreset(selected);
    shot.continuation_mode = preset.continuationMode;
    shot.context_length = preset.contextLength;
    // A semantic preset opts back into automatic generated-audio context.
    delete shot.audio_context_length;
    return shot;
}

export function primaryTransitionOptions() {
    return PRIMARY_TRANSITION_PRESETS.map((name) => {
        const preset = transitionPreset(name);
        return {
            name,
            label: preset.label,
            description: preset.description,
            continuationMode: preset.continuationMode,
            contextLength: preset.contextLength,
        };
    });
}
