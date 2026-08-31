#!/usr/bin/env python3
"""Rewrite a saved MASTER workflow to the independent companion node ids.

Besides namespacing package-owned node types, UI workflow graphs are routed
through one explicit ``MASTER — Core Compatibility`` boundary.  That node owns
the private MODEL/CLIP adaptations required by older ComfyUI builds and leaves
Ethan's legacy runtime untouched.

This migration tool itself does not import ComfyUI or execute node code.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


NODE_ID_PREFIX = "DrMacabreH3Master_"
CORE_COMPAT_TYPE = NODE_ID_PREFIX + "MiniMaxH3MasterCoreCompat"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _mapping_keys_from_file(path: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return set()

    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not any(name.endswith("NODE_CLASS_MAPPINGS") for name in names):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                result.add(key.value)
    return result


def discover_owned_node_ids(root: Path = PACKAGE_ROOT) -> set[str]:
    result: set[str] = set()
    for path in sorted(root.glob("*.py")):
        if path.name in {"__init__.py", "companion_namespace.py"}:
            continue
        result.update(_mapping_keys_from_file(path))
    if not result:
        raise RuntimeError("No package-owned NODE_CLASS_MAPPINGS ids were discovered.")
    return result


def migrate_value(value: Any, owned: set[str], stats: dict[str, int]) -> Any:
    if isinstance(value, list):
        return [migrate_value(item, owned, stats) for item in value]
    if not isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"type", "class_type"} and isinstance(item, str):
            if item.startswith(NODE_ID_PREFIX):
                result[key] = item
                continue
            if item in owned:
                result[key] = NODE_ID_PREFIX + item
                stats["rewritten"] += 1
                continue
        result[key] = migrate_value(item, owned, stats)
    return result


def remaining_legacy_types(value: Any, owned: set[str], found: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            remaining_legacy_types(item, owned, found)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key in {"type", "class_type"} and isinstance(item, str) and item in owned:
            found.append(item)
        else:
            remaining_legacy_types(item, owned, found)


def _contains_value(value: Any, wanted: str) -> bool:
    if isinstance(value, str):
        return value.lower() == wanted.lower()
    if isinstance(value, list):
        return any(_contains_value(item, wanted) for item in value)
    if isinstance(value, dict):
        return any(_contains_value(item, wanted) for item in value.values())
    return False


def _single_node(nodes: list[dict[str, Any]], label: str, predicate):
    matches = [node for node in nodes if predicate(node)]
    if len(matches) != 1:
        raise RuntimeError(
            "MASTER companion migration expected exactly one %s, found %d. "
            "Refusing to guess the MODEL/CLIP routing." % (label, len(matches)))
    return matches[0]


def _output_slot(node: dict[str, Any], socket_type: str) -> int:
    matches = [
        index for index, output in enumerate(node.get("outputs") or [])
        if str(output.get("type") or "") == socket_type
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Node #%s (%s) must expose exactly one %s output; found %d."
            % (node.get("id"), node.get("type"), socket_type, len(matches)))
    return matches[0]


def _next_numeric_id(values, label: str) -> int:
    ints = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError(
                "MASTER companion migration requires numeric %s ids; got %r."
                % (label, value))
        ints.append(value)
    return max(ints, default=0) + 1


def _insert_core_compat_graph(
        workflow: dict[str, Any], stats: dict[str, int]) -> dict[str, Any]:
    nodes = workflow.get("nodes")
    links = workflow.get("links")
    if not isinstance(nodes, list):
        # API-prompt dictionaries have no UI graph to rewire. They still receive
        # type namespacing, but cannot safely invent a MODEL/CLIP edge here.
        stats["core_compat_injected"] = 0
        return workflow
    if not isinstance(links, list):
        raise RuntimeError(
            "MASTER companion UI workflow has no standard top-level links list.")
    if any(str(node.get("type") or "") == CORE_COMPAT_TYPE for node in nodes):
        stats["core_compat_injected"] = 0
        return workflow

    model_source = _single_node(
        nodes,
        "core MiniMaxH3SigmaShift MODEL source",
        lambda node: str(node.get("type") or "") == "MiniMaxH3SigmaShift",
    )
    clip_source = _single_node(
        nodes,
        "MiniMax CLIPLoader",
        lambda node: (
            str(node.get("type") or "") == "CLIPLoader"
            and (
                _contains_value(node.get("widgets_values"), "minimax")
                or _contains_value(node.get("widgets_values_named"), "minimax")
                or "h3 text encoder" in str(node.get("title") or "").lower()
            )
        ),
    )

    model_slot = _output_slot(model_source, "MODEL")
    clip_slot = _output_slot(clip_source, "CLIP")
    model_output = model_source["outputs"][model_slot]
    clip_output = clip_source["outputs"][clip_slot]
    model_outgoing = list(model_output.get("links") or [])
    clip_outgoing = list(clip_output.get("links") or [])
    if not model_outgoing:
        raise RuntimeError("MiniMaxH3SigmaShift MODEL output has no consumers.")
    if not clip_outgoing:
        raise RuntimeError("MiniMax CLIPLoader output has no consumers.")

    link_by_id = {}
    for record in links:
        if not isinstance(record, list) or len(record) < 6:
            raise RuntimeError(
                "MASTER companion migration supports standard ComfyUI link "
                "records [id,origin,slot,target,slot,type]; got %r." % (record,))
        link_by_id[record[0]] = record

    for link_id in model_outgoing:
        record = link_by_id.get(link_id)
        if record is None or record[1] != model_source["id"] or record[2] != model_slot:
            raise RuntimeError(
                "MODEL output/link metadata disagree at link #%s." % link_id)
    for link_id in clip_outgoing:
        record = link_by_id.get(link_id)
        if record is None or record[1] != clip_source["id"] or record[2] != clip_slot:
            raise RuntimeError(
                "CLIP output/link metadata disagree at link #%s." % link_id)

    compat_id = _next_numeric_id(
        [node.get("id") for node in nodes], "node")
    next_link = _next_numeric_id([record[0] for record in links], "link")
    model_input_link = next_link
    clip_input_link = next_link + 1

    # Existing consumer links retain their IDs/target sockets; only their origin
    # moves to the private compatibility boundary.
    for link_id in model_outgoing:
        record = link_by_id[link_id]
        record[1] = compat_id
        record[2] = 0
    for link_id in clip_outgoing:
        record = link_by_id[link_id]
        record[1] = compat_id
        record[2] = 1

    links.append([
        model_input_link,
        model_source["id"],
        model_slot,
        compat_id,
        0,
        "MODEL",
    ])
    links.append([
        clip_input_link,
        clip_source["id"],
        clip_slot,
        compat_id,
        1,
        "CLIP",
    ])
    model_output["links"] = [model_input_link]
    clip_output["links"] = [clip_input_link]

    model_pos = model_source.get("pos") or [0, 0]
    clip_pos = clip_source.get("pos") or [0, 160]
    model_size = model_source.get("size") or [320, 100]
    clip_size = clip_source.get("size") or [320, 100]
    x = max(
        float(model_pos[0]) + float(model_size[0]),
        float(clip_pos[0]) + float(clip_size[0]),
    ) + 80.0
    y = min(float(model_pos[1]), float(clip_pos[1]))
    max_order = max(
        [int(node.get("order", 0)) for node in nodes], default=0)

    nodes.append({
        "id": compat_id,
        "type": CORE_COMPAT_TYPE,
        "pos": [x, y],
        "size": [330, 110],
        "flags": {},
        "order": max_order + 1,
        "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": model_input_link},
            {"name": "clip", "type": "CLIP", "link": clip_input_link},
        ],
        "outputs": [
            {"name": "model", "type": "MODEL", "links": model_outgoing},
            {"name": "clip", "type": "CLIP", "links": clip_outgoing},
            {"name": "status", "type": "STRING", "links": []},
        ],
        "properties": {
            "Node name for S&R": CORE_COMPAT_TYPE,
        },
        "title": "MASTER — CORE COMPATIBILITY (INTERNAL)",
    })

    workflow["last_node_id"] = max(
        int(workflow.get("last_node_id") or 0), compat_id)
    workflow["last_link_id"] = max(
        int(workflow.get("last_link_id") or 0), clip_input_link)
    stats["core_compat_injected"] = 1
    stats["core_compat_model_links"] = len(model_outgoing)
    stats["core_compat_clip_links"] = len(clip_outgoing)
    return workflow


def default_output_path(source: Path) -> Path:
    stem = source.stem
    if stem.endswith("-MASTER-COMPANION"):
        return source
    return source.with_name(stem + "-MASTER-COMPANION" + source.suffix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    source = args.workflow.resolve()
    if not source.is_file():
        raise SystemExit("Workflow not found: %s" % source)
    if args.in_place and args.output is not None:
        raise SystemExit("Use --in-place or --output, not both.")

    owned = discover_owned_node_ids()
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    stats = {
        "rewritten": 0,
        "core_compat_injected": 0,
        "core_compat_model_links": 0,
        "core_compat_clip_links": 0,
    }
    migrated = migrate_value(payload, owned, stats)
    if isinstance(migrated, dict):
        migrated = _insert_core_compat_graph(migrated, stats)

    leftovers: list[str] = []
    remaining_legacy_types(migrated, owned, leftovers)
    if leftovers:
        raise RuntimeError(
            "Migration left legacy package node types: %s" %
            ", ".join(sorted(set(leftovers))))

    if args.in_place:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = source.with_name(
            source.name + ".PRE_COMPANION_" + stamp + ".bak")
        shutil.copy2(source, backup)
        target = source
    else:
        backup = None
        target = (
            args.output.resolve() if args.output is not None
            else default_output_path(source)
        )
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print("MASTER COMPANION WORKFLOW MIGRATION: OK")
    print("source=%s" % source)
    print("output=%s" % target)
    print("owned_node_ids=%d" % len(owned))
    print("rewritten_type_fields=%d" % stats["rewritten"])
    print("core_compat_injected=%d" % stats["core_compat_injected"])
    print("core_compat_model_links=%d" % stats["core_compat_model_links"])
    print("core_compat_clip_links=%d" % stats["core_compat_clip_links"])
    if backup is not None:
        print("backup=%s" % backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
