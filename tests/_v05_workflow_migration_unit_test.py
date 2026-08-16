#!/usr/bin/env python3
"""Exercise the additive and idempotent 0.5 workflow migration."""

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "h3_migrate_v05", ROOT / "tools" / "migrate_v05_workflows.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def nodes(workflow, node_type):
    return [node for node in workflow["nodes"] if node.get("type") == node_type]


def input_names(node):
    return [item["name"] for item in node.get("inputs", [])]


def main():
    archived = load(
        "example_workflows/Archive/"
        "MiniMax H3 Ref2V - Studio Legacy Scheduled.json")
    original_identity = {
        node["id"]: node["type"] for node in archived["nodes"]}
    migrated = migration.migrate(
        copy.deepcopy(archived), "custom-v0.4-studio.json")

    for node_id, node_type in original_identity.items():
        match = next(node for node in migrated["nodes"]
                     if node["id"] == node_id)
        assert match["type"] == node_type
    assert len(nodes(migrated, "MiniMaxH3AudioPolicy")) == 1
    assert len(nodes(migrated, "MiniMaxH3TransitionPolicy")) == 1
    studio = nodes(migrated, "MiniMaxH3ChainPlanStudio")[0]
    assert {"source_timeline", "source_audio", "tagged_references",
            "reference_schedule"}.issubset(input_names(studio))

    stable = copy.deepcopy(migrated)
    migration.migrate(migrated, "custom-v0.4-studio.json")
    assert migrated == stable

    source_demo = load(
        "example_workflows/"
        "MiniMax H3 Ref2V - Studio Tagged Source Audio.json")
    stable_demo = copy.deepcopy(source_demo)
    migration.migrate(source_demo, migration.SOURCE_AUDIO_DEMO)
    assert source_demo == stable_demo
    assert len(nodes(source_demo, "MiniMaxH3SourceTimeline")) == 1
    assert len(nodes(source_demo, "MiniMaxH3AudioPolicy")) == 1
    assert len(nodes(source_demo, "MiniMaxH3TransitionPolicy")) == 1

    print("v0.5 workflow migration: additive and idempotent")


if __name__ == "__main__":
    main()
