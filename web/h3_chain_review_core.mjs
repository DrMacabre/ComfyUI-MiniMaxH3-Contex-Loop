import {MAX_SEED, promptTextToLines} from "./h3_chain_plan_core.mjs";

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
    if (!prompt) throw new Error("The retry prompt cannot be empty.");
    const normalizedSeed = reviewSeed(seed);
    plan.shots[index].prompt = promptTextToLines(prompt);
    plan.shots[index].seed = normalizedSeed;
    return plan;
}
