#!/usr/bin/env python3
"""Exercise the compact, exact, and idempotent 0.5 workflow migration."""

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
    assert len(nodes(migrated, "MiniMaxH3AudioPolicy")) == 0
    assert len(nodes(migrated, "MiniMaxH3TransitionPolicy")) == 0
    compact = nodes(migrated, "MiniMaxH3ChainPolicy")
    assert len(compact) == 1
    assert compact[0]["widgets_values"] == [
        "guide", "generated", "off", "on"]
    plan = nodes(migrated, "MiniMaxH3ChainPlan")[0]
    assert next(item for item in plan["inputs"]
                if item["name"] == "chain_policy")["link"] is not None
    studio = nodes(migrated, "MiniMaxH3ChainPlanStudio")[0]
    assert {"source_timeline", "source_audio", "tagged_references",
            "reference_schedule"}.issubset(input_names(studio))
    current = nodes(migrated, "MiniMaxH3ChainCurrent")[0]
    trim = nodes(migrated, "MiniMaxH3LoopTrim")[0]
    state_input = next(item for item in trim["inputs"]
                       if item["name"] == "state")
    state_link = next(item for item in migrated["links"]
                      if item[0] == state_input["link"])
    assert state_link[1:3] == [current["id"], 0]
    assert next(item for item in trim["inputs"]
                if item["name"] == "retain_overlap_frames")["link"] is None

    stable = copy.deepcopy(migrated)
    migration.migrate(migrated, "custom-v0.4-studio.json")
    assert migrated == stable

    source_demo = load(
        "example_workflows/"
        "MiniMax H3 Ref2V - Studio Tagged Source Audio.json")
    migration.migrate(source_demo, migration.SOURCE_AUDIO_DEMO)
    stable_demo = copy.deepcopy(source_demo)
    migration.migrate(source_demo, migration.SOURCE_AUDIO_DEMO)
    assert source_demo == stable_demo
    assert len(nodes(source_demo, "MiniMaxH3SourceTimeline")) == 1
    assert len(nodes(source_demo, "MiniMaxH3AudioPolicy")) == 0
    assert len(nodes(source_demo, "MiniMaxH3TransitionPolicy")) == 0
    compact = nodes(source_demo, "MiniMaxH3ChainPolicy")
    assert len(compact) == 1
    assert compact[0]["widgets_values"] == [
        "guide", "source", "on", "off"]

    drift_plan = {
        "pos": [100, 200],
        "widgets_values": [
            "{}", "drift", "", 960, 544, 39, "video", "head",
            "disabled", "generated_audio", 39, 15.0, 20, 0, 18, 0,
            "drift_control_av",
        ],
    }
    drift_policy, drift_output = migration._chain_policy_node(
        drift_plan, ("generated", "off", "on"),
        "drift_control_av", 39, 39)
    assert drift_policy["type"] == "MiniMaxH3Legacy04PolicyAdapter"
    assert drift_policy["widgets_values"] == [
        "generated_audio", "drift_control_av", 39, 39]
    assert drift_output == 3

    mismatched_audio, mismatch_output = migration._chain_policy_node(
        drift_plan, ("generated", "off", "on"), "masked_av", 39, 22)
    assert mismatched_audio["type"] == "MiniMaxH3Legacy04PolicyAdapter"
    assert mismatched_audio["widgets_values"] == [
        "generated_audio", "masked_av", 39, 22]
    assert mismatch_output == 3

    print("v0.5 workflow migration: compact, exact, and idempotent")


if __name__ == "__main__":
    main()
