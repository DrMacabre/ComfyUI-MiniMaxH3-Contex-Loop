#!/usr/bin/env python3
"""Rewrite a saved MASTER workflow to the independent companion node ids.

This tool does not import ComfyUI or execute node code.  It discovers the node
ids owned by this source tree by parsing the literal ``*_NODE_CLASS_MAPPINGS``
dictionaries in the package's Python modules, then rewrites only workflow
``type`` / ``class_type`` fields that exactly match those owned ids.
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
    stats = {"rewritten": 0}
    migrated = migrate_value(payload, owned, stats)

    leftovers: list[str] = []
    remaining_legacy_types(migrated, owned, leftovers)
    if leftovers:
        raise RuntimeError(
            "Migration left legacy package node types: %s" %
            ", ".join(sorted(set(leftovers))))

    if args.in_place:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = source.with_name(source.name + ".PRE_COMPANION_" + stamp + ".bak")
        shutil.copy2(source, backup)
        target = source
    else:
        backup = None
        target = (args.output.resolve() if args.output is not None
                  else default_output_path(source))
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    print("MASTER COMPANION WORKFLOW MIGRATION: OK")
    print("source=%s" % source)
    print("output=%s" % target)
    print("owned_node_ids=%d" % len(owned))
    print("rewritten_type_fields=%d" % stats["rewritten"])
    if backup is not None:
        print("backup=%s" % backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
