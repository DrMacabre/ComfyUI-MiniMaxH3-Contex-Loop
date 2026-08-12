#!/usr/bin/env python3
"""Standalone prompt-history persistence and branching checks."""

import json
import pathlib
import tempfile

from prompt_history import PromptHistoryStore


def main():
    with tempfile.TemporaryDirectory() as temporary:
        store = PromptHistoryStore(temporary)
        first = store.save_draft("project", "scene_one", "First draft.")
        first_id = first["revision"]["id"]

        edited = store.save_draft(
            "project", "scene_one", "First executed prompt.", first_id)
        assert edited["revision"]["id"] == first_id
        executed = store.mark_executed(
            "project", "scene_one", "First executed prompt.")
        assert executed["revision"]["executed_at"]
        repeated = store.mark_executed(
            "project", "scene_one", "  First executed prompt.\n")
        assert repeated["revision"]["id"] == first_id
        assert repeated["revision"]["execution_count"] == 2

        child = store.save_draft(
            "project", "scene_one", "Second version.", first_id)
        child_id = child["revision"]["id"]
        assert child_id != first_id
        assert child["revision"]["parent_id"] == first_id

        # Continue typing in the unexecuted child instead of creating a file
        # for every keystroke.
        child_edit = store.save_draft(
            "project", "scene_one", "Second version, edited.", child_id)
        assert child_edit["revision"]["id"] == child_id
        assert len(child_edit["history"]["revisions"]) == 2

        restored = store.activate("project", "scene_one", first_id)
        assert restored["revision"]["prompt"] == "First executed prompt."
        assert restored["history"]["active_revision"] == first_id
        alternate = store.save_draft(
            "project", "scene_one", "Alternate branch.", first_id)
        alternate_id = alternate["revision"]["id"]
        assert alternate_id not in (first_id, child_id)
        assert alternate["revision"]["parent_id"] == first_id
        assert len(alternate["history"]["revisions"]) == 3

        scene_dir = pathlib.Path(
            temporary, "h3_chains", "project", "prompt_history", "scene_one")
        index = json.loads((scene_dir / "index.json").read_text(encoding="utf-8"))
        assert all("prompt" not in item for item in index["revisions"])
        assert (scene_dir / f"{first_id}.json").is_file()
        assert (scene_dir / f"{child_id}.json").is_file()
        assert (scene_dir / f"{alternate_id}.json").is_file()

    print("H3 prompt history: lazy files, mutable drafts and executed branches pass")


if __name__ == "__main__":
    main()
