import {MAX_SEED, promptTextToLines, sharedPrompt} from "./h3_chain_plan_core.mjs";

export function reviewSeed(value) {
    let seed;
    try {
        seed = BigInt(String(value));
    } catch (_error) {
        throw new Error("Seed must be an integer.");
    }
    if (seed < 0n || seed > MAX_SEED) {
        throw new Error("Seed is outside the uint64 range.");
    }
    return seed.toString();
}

export function applyReviewEdit(plan, oneBasedIndex, scenePrompt, seed) {
    const index = Number(oneBasedIndex) - 1;
    if (!Array.isArray(plan?.shots) || index < 0 || index >= plan.shots.length) {
        throw new Error("The reviewed scene does not exist in the plan.");
    }
    const prompt = String(scenePrompt ?? "").replace(/\r\n?/g, "\n").trim();
    if (!prompt && !sharedPrompt(plan).text.trim()) {
        throw new Error("Retry requires a scene prompt or shared prompt.");
    }
    const normalizedSeed = reviewSeed(seed);
    plan.shots[index].prompt = promptTextToLines(prompt);
    plan.shots[index].seed = normalizedSeed;
    return plan;
}

export function reviewCountdown(deadlineSeconds, nowMilliseconds = Date.now()) {
    if (deadlineSeconds === null || deadlineSeconds === undefined || deadlineSeconds === "") {
        return null;
    }
    const deadline = Number(deadlineSeconds);
    if (!Number.isFinite(deadline)) return null;
    const seconds = Math.max(0, Math.ceil(deadline - Number(nowMilliseconds) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = String(seconds % 60).padStart(2, "0");
    return {seconds, text: `${minutes}:${remainder}`};
}
