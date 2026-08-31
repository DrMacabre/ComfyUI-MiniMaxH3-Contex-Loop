#!/usr/bin/env python3
"""Patch an already migrated H3 MASTER workflow after runtime smoke 01.

This is intentionally surgical: it does not rebuild the workflow. It only:
1. removes Run Manager asset_* execution links while preserving loader bindings
   through asset_bindings_json + a frontend persistence property;
2. converts recovery-only master exports to the inactive-safe recovery node.

The normal FINAL MASTER EXPORT remains strict and still requires a manifest.
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


def _input_index(node: dict[str, Any], name: str) -> int:
    for index, item in enumerate(node.get("inputs", [])):
        if item.get("name") == name:
            return index
    raise PatchError("%s(%s) has no input %r" % (
        node.get("type"), node.get("id"), name))


def _remove_link(workflow: dict[str, Any], link_id: int) -> None:
    links = workflow.get("links", [])
    record = next((item for item in links if int(item[0]) == int(link_id)), None)
    if record is None:
        return
    _, origin_id, origin_slot, target_id, target_slot, _typ = record[:6]
    nodes = _node_map(workflow)
    origin = nodes.get(int(origin_id))
    target = nodes.get(int(target_id))
    if origin is not None and int(origin_slot) < len(origin.get("outputs", [])):
        output = origin["outputs"][int(origin_slot)]
        output["links"] = [
            value for value in (output.get("links") or [])
            if int(value) != int(link_id)
        ] or None
    if target is not None and int(target_slot) < len(target.get("inputs", [])):
        if target["inputs"][int(target_slot)].get("link") == int(link_id):
            target["inputs"][int(target_slot)]["link"] = None
    links.remove(record)


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
        return default
    values = node.get("widgets_values") or []
    return values[index] if index < len(values) else default


def _asset_bindings(manager: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _widget_value(manager, "asset_bindings_json", "[]")
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError as exc:
        raise PatchError(
            "Run Manager %s has invalid asset_bindings_json" % manager.get("id")) from exc
    if not isinstance(parsed, list):
        raise PatchError(
            "Run Manager %s asset_bindings_json is not a list" % manager.get("id"))
    return [item for item in parsed if isinstance(item, dict)]


def _detach_run_manager_assets(workflow: dict[str, Any]) -> tuple[int, int]:
    managers = [
        node for node in workflow.get("nodes", [])
        if node.get("type") == "MiniMaxH3ChainRunManager"
    ]
    detached_links = 0
    preserved_bindings = 0
    for manager in managers:
        bindings = _asset_bindings(manager)
        if not bindings:
            raise PatchError(
                "Run Manager %s has no persisted asset bindings; refusing to detach media"
                % manager.get("id"))
        preserved_bindings += len(bindings)
        manager.setdefault("properties", {})[
            "h3_persist_detached_asset_bindings"] = True
        for item in manager.get("inputs", []):
            if not str(item.get("name", "")).startswith("asset_"):
                continue
            link_id = item.get("link")
            if link_id is None:
                continue
            _remove_link(workflow, int(link_id))
            detached_links += 1
    return detached_links, preserved_bindings


def _reindex_target_links(workflow: dict[str, Any], node: dict[str, Any],
                          old_inputs: list[dict[str, Any]],
                          new_inputs: list[dict[str, Any]]) -> None:
    old_names = {index: item.get("name") for index, item in enumerate(old_inputs)}
    new_indexes = {item.get("name"): index for index, item in enumerate(new_inputs)}
    for link in workflow.get("links", []):
        if int(link[3]) != int(node["id"]):
            continue
        old_slot = int(link[4])
        name = old_names.get(old_slot)
        if name not in new_indexes:
            raise PatchError(
                "Recovery export %s link %s targets removed input slot %s"
                % (node.get("id"), link[0], old_slot))
        link[4] = int(new_indexes[name])


def _recovery_input(item: dict[str, Any] | None, name: str, typ: str, *,
                    widget: bool = False, optional: bool = False) -> dict[str, Any]:
    result = dict(item or {})
    result["localized_name"] = result.get("localized_name") or name
    result["name"] = name
    result["type"] = typ
    result.setdefault("link", None)
    if widget:
        result["widget"] = {"name": name}
    else:
        result.pop("widget", None)
    if optional:
        result["shape"] = 7
    else:
        result.pop("shape", None)
    return result


def _patch_recovery_exports(workflow: dict[str, Any]) -> int:
    patched = 0
    for node in workflow.get("nodes", []):
        title = str(node.get("title") or "")
        if node.get("type") != "MiniMaxH3MasterExport" or not title.startswith(
                "RECOVERY MASTER EXPORT"):
            continue
        old_inputs = [dict(item) for item in node.get("inputs", [])]
        by_name = {item.get("name"): item for item in old_inputs}
        new_inputs = [
            _recovery_input(by_name.get("video_vae"), "video_vae", "VAE"),
            _recovery_input(
                by_name.get("export_config"), "export_config",
                "H3_MASTER_EXPORT_CONFIG"),
            _recovery_input(by_name.get("filename"), "filename", "STRING", widget=True),
            _recovery_input(
                by_name.get("manifest"), "manifest", "H3_CHAIN_MANIFEST", optional=True),
            _recovery_input(
                by_name.get("source_audio"), "source_audio", "AUDIO", optional=True),
        ]
        _reindex_target_links(workflow, node, old_inputs, new_inputs)
        node["inputs"] = new_inputs
        node["type"] = "MiniMaxH3MasterRecoveryExport"
        props = node.setdefault("properties", {})
        props["Node name for S&R"] = "MiniMaxH3MasterRecoveryExport"
        patched += 1
    return patched


def _validate(workflow: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = _node_map(workflow)
    links = workflow.get("links", [])
    link_ids = [int(link[0]) for link in links]
    if len(link_ids) != len(set(link_ids)):
        errors.append("duplicate link ids")
    for link in links:
        if not isinstance(link, list) or len(link) < 6:
            errors.append("malformed link %r" % (link,))
            continue
        lid, origin_id, origin_slot, target_id, target_slot, _typ = link[:6]
        origin = nodes.get(int(origin_id))
        target = nodes.get(int(target_id))
        if origin is None or target is None:
            errors.append("link %s points to missing node" % lid)
            continue
        if int(origin_slot) >= len(origin.get("outputs", [])):
            errors.append("link %s origin slot missing" % lid)
            continue
        if int(target_slot) >= len(target.get("inputs", [])):
            errors.append("link %s target slot missing" % lid)
            continue
        if int(lid) not in (origin["outputs"][int(origin_slot)].get("links") or []):
            errors.append("link %s missing from origin output metadata" % lid)
        if target["inputs"][int(target_slot)].get("link") != int(lid):
            errors.append("link %s missing from target input metadata" % lid)

    final_exports = [
        node for node in workflow.get("nodes", [])
        if node.get("type") == "MiniMaxH3MasterExport"
    ]
    if len(final_exports) != 1:
        errors.append("expected exactly one strict final master export; found %d"
                      % len(final_exports))
    else:
        try:
            manifest = final_exports[0]["inputs"][
                _input_index(final_exports[0], "manifest")]
            if manifest.get("link") is None:
                errors.append("FINAL MASTER EXPORT manifest is disconnected")
        except PatchError as exc:
            errors.append(str(exc))

    recovery = [
        node for node in workflow.get("nodes", [])
        if node.get("type") == "MiniMaxH3MasterRecoveryExport"
    ]
    if not recovery:
        errors.append("no inactive-safe recovery master export found")
    for node in recovery:
        try:
            manifest = node["inputs"][_input_index(node, "manifest")]
            if manifest.get("shape") != 7:
                errors.append("recovery export %s manifest is not optional" % node.get("id"))
        except PatchError as exc:
            errors.append(str(exc))

    managers = [
        node for node in workflow.get("nodes", [])
        if node.get("type") == "MiniMaxH3ChainRunManager"
    ]
    for manager in managers:
        if not manager.get("properties", {}).get("h3_persist_detached_asset_bindings"):
            errors.append("Run Manager %s detached-binding persistence is off"
                          % manager.get("id"))
        for item in manager.get("inputs", []):
            if str(item.get("name", "")).startswith("asset_") and item.get("link") is not None:
                errors.append("Run Manager %s still has live media asset input %s"
                              % (manager.get("id"), item.get("name")))
    return errors


def patch(workflow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    detached_links, preserved_bindings = _detach_run_manager_assets(workflow)
    recovery_exports = _patch_recovery_exports(workflow)
    errors = _validate(workflow)
    if errors:
        raise PatchError("Runtime patch validation failed:\n- " + "\n- ".join(errors))
    report = {
        "status": "RUNTIME SMOKE 01 PATCHED / RETEST REQUIRED",
        "detached_run_manager_asset_links": detached_links,
        "preserved_asset_bindings": preserved_bindings,
        "inactive_safe_recovery_exports": recovery_exports,
        "strict_final_export": True,
        "blank_media_not_forced_by_run_manager": True,
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
