#!/usr/bin/env python3
"""Patch an already migrated H3 MASTER workflow after runtime smoke 02.

This patch is intentionally metadata-only. It does not rebuild graph links.
It promotes the detached Run Manager asset records to persistent templates and
keeps asset_bindings_json limited to media that is actually selected. This
prevents blank master placeholders from being treated as missing source files.

The exact-timeline generated-audio safety fix lives in master_policy_router.py
and therefore needs only a plugin update, not a workflow graph rewrite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class PatchError(RuntimeError):
    pass


def _node_map(workflow: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(node["id"]): node for node in workflow.get("nodes", [])}


def _widget_value(node: dict[str, Any], name: str, default: Any = None) -> Any:
    named = node.get("widgets_values_named")
    if isinstance(named, dict) and name in named:
        return named[name]
    widget_names = [
        item.get("widget", {}).get("name")
        for item in node.get("inputs", [])
        if isinstance(item.get("widget"), dict)
    ]
    try:
        index = widget_names.index(name)
    except ValueError:
        index = -1
    values = node.get("widgets_values") or []
    if index >= 0 and index < len(values):
        return values[index]
    # Core loader nodes generally serialize their media selector as the first
    # widget and do not expose it as a graph input.
    if name in ("image", "audio", "file", "video", "path", "filename"):
        for value in values:
            if isinstance(value, str):
                return value
    return default


def _set_widget_value(node: dict[str, Any], name: str, value: Any) -> None:
    named = node.setdefault("widgets_values_named", {})
    named[name] = value
    widget_names = [
        item.get("widget", {}).get("name")
        for item in node.get("inputs", [])
        if isinstance(item.get("widget"), dict)
    ]
    if name in widget_names:
        index = widget_names.index(name)
        values = list(node.get("widgets_values") or [])
        while len(values) <= index:
            values.append(None)
        values[index] = value
        node["widgets_values"] = values


def _parse_bindings(manager: dict[str, Any]) -> list[dict[str, Any]]:
    props = manager.setdefault("properties", {})
    templates = props.get("h3_detached_asset_templates")
    if isinstance(templates, list) and templates:
        return [dict(item) for item in templates if isinstance(item, dict)]
    raw = _widget_value(manager, "asset_bindings_json", "[]")
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError as exc:
        raise PatchError(
            "Run Manager %s has invalid asset_bindings_json" % manager.get("id")) from exc
    if not isinstance(parsed, list):
        raise PatchError(
            "Run Manager %s asset_bindings_json is not a list" % manager.get("id"))
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _refresh_template(binding: dict[str, Any], nodes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    result = dict(binding)
    try:
        node = nodes.get(int(str(binding.get("node_id") or "0")))
    except ValueError:
        node = None
    if node is None:
        return result
    title = str(node.get("title") or node.get("type") or result.get("label") or "Asset")
    widget_name = str(result.get("widget_name") or "")
    value = _widget_value(node, widget_name, result.get("original_value", ""))
    result.update({
        "label": title,
        "node_id": str(node.get("id")),
        "node_type": str(node.get("type") or result.get("node_type") or ""),
        "node_title": title,
        "original_value": str(value or ""),
    })
    node.setdefault("properties", {}).setdefault("h3_asset_binding_ids", {})[
        str(int(result.get("output_slot", 0) or 0))] = str(result.get("binding_id") or "")
    return result


def patch(workflow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = _node_map(workflow)
    managers = [
        node for node in workflow.get("nodes", [])
        if node.get("type") == "MiniMaxH3ChainRunManager"
    ]
    if not managers:
        raise PatchError("No MiniMaxH3ChainRunManager found")

    template_count = 0
    active_count = 0
    inactive_count = 0
    for manager in managers:
        templates = [_refresh_template(item, nodes) for item in _parse_bindings(manager)]
        if not templates:
            raise PatchError(
                "Run Manager %s has no detached asset templates" % manager.get("id"))
        active = [
            item for item in templates
            if str(item.get("original_value") or "").strip()
        ]
        props = manager.setdefault("properties", {})
        props["h3_persist_detached_asset_bindings"] = True
        props["h3_detached_asset_templates"] = templates
        _set_widget_value(
            manager, "asset_bindings_json",
            json.dumps(active, ensure_ascii=False, separators=(",", ":")))
        template_count += len(templates)
        active_count += len(active)
        inactive_count += len(templates) - len(active)

    report = {
        "status": "RUNTIME SMOKE 02 PATCHED / RETEST REQUIRED",
        "detached_asset_templates": template_count,
        "active_asset_bindings": active_count,
        "inactive_blank_assets_omitted": inactive_count,
        "master_generated_audio_latent_carry": "off",
        "exact_final_timeline_guard": "unchanged / fail-closed",
        "runtime": "INCONCLUSIVE UNTIL RETEST",
    }
    return workflow, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", help="Existing Default H3 - MASTER.json")
    parser.add_argument("--output", help="Optional output path; defaults to in-place")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args(argv)

    source = Path(args.workflow)
    if not source.is_file():
        raise SystemExit("MASTER workflow not found: %s" % source)
    output = Path(args.output) if args.output else source
    with source.open("r", encoding="utf-8-sig") as handle:
        workflow = json.load(handle)
    patched, report = patch(workflow)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(patched, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
