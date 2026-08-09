// Pure data helpers for the H3 Chain Plan editor. Keep this module free of
// ComfyUI/browser dependencies so its timing and serialization can be tested.

export const FPS = 24;
export const MAX_SHOTS = 128;
export const MAX_H3_FRAMES = 3592;
export const MAX_SEED = 18446744073709551615n;

function clone(value) {
    return JSON.parse(JSON.stringify(value));
}

function protectSeedIntegers(source) {
    // JSON.parse rounds integers above 2^53. The Python node accepts seed
    // strings, so quote numeric `seed` values before parsing and preserve all
    // uint64 digits exactly. This scanner only touches actual JSON object keys,
    // never text that happens to contain `\"seed\": 123` inside a prompt.
    let output = "";
    let index = 0;
    while (index < source.length) {
        if (source[index] !== '"') {
            output += source[index++];
            continue;
        }

        const start = index;
        index += 1;
        while (index < source.length) {
            if (source[index] === "\\") {
                index += 2;
                continue;
            }
            if (source[index] === '"') {
                index += 1;
                break;
            }
            index += 1;
        }
        const token = source.slice(start, index);
        output += token;

        let key;
        try {
            key = JSON.parse(token);
        } catch (_error) {
            continue;
        }
        if (key !== "seed") {
            continue;
        }

        let cursor = index;
        while (/\s/.test(source[cursor] || "")) cursor += 1;
        if (source[cursor] !== ":") continue;
        cursor += 1;
        while (/\s/.test(source[cursor] || "")) cursor += 1;
        const match = source.slice(cursor).match(/^-?\d+(?=\s*[,}])/);
        if (!match) continue;

        output += source.slice(index, cursor);
        output += JSON.stringify(match[0]);
        index = cursor + match[0].length;
    }
    return output;
}

export function promptValueToText(value, label = "prompt") {
    if (Array.isArray(value)) {
        if (!value.every((line) => typeof line === "string")) {
            throw new Error(`${label} line arrays may contain only strings.`);
        }
        return value.join("\n");
    }
    if (value === undefined || value === null) return "";
    return String(value);
}

export function promptTextToLines(value) {
    return String(value ?? "").replace(/\r\n?/g, "\n").split("\n");
}

export function parsePlanJson(source) {
    let raw;
    try {
        raw = JSON.parse(protectSeedIntegers(String(source ?? "")));
    } catch (error) {
        throw new Error(`Invalid plan JSON: ${error.message}`);
    }
    if (Array.isArray(raw)) raw = {shots: raw};
    if (!raw || typeof raw !== "object") {
        throw new Error("The plan must be an object or a bare list of scenes.");
    }
    if (!Array.isArray(raw.shots) || raw.shots.length === 0) {
        throw new Error("The plan needs at least one scene in shots.");
    }
    if (raw.shots.length > MAX_SHOTS) {
        throw new Error(`The plan supports at most ${MAX_SHOTS} scenes.`);
    }

    const plan = clone(raw);
    plan.shots = plan.shots.map((shot, offset) => {
        if (typeof shot === "string") {
            return {prompt: promptTextToLines(shot)};
        }
        if (!shot || typeof shot !== "object" || Array.isArray(shot)) {
            throw new Error(`Scene ${offset + 1} must be an object or prompt string.`);
        }
        const normalized = {...shot};
        normalized.prompt = promptTextToLines(
            promptValueToText(shot.prompt, `Scene ${offset + 1} prompt`),
        );
        return normalized;
    });

    if (Object.hasOwn(plan, "prompt_prefix")) {
        plan.prompt_prefix = promptTextToLines(
            promptValueToText(plan.prompt_prefix, "prompt_prefix"),
        );
    } else if (Object.hasOwn(plan, "global_prompt")) {
        plan.global_prompt = promptTextToLines(
            promptValueToText(plan.global_prompt, "global_prompt"),
        );
    }
    return plan;
}

export function planToJson(plan) {
    return JSON.stringify(plan, null, 2);
}

export function sharedPrompt(plan) {
    const key = Object.hasOwn(plan, "prompt_prefix")
        ? "prompt_prefix"
        : Object.hasOwn(plan, "global_prompt") ? "global_prompt" : "prompt_prefix";
    return {key, text: promptValueToText(plan[key] ?? "", key)};
}

export function setSharedPrompt(plan, text) {
    const current = sharedPrompt(plan);
    plan[current.key] = promptTextToLines(text);
}

export function safeShotId(value, fallback) {
    let text = String(value ?? "").trim().replace(/[^A-Za-z0-9._-]+/g, "_");
    text = text.replace(/^[._-]+|[._-]+$/g, "");
    return (text || fallback).slice(0, 96);
}

export function uniqueShotId(shots, requested = "scene") {
    const used = new Set(shots.map((shot, offset) => safeShotId(
        shot?.id,
        `clip_${String(offset + 1).padStart(4, "0")}`,
    )));
    const base = safeShotId(requested, "scene");
    if (!used.has(base)) return base;
    for (let suffix = 2; suffix <= MAX_SHOTS + 1; suffix += 1) {
        const candidate = `${base}_${suffix}`.slice(0, 96);
        if (!used.has(candidate)) return candidate;
    }
    return `${base}_${Date.now()}`.slice(0, 96);
}

export function makeShot(shots = []) {
    const ordinal = shots.length + 1;
    return {
        id: uniqueShotId(shots, `scene_${String(ordinal).padStart(2, "0")}`),
        prompt: ["Describe this scene."],
    };
}

export function duplicateShot(shots, index) {
    const duplicated = clone(shots[index]);
    duplicated.id = uniqueShotId(shots, `${safeShotId(
        duplicated.id,
        `scene_${String(index + 1).padStart(2, "0")}`,
    )}_copy`);
    shots.splice(index + 1, 0, duplicated);
    return duplicated;
}

export function moveShot(shots, from, to) {
    if (from === to || from < 0 || from >= shots.length || to < 0 || to >= shots.length) {
        return;
    }
    const [shot] = shots.splice(from, 1);
    shots.splice(to, 0, shot);
}

export function h3FrameLength(seconds) {
    const numeric = Number(seconds);
    if (!Number.isFinite(numeric) || numeric <= 0) {
        throw new Error("Duration must be a finite positive number.");
    }
    const requested = Math.max(5, Math.ceil(numeric * FPS - 1e-9));
    const length = requested + ((5 - (requested % 17)) % 17);
    if (length > MAX_H3_FRAMES) {
        throw new Error(
            `Duration rounds to ${length} frames; H3's largest valid length is ${MAX_H3_FRAMES}.`,
        );
    }
    return length;
}

export function validateH3Length(value) {
    const length = Number(value);
    if (!Number.isInteger(length) || length < 5 || length > MAX_H3_FRAMES || length % 17 !== 5) {
        throw new Error(
            `Exact length must be 5..${MAX_H3_FRAMES} frames with length % 17 == 5.`,
        );
    }
    return length;
}

function sceneRawFrames(shot, defaultDuration) {
    if (shot.length !== undefined && shot.length !== null && shot.length !== "") {
        return validateH3Length(shot.length);
    }
    if (shot.frames !== undefined && shot.frames !== null && shot.frames !== "") {
        return validateH3Length(shot.frames);
    }
    const duration = shot.duration_seconds ?? defaultDuration;
    return h3FrameLength(duration);
}

function validateSeed(seed) {
    if (seed === undefined || seed === null || seed === "") return;
    let numeric;
    try {
        numeric = BigInt(String(seed));
    } catch (_error) {
        throw new Error("Seed must be an unsigned 64-bit integer.");
    }
    if (numeric < 0n || numeric > MAX_SEED) {
        throw new Error("Seed is outside the unsigned 64-bit range.");
    }
}

export function calculatePlanTiming(plan, settings = {}) {
    const errors = [];
    const rows = [];
    const contextLength = Number(settings.contextLength ?? 22);
    const anchorMode = settings.anchorMode ?? "head";
    const nodeDefaultDuration = Number(settings.defaultDurationSeconds ?? 15);
    const planDefaultDuration = Number(plan?.defaults?.duration_seconds ?? nodeDefaultDuration);
    const defaultSteps = Number(plan?.defaults?.steps ?? settings.defaultSteps ?? 20);

    if (![1, 5, 22, 39].includes(contextLength)) {
        errors.push("Context length must be 1, 5, 22, or 39.");
    }
    if (!Number.isFinite(planDefaultDuration) || planDefaultDuration <= 0) {
        errors.push("Default duration must be a finite positive number.");
    }
    if (!Number.isInteger(defaultSteps) || defaultSteps < 1 || defaultSteps > 10000) {
        errors.push("Default steps must be between 1 and 10000.");
    }

    const ids = new Set();
    let stitchedFrames = 0;
    for (let offset = 0; offset < (plan?.shots?.length ?? 0); offset += 1) {
        const shot = plan.shots[offset];
        const index = offset + 1;
        const fallback = `clip_${String(index).padStart(4, "0")}`;
        const id = safeShotId(shot.id, fallback);
        const rowErrors = [];
        if (ids.has(id)) rowErrors.push(`Duplicate normalized scene id “${id}”.`);
        ids.add(id);
        if (!promptValueToText(shot.prompt, `Scene ${index} prompt`).trim()) {
            rowErrors.push("Prompt is empty.");
        }

        const steps = Number(shot.steps ?? defaultSteps);
        if (!Number.isInteger(steps) || steps < 1 || steps > 10000) {
            rowErrors.push("Steps must be between 1 and 10000.");
        }
        try {
            validateSeed(shot.seed);
        } catch (error) {
            rowErrors.push(error.message);
        }

        let rawFrames = 0;
        try {
            rawFrames = sceneRawFrames(shot, planDefaultDuration);
        } catch (error) {
            rowErrors.push(error.message);
        }

        let deliveredFrames = rawFrames;
        let generationStartFrame = stitchedFrames;
        if (index > 1 && anchorMode === "head") {
            if (rawFrames <= contextLength) {
                rowErrors.push(
                    `${rawFrames} raw frames are not longer than the ${contextLength}-frame overlap.`,
                );
            }
            deliveredFrames = Math.max(0, rawFrames - contextLength);
            generationStartFrame = stitchedFrames - contextLength;
        }

        rows.push({
            index,
            id,
            rawFrames,
            rawSeconds: rawFrames / FPS,
            deliveredFrames,
            deliveredSeconds: deliveredFrames / FPS,
            generationStartFrame,
            errors: rowErrors,
        });
        stitchedFrames += deliveredFrames;
    }

    for (let offset = 0; offset < rows.length - 1; offset += 1) {
        if (rows[offset].deliveredFrames < contextLength) {
            rows[offset].errors.push(
                `Delivers fewer than ${contextLength} frames needed by the next scene.`,
            );
        }
    }
    for (const row of rows) {
        for (const error of row.errors) errors.push(`Scene ${row.index}: ${error}`);
    }

    return {
        shots: rows,
        totalFrames: stitchedFrames,
        totalSeconds: stitchedFrames / FPS,
        errors,
    };
}

export function formatClock(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "—";
    const wholeMinutes = Math.floor(seconds / 60);
    const remainder = seconds - wholeMinutes * 60;
    return wholeMinutes
        ? `${wholeMinutes}:${remainder.toFixed(3).padStart(6, "0")}`
        : `${remainder.toFixed(3)}s`;
}

