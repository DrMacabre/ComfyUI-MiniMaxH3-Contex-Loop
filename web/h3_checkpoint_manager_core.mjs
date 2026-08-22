export function formatCheckpointBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function checkpointRevisionKey(scene, revision) {
    return `${Number(scene)}:${String(revision ?? "").toLowerCase()}`;
}

export function checkpointRevisionMap(payload) {
    return new Map((payload?.revisions ?? []).map((item) => [
        checkpointRevisionKey(item.scene, item.revision), item,
    ]));
}

export function selectedCheckpointRevision(payload, scene = null, revision = "") {
    const revisions = Array.isArray(payload?.revisions) ? payload.revisions : [];
    const wantedScene = Number(scene);
    const wantedRevision = String(revision ?? "").toLowerCase();
    if (Number.isInteger(wantedScene) && wantedRevision) {
        const exact = revisions.find((item) =>
            Number(item.scene) === wantedScene &&
            String(item.revision).toLowerCase() === wantedRevision);
        if (exact) return exact;
    }
    const sceneRevisions = Number.isInteger(wantedScene)
        ? revisions.filter((item) => Number(item.scene) === wantedScene) : [];
    const deepest = (items) => [...items].sort((left, right) =>
        Number(right.scene) - Number(left.scene) ||
        String(right.created_at).localeCompare(String(left.created_at)))[0];
    return sceneRevisions.find((item) => item.active)
        ?? sceneRevisions.sort((left, right) =>
            String(right.created_at).localeCompare(String(left.created_at)))[0]
        ?? deepest(revisions.filter((item) => item.active))
        ?? deepest(revisions)
        ?? null;
}

export function checkpointBranchRows(payload) {
    const revisions = checkpointRevisionMap(payload);
    return (payload?.branches ?? []).map((branch) => ({
        ...branch,
        revisions: (branch.path ?? []).map((item) =>
            revisions.get(checkpointRevisionKey(item.scene, item.revision)))
            .filter(Boolean),
    }));
}

export function checkpointRevisionLineage(payload, selected) {
    const records = checkpointRevisionMap(payload);
    let cursor = selected ?? null;
    const reversed = [];
    const seen = new Set();
    while (cursor) {
        const key = checkpointRevisionKey(cursor.scene, cursor.revision);
        if (seen.has(key)) return [];
        seen.add(key);
        reversed.push({
            scene: Number(cursor.scene),
            revision: String(cursor.revision ?? "").toLowerCase(),
        });
        if (!cursor.parent) break;
        cursor = records.get(checkpointRevisionKey(
            cursor.parent.scene, cursor.parent.revision,
        ));
        if (!cursor) return [];
    }
    const lineage = reversed.reverse();
    if (!lineage.length || lineage[0].scene !== 1) return [];
    if (lineage.some((item, index) => item.scene !== index + 1)) return [];
    return lineage;
}

export function checkpointSelectionJson(payload, runName, selected) {
    const normalizedRun = String(runName ?? "").trim();
    const lineage = checkpointRevisionLineage(payload, selected);
    return normalizedRun && lineage.length
        ? JSON.stringify({run_name: normalizedRun, lineage})
        : "";
}

export function checkpointDependencyText(item) {
    const scene = Number(item?.scene) || 0;
    const id = String(item?.scene_id ?? `clip_${String(scene).padStart(4, "0")}`);
    const video = Math.max(0, Number(item?.context_length) || 0);
    const audio = Math.max(0, Number(item?.audio_context_length) || 0);
    const mode = String(item?.continuation_mode ?? "guide");
    const relationship = video || audio
        ? `uses Video ${video}f / Audio ${audio}f via ${mode}`
        : `has a structural continuation edge (Video 0f / Audio 0f)`;
    return `Scene ${scene} · ${id} ${relationship}`;
}

export function checkpointDeletionTitle(preview) {
    if (!preview) return "Select a checkpoint revision to inspect deletion safety.";
    if (preview.allowed) {
        const action = preview.rollback ? "Safe active-tip rollback" : "Safe leaf deletion";
        return `${action} · ${preview.owned_file_count} files · ${formatCheckpointBytes(preview.reclaimed_bytes)}`;
    }
    return (preview.blockers ?? []).join(" ") || "Deletion is blocked.";
}
