export function studioCheckpointSignature(runName, records) {
    return JSON.stringify({
        run_name: String(runName ?? ""),
        checkpoints: (Array.isArray(records) ? records : []).map((item) => ({
            scene: item?.scene,
            scene_id: item?.scene_id,
            ready: item?.ready,
            delivered_frames: item?.delivered_frames,
            video: item?.video,
            audio: item?.audio,
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

export function matchingStudioSourceScene(payload, index, timingRow) {
    if (!payload?.token || !timingRow) return null;
    const scene = Number(index) + 1;
    const item = (Array.isArray(payload.scenes) ? payload.scenes : []).find(
        (candidate) => Number(candidate?.scene) === scene,
    );
    if (!item || String(item.scene_id ?? "") !== String(timingRow.id ?? "")) {
        return null;
    }
    if (Number(item.delivered_frames) !== Number(timingRow.deliveredFrames)) {
        return null;
    }
    const references = Array.isArray(item.references) ? item.references : [];
    return references.length ? item : null;
}

export function matchingStudioSourceAudio(payload, timingRows) {
    const audio = payload?.source_audio;
    if (!payload?.token || !audio?.available) return null;
    const rows = Array.isArray(timingRows) ? timingRows : [];
    const plannedFrames = rows.reduce(
        (total, row) => total + Math.max(0, Number(row?.deliveredFrames) || 0),
        0,
    );
    if (Number(audio.frame_count) !== plannedFrames) return null;
    return audio;
}

export function studioSourceAudioSecond(sourceAudio, timelineSeconds) {
    const start = Math.max(0, Number(sourceAudio?.seek_seconds) || 0);
    const duration = Math.max(0, Number(sourceAudio?.duration_seconds) || 0);
    const local = Math.max(0, Number(timelineSeconds) || 0);
    return start + Math.min(Math.max(0, duration - 0.02), local);
}

export function studioWaveformSceneSamples(waveform, rows, index) {
    const scenes = Array.isArray(rows) ? rows : [];
    const samples = Array.isArray(waveform?.samples) ? waveform.samples : [];
    const rate = Math.max(1, Number(waveform?.points_per_second) || 1);
    if (!samples.length || index < 0 || index >= scenes.length) return [];
    const start = studioSceneStartSeconds(scenes, index);
    const end = start + Math.max(
        0, Number(scenes[index]?.deliveredSeconds) || 0);
    return samples.slice(
        Math.max(0, Math.floor(start * rate)),
        Math.min(samples.length, Math.max(1, Math.ceil(end * rate))),
    );
}

export function studioSourceSecond(reference, deliveredLocalSeconds, fps = 24) {
    const rate = Math.max(1, Number(fps) || 24);
    const offset = Math.max(0, Number(reference?.compare_offset_frames) || 0) / rate;
    const local = Math.max(0, Number(deliveredLocalSeconds) || 0);
    const duration = Math.max(0, Number(reference?.frame_count) || 0) / rate;
    return Math.min(Math.max(0, duration - 0.02), offset + local);
}

export function h3StudioGridMarkers(
    rawFrames, contextFrames = 0, continuationMode = "guide",
) {
    const frames = Math.trunc(Number(rawFrames));
    const context = Math.trunc(Number(contextFrames));
    const rawIndex = Number.isInteger(frames) ? (frames - 5) / 17 : NaN;
    const rawOnGrid = Number.isInteger(rawIndex) && rawIndex >= 0;
    const raw = {
        frames,
        onGrid:rawOnGrid,
        index:rawOnGrid ? rawIndex : null,
        label:rawOnGrid
            ? `${frames}f = 17×${rawIndex}+5`
            : `${frames}f is off the 17n+5 grid`,
    };

    const avMode = [
        "masked_av", "tapered_av", "feathered_av", "audio_feathered_av",
        "drift_control_av",
    ].includes(
        String(continuationMode ?? ""),
    );
    let av = null;
    if (avMode && Number.isInteger(context) && context > 0) {
        const latentIndex = (context - 5) / 17;
        const latentGrid = Number.isInteger(latentIndex) && latentIndex >= 0;
        const exact = latentGrid && context % 3 === 0;
        const audioTicks = context * 5 / 3;
        av = {
            frames:context,
            latentGrid,
            exact,
            audioTicks,
            label:exact
                ? `${context}f AV = ${audioTicks} audio ticks`
                : `${context}f AV = ${audioTicks.toFixed(3)} audio ticks`,
        };
    }

    // Community experiments report fewer flashes when a generated-to-real
    // cut lands within the four-frame window beginning at 17n-3.  Surface the
    // nearest completed window as an optional diagnostic, never a validator.
    const packet = Number.isInteger(frames) ? Math.floor(frames / 17) : 0;
    const cut = packet > 0 ? {
        start:17 * packet - 3,
        end:17 * packet,
        experimental:true,
        label:`cut test ${17 * packet - 3}–${17 * packet}f`,
    } : null;
    return {raw, av, cut};
}
