export function normalizeRunName(value) {
    return String(value ?? "").trim();
}

export function runManagerIdentity(activeRunName, selectedRun) {
    const active = normalizeRunName(activeRunName);
    const selected = normalizeRunName(selectedRun?.run_name);
    const same = Boolean(active && selected && active === selected);
    return {
        active,
        selected,
        same,
        activeLabel: active ? `Active Plan: ${active}` : "Active Plan: not named",
        selectedLabel: selected
            ? `Selected archive: ${selected}${same ? " (active)" : " (not loaded)"}`
            : "Selected archive: none",
        loadLabel: same ? "Reload selected archive" : "Load selected archive into Plan",
        saveLabel: active ? `Save assets to active Plan “${active}”` : "Save assets to active Plan",
    };
}

export function runArchiveOptionLabel(run, activeRunName) {
    const name = normalizeRunName(run?.run_name);
    const scene = run?.scene_count == null
        ? (run?.restorable ? "" : " · assets only")
        : ` · ${run.scene_count} scenes`;
    const active = name && name === normalizeRunName(activeRunName)
        ? " · ACTIVE PLAN" : "";
    return `${name}${scene}${active}`;
}
