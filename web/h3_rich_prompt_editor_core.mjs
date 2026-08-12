export const RICH_PROMPT_GUIDES = Object.freeze([
    {id: "auto", label: "Auto · H3 mode"},
    {id: "general", label: "H3 General"},
    {id: "continuity", label: "Chain continuity"},
    {id: "music_video", label: "Music video"},
    {id: "dialogue", label: "Dialogue + voice"},
    {id: "brand_promo", label: "Brand / product"},
    {id: "animation", label: "3D animation"},
    {id: "handdrawn", label: "Hand-drawn + live"},
    {id: "paper", label: "Paper / stop motion"},
]);

const GUIDE_RULES = Object.freeze({
    auto: "Choose the most appropriate H3 treatment from the prompt and connected conditioning mode.",
    general: "Prioritize concrete composition, action, camera, performance, lighting, synchronized sound, and an executable ending state.",
    continuity: "Prioritize a physically continuous opening from the previous scene and a visible unfinished handoff into the next scene. Do not add a cut unless requested.",
    music_video: "Prioritize beat-aware performance, exact lyric/dialogue timing, camera rhythm, readable performer identity, and explicit diegetic versus non-diegetic audio.",
    dialogue: "Prioritize speaker identity, vocal-reference mapping, exact <d> dialogue, language, delivery, mouth timing, ambience, and separation from soundtrack references.",
    brand_promo: "Prioritize verified product appearance, a clear visual selling point, restrained readable text, precise beat structure, and no invented brand claims.",
    animation: "Prioritize character silhouettes, readable staging, expressive poses, material/style continuity, motivated camera movement, and clean action beats.",
    handdrawn: "Prioritize physical contact between live action and drawn elements, one continuous transformation, tactile line behavior, and camera reaction lag.",
    paper: "Prioritize tactile paper materials, layered depth, handmade shadows, stop-motion cadence, practical transitions, and restrained paper sound effects.",
});

export function normalizeRichGuide(value) {
    const id = String(value ?? "auto");
    return RICH_PROMPT_GUIDES.some((item) => item.id === id) ? id : "auto";
}

export function richGenerationMode(referenceMode) {
    if (referenceMode === "scheduled" || referenceMode === "native") return "Ref2VA";
    if (referenceMode === "native_keyframes") return "I2VA/FL2VA";
    return "H3 chain scene";
}

export function richGuideInstruction(guide, generationMode) {
    const selected = normalizeRichGuide(guide);
    const mode = String(generationMode || "H3 chain scene");
    const schema = mode === "Ref2VA"
        ? "If the source already uses the Ref2VA six-section format, preserve its order: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music. Introduce that complete format only when the user explicitly asks for a full H3 rewrite. Keep every reference label or @alias stable."
        : "If the source already uses the base H3 format, preserve integrated_multimodal_description, overall_soundscape, and non_diegetic_music. Introduce the complete format or keyframe-alignment sentence only when the user explicitly asks for a full H3 rewrite; do not force headings onto a compact prompt.";
    return [
        `Return a complete replacement string for the current MiniMax H3 ${mode} scene, but change only what the request requires.`,
        schema,
        GUIDE_RULES[selected],
        "Preserve exact dialogue and lyrics inside <d> tags, their language, explicit timing, subject identity, wardrobe, camera continuity, and all valid media references unless the source explicitly asks to change them.",
        "Connected references prove only that an asset and its media type are available; their previews are not uploaded to the optimizer. Do not invent image content, motion, lyrics, voice, timbre, or an audio copy/reference role. Use only facts stated in the prompt or shared/adjacent context and otherwise preserve the reference token without elaboration.",
        "Keep all described events and cut times inside the supplied scene duration.",
        "Return a complete replacement rather than commentary, a patch, or an ellipsis.",
    ].join(" ");
}

function recordTokens(record) {
    return [record?.token, record?.label]
        .map((value) => String(value ?? "").trim())
        .filter(Boolean);
}

export function referenceRecordMap(records) {
    const map = new Map();
    for (const record of Array.isArray(records) ? records : []) {
        for (const token of recordTokens(record)) map.set(token.toLowerCase(), record);
    }
    return map;
}

const RICH_TOKEN_PATTERN = /(@[A-Za-z0-9_.-]+|<(?:Picture|Video|Audio|Subject)\s+\d+>|<\/?d>)/gi;

export function tokenizeRichPrompt(text, records = []) {
    const source = String(text ?? "");
    const recordMap = referenceRecordMap(records);
    const parts = [];
    let offset = 0;
    for (const match of source.matchAll(RICH_TOKEN_PATTERN)) {
        const index = match.index ?? 0;
        if (index > offset) parts.push({type: "text", text: source.slice(offset, index)});
        const token = match[0];
        const lower = token.toLowerCase();
        const record = recordMap.get(lower) ?? null;
        if (record || lower.startsWith("@") || /^<(?:picture|video|audio)\s/i.test(lower)) {
            const namedKind = lower.startsWith("<picture") ? "picture"
                : lower.startsWith("<video") ? "video"
                    : lower.startsWith("<audio") ? "audio" : null;
            parts.push({
                type: "reference",
                text: token,
                kind: record?.kind ?? namedKind ?? "unknown",
                record,
                unresolved: !record,
            });
        } else if (lower.startsWith("<subject")) {
            parts.push({type: "subject", text: token});
        } else {
            parts.push({type: "dialogue", text: token});
        }
        offset = index + token.length;
    }
    if (offset < source.length) parts.push({type: "text", text: source.slice(offset)});
    return parts;
}

export function optimizerSource(currentPrompt, previous = null) {
    const current = String(currentPrompt ?? "");
    if (previous && current === String(previous.result ?? "")) {
        return String(previous.source ?? current);
    }
    return current;
}
