export function orderedPromptRevisions(history) {
    return [...(history?.revisions ?? [])].sort((left, right) => {
        const time = String(left.created_at ?? "").localeCompare(
            String(right.created_at ?? ""),
        );
        return time || String(left.id ?? "").localeCompare(String(right.id ?? ""));
    });
}

export function promptRevisionNavigation(history, revisionId = null) {
    const revisions = orderedPromptRevisions(history);
    const requested = String(revisionId ?? history?.active_revision ?? "");
    let index = revisions.findIndex((item) => item.id === requested);
    if (index < 0 && revisions.length) index = revisions.length - 1;
    const revision = index < 0 ? null : revisions[index];
    const parentIndex = revision?.parent_id == null
        ? -1 : revisions.findIndex((item) => item.id === revision.parent_id);
    const activeRevision = String(history?.active_revision ?? "");
    const latestExecutedRevision = String(
        history?.latest_executed_revision
        ?? [...revisions].filter((item) => item.executed_at).sort((left, right) =>
            String(left.last_executed_at ?? left.executed_at ?? "").localeCompare(
                String(right.last_executed_at ?? right.executed_at ?? ""),
            )).at(-1)?.id
        ?? "",
    );
    return {
        revisions,
        revision,
        index,
        position: index < 0 ? 0 : index + 1,
        total: revisions.length,
        previous: index > 0 ? revisions[index - 1] : null,
        next: index >= 0 && index < revisions.length - 1 ? revisions[index + 1] : null,
        parentPosition: parentIndex < 0 ? null : parentIndex + 1,
        activeRevision,
        latestExecutedRevision,
        isActive: Boolean(revision && revision.id === activeRevision),
        isExecuted: Boolean(revision?.executed_at),
        isImmutable: Boolean(revision?.executed_at),
        isLatestExecuted: Boolean(
            revision && revision.id === latestExecutedRevision),
    };
}

export function promptRevisionLabel(navigation, locale = undefined) {
    const revision = navigation?.revision;
    if (!revision) return "No saved versions";
    const timestamp = revision.executed_at ?? revision.updated_at ?? revision.created_at;
    const date = timestamp ? new Date(timestamp) : null;
    const time = date && Number.isFinite(date.getTime())
        ? date.toLocaleString(locale, {dateStyle: "medium", timeStyle: "short"})
        : "Unknown time";
    const state = navigation.isActive
        ? (navigation.isExecuted ? "Active executed" : "Active draft")
        : (navigation.isExecuted ? "Executed history" : "Draft history");
    const branch = navigation.parentPosition == null
        ? "" : ` · branched from ${navigation.parentPosition}`;
    const repeats = Number(revision.execution_count) > 1
        ? ` · executed ${revision.execution_count}×` : "";
    return `${state} · ${time}${branch}${repeats}`;
}

export function promptRevisionHelp(navigation) {
    if (!navigation?.revision) return "No prompt revision exists yet.";
    if (navigation.isActive && navigation.isImmutable) {
        return "This executed revision is active in the Plan and immutable. Typing creates a child draft.";
    }
    if (navigation.isActive) {
        return "This draft is active in the Plan. Typing updates this draft until it executes.";
    }
    return navigation.isImmutable
        ? "This is immutable executed history. Activating it replaces the current Plan prompt."
        : "This is an inactive draft. Activating it replaces the current Plan prompt.";
}
