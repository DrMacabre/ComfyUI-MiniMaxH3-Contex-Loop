export function studioCheckpointSignature(runName, records) {
    return JSON.stringify({
        run_name: String(runName ?? ""),
        checkpoints: (Array.isArray(records) ? records : []).map((item) => ({
            scene: item?.scene,
            scene_id: item?.scene_id,
            ready: item?.ready,
            delivered_frames: item?.delivered_frames,
            video: item?.video,
            preview_video: item?.preview_video,
            partial_video: item?.partial_video,
        })),
    });
}

export function matchingStudioCheckpoint(checkpoints, index, timingRow) {
    const scene = Number(index) + 1;
    const item = checkpoints instanceof Map
        ? checkpoints.get(scene)
        : (Array.isArray(checkpoints)
            ? checkpoints.find((candidate) => Number(candidate?.scene) === scene)
            : null);
    if (!item?.ready || !timingRow) return null;
    if (String(item.scene_id ?? "") !== String(timingRow.id ?? "")) return null;
    const savedFrames = Number(item.delivered_frames);
    const plannedFrames = Number(timingRow.deliveredFrames);
    if (Number.isFinite(savedFrames) && savedFrames > 0
            && Number.isFinite(plannedFrames) && savedFrames !== plannedFrames) {
        return null;
    }
    return item;
}

export function studioSceneStartSeconds(rows, index) {
    const bounded = Math.max(0, Math.min(
        Array.isArray(rows) ? rows.length : 0,
        Number.isFinite(Number(index)) ? Math.trunc(Number(index)) : 0,
    ));
    let seconds = 0;
    for (let offset = 0; offset < bounded; offset += 1) {
        seconds += Math.max(0, Number(rows[offset]?.deliveredSeconds) || 0);
    }
    return seconds;
}

export function locateStudioTimelineSecond(rows, seconds) {
    const scenes = Array.isArray(rows) ? rows : [];
    const totalSeconds = studioSceneStartSeconds(scenes, scenes.length);
    const targetSeconds = Math.max(0, Math.min(
        totalSeconds, Number.isFinite(Number(seconds)) ? Number(seconds) : 0,
    ));
    if (!scenes.length) {
        return {index: -1, startSeconds: 0, localSeconds: 0, targetSeconds, totalSeconds};
    }
    let startSeconds = 0;
    for (let index = 0; index < scenes.length; index += 1) {
        const duration = Math.max(0, Number(scenes[index]?.deliveredSeconds) || 0);
        if (targetSeconds < startSeconds + duration || index === scenes.length - 1) {
            return {
                index,
                startSeconds,
                localSeconds: Math.max(0, targetSeconds - startSeconds),
                targetSeconds,
                totalSeconds,
            };
        }
        startSeconds += duration;
    }
    return {index: scenes.length - 1, startSeconds, localSeconds: 0, targetSeconds, totalSeconds};
}
