#!/usr/bin/env python3
"""Compact the generated H3 MASTER reference banks into readable pairs.

This is a pure LiteGraph-layout pass: it never changes node ids, links, widget
values, prompt content, policies, or media bindings. Each reference bank is
repacked as numbered Load Media -> ON/OFF + @tag pairs, then its group bounds
are recomputed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


BANKS = {
    "image": {
        "group": "REFERENCE BANK — IMAGES 1–9",
        "count": 9,
        "loader_type": "LoadImage",
        "slot_type": "MiniMaxH3MasterPictureReferenceSlot",
        "loader_title": "IMAGE REF {n} — LOAD IMAGE",
        "slot_title": "IMAGE REF {n} — ON/OFF + @tag",
        "media_input": "image",
        "columns": 3,
        "loader_size": [430, 160],
        "slot_size": [430, 180],
    },
    "video": {
        "group": "REFERENCE BANK — VIDEOS 1–3",
        "count": 3,
        "loader_type": "LoadVideo",
        "slot_type": "MiniMaxH3MasterVideoReferenceSlot",
        "loader_title": "VIDEO REF {n} — LOAD VIDEO",
        "slot_title": "VIDEO REF {n} — ON/OFF + @tag",
        "media_input": "video",
        "columns": 3,
        "loader_size": [430, 140],
        "slot_size": [430, 180],
    },
    "audio": {
        "group": "REFERENCE BANK — AUDIO 1–3",
        "count": 3,
        "loader_type": "LoadAudio",
        "slot_type": "MiniMaxH3MasterAudioReferenceSlot",
        "loader_title": "AUDIO REF {n} — LOAD AUDIO",
        "slot_title": "AUDIO REF {n} — ON/OFF + @tag",
        "media_input": "audio",
        "columns": 3,
        "loader_size": [430, 160],
        "slot_size": [430, 180],
    },
}


class LayoutError(RuntimeError):
    pass


def _group(workflow: dict[str, Any], title: str) -> dict[str, Any]:
    matches = [g for g in workflow.get("groups", []) if g.get("title") == title]
    if len(matches) != 1:
        raise LayoutError("Expected exactly one group %r; found %d" % (title, len(matches)))
    return matches[0]


def _node(workflow: dict[str, Any], typ: str, title: str) -> dict[str, Any]:
    matches = [
        n for n in workflow.get("nodes", [])
        if n.get("type") == typ and n.get("title") == title
    ]
    if len(matches) != 1:
        raise LayoutError(
            "Expected exactly one %s titled %r; found %d" % (typ, title, len(matches)))
    return matches[0]


def _input(node: dict[str, Any], name: str) -> dict[str, Any]:
    for item in node.get("inputs", []):
        if item.get("name") == name:
            return item
    raise LayoutError("%s has no input %r" % (node.get("title"), name))


def _link_map(workflow: dict[str, Any]) -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 6:
            result[int(link[0])] = link
    return result


def _assert_pair_link(workflow: dict[str, Any], loader: dict[str, Any],
                      slot: dict[str, Any], media_input: str) -> None:
    target = _input(slot, media_input)
    link_id = target.get("link")
    if link_id is None:
        raise LayoutError("%s is not connected to its loader" % slot.get("title"))
    record = _link_map(workflow).get(int(link_id))
    if record is None:
        raise LayoutError("Missing link %s for %s" % (link_id, slot.get("title")))
    if int(record[1]) != int(loader["id"]):
        raise LayoutError(
            "%s is fed by node %s, expected loader %s" %
            (slot.get("title"), record[1], loader["id"]))


def _bounds(nodes: list[dict[str, Any]], margin: int = 42) -> list[int]:
    if not nodes:
        return [0, 0, 100, 100]
    x1 = min(float(n["pos"][0]) for n in nodes) - margin
    y1 = min(float(n["pos"][1]) for n in nodes) - margin
    x2 = max(float(n["pos"][0]) + float(n["size"][0]) for n in nodes) + margin
    y2 = max(float(n["pos"][1]) + float(n["size"][1]) for n in nodes) + margin
    return [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]


def _rect(node: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y = map(float, node["pos"][:2])
    w, h = map(float, node["size"][:2])
    return x, y, x + w, y + h


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax1, ay1, ax2, ay2 = _rect(a)
    bx1, by1, bx2, by2 = _rect(b)
    return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2


def _repack_bank(workflow: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    group = _group(workflow, config["group"])
    bounding = group.get("bounding") or [0, 0, 100, 100]
    anchor_x = int(bounding[0]) + 52
    anchor_y = int(bounding[1]) + 52
    columns = int(config["columns"])
    cell_width = 520
    vertical_gap = 24
    row_gap = 72
    pair_height = int(config["loader_size"][1]) + vertical_gap + int(config["slot_size"][1])
    cell_height = pair_height + row_gap

    bank_nodes: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for number in range(1, int(config["count"]) + 1):
        loader = _node(
            workflow, config["loader_type"], config["loader_title"].format(n=number))
        slot = _node(
            workflow, config["slot_type"], config["slot_title"].format(n=number))
        _assert_pair_link(workflow, loader, slot, config["media_input"])

        row = (number - 1) // columns
        column = (number - 1) % columns
        x = anchor_x + column * cell_width
        y = anchor_y + row * cell_height

        loader["size"] = list(config["loader_size"])
        slot["size"] = list(config["slot_size"])
        loader["pos"] = [x, y]
        slot["pos"] = [x, y + int(config["loader_size"][1]) + vertical_gap]

        bank_nodes.extend((loader, slot))
        pairs.append({
            "number": number,
            "loader_id": int(loader["id"]),
            "slot_id": int(slot["id"]),
            "loader_pos": list(loader["pos"]),
            "slot_pos": list(slot["pos"]),
        })

    for index, first in enumerate(bank_nodes):
        for second in bank_nodes[index + 1:]:
            if _overlap(first, second):
                raise LayoutError(
                    "Reference-bank layout overlap: %s / %s" %
                    (first.get("title"), second.get("title")))

    group["bounding"] = _bounds(bank_nodes)
    return {
        "group": config["group"],
        "pairs": pairs,
        "bounding": list(group["bounding"]),
    }


def repack(workflow: dict[str, Any]) -> dict[str, Any]:
    report = {"status": "REFERENCE BANKS REPACKED", "banks": {}}
    for name, config in BANKS.items():
        report["banks"][name] = _repack_bank(workflow, config)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", help="Generated Default H3 - MASTER.json")
    parser.add_argument("--output", help="Output path; defaults to in-place")
    parser.add_argument("--report", help="Optional layout report JSON")
    args = parser.parse_args(argv)

    source = Path(args.workflow)
    if not source.is_file():
        raise SystemExit("Workflow not found: %s" % source)
    target = Path(args.output) if args.output else source

    with source.open("r", encoding="utf-8-sig") as handle:
        workflow = json.load(handle)
    report = repack(workflow)

    target.write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    print(json.dumps({"output": str(target), **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
