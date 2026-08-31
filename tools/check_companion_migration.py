#!/usr/bin/env python3
"""Regression checks for MASTER companion workflow migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "migrate_workflow_to_companion.py"
spec = importlib.util.spec_from_file_location("companion_migration_test", PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

workflow = {
    "last_node_id": 20,
    "last_link_id": 13,
    "nodes": [
        {
            "id": 1,
            "type": "MiniMaxH3SigmaShift",
            "pos": [0, 0],
            "size": [300, 80],
            "order": 0,
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [10, 11]}],
        },
        {
            "id": 2,
            "type": "CLIPLoader",
            "title": "H3 TEXT ENCODER",
            "pos": [0, 120],
            "size": [300, 100],
            "order": 1,
            "widgets_values": ["qwen.safetensors", "minimax", "default"],
            "outputs": [{"name": "CLIP", "type": "CLIP", "links": [12, 13]}],
        },
        {
            "id": 10,
            "type": "SomeSampler",
            "order": 2,
            "inputs": [{"name": "model", "type": "MODEL", "link": 10}],
            "outputs": [],
        },
        {
            "id": 11,
            "type": "AnotherModelConsumer",
            "order": 3,
            "inputs": [{"name": "model", "type": "MODEL", "link": 11}],
            "outputs": [],
        },
        {
            "id": 12,
            "type": "MiniMaxH3ChainPlan",
            "order": 4,
            "inputs": [{"name": "clip", "type": "CLIP", "link": 12}],
            "outputs": [],
        },
        {
            "id": 13,
            "type": "OtherClipConsumer",
            "order": 5,
            "inputs": [{"name": "clip", "type": "CLIP", "link": 13}],
            "outputs": [],
        },
    ],
    "links": [
        [10, 1, 0, 10, 0, "MODEL"],
        [11, 1, 0, 11, 0, "MODEL"],
        [12, 2, 0, 12, 0, "CLIP"],
        [13, 2, 0, 13, 0, "CLIP"],
    ],
}

owned = module.discover_owned_node_ids(ROOT)
stats = {
    "rewritten": 0,
    "core_compat_injected": 0,
    "core_compat_model_links": 0,
    "core_compat_clip_links": 0,
}
migrated = module.migrate_value(workflow, owned, stats)
migrated = module._insert_core_compat_graph(migrated, stats)

assert stats["core_compat_injected"] == 1
assert stats["core_compat_model_links"] == 2
assert stats["core_compat_clip_links"] == 2
assert stats["rewritten"] >= 1

compat = next(
    node for node in migrated["nodes"]
    if node["type"] == module.CORE_COMPAT_TYPE)
compat_id = compat["id"]
assert compat_id == 21
assert compat["inputs"][0]["link"] == 14
assert compat["inputs"][1]["link"] == 15
assert compat["outputs"][0]["links"] == [10, 11]
assert compat["outputs"][1]["links"] == [12, 13]

links = {record[0]: record for record in migrated["links"]}
assert links[10][1:3] == [compat_id, 0]
assert links[11][1:3] == [compat_id, 0]
assert links[12][1:3] == [compat_id, 1]
assert links[13][1:3] == [compat_id, 1]
assert links[14] == [14, 1, 0, compat_id, 0, "MODEL"]
assert links[15] == [15, 2, 0, compat_id, 1, "CLIP"]

model_source = next(node for node in migrated["nodes"] if node["id"] == 1)
clip_source = next(node for node in migrated["nodes"] if node["id"] == 2)
assert model_source["outputs"][0]["links"] == [14]
assert clip_source["outputs"][0]["links"] == [15]
assert migrated["last_node_id"] == 21
assert migrated["last_link_id"] == 15

# Idempotence: a second migration must not inject another boundary.
stats2 = {
    "rewritten": 0,
    "core_compat_injected": 0,
    "core_compat_model_links": 0,
    "core_compat_clip_links": 0,
}
again = module._insert_core_compat_graph(migrated, stats2)
assert again is migrated
assert stats2["core_compat_injected"] == 0
assert sum(1 for node in migrated["nodes"]
           if node["type"] == module.CORE_COMPAT_TYPE) == 1

print("MASTER COMPANION WORKFLOW MIGRATION CHECKS: OK")
