#!/usr/bin/env python3
"""Regression for compact numbered Load Media -> Ref Slot bank layout."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import _master_workflow_migrator_test as base  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "master_reference_repack", ROOT / "tools" / "repack_master_workflow.py")
repack = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(repack)


def by_title(workflow, title):
    matches = [node for node in workflow["nodes"] if node.get("title") == title]
    assert len(matches) == 1, (title, len(matches))
    return matches[0]


def main():
    workflow, _ = base.builder.migrate(base.make_workflow())
    report = repack.repack(workflow)
    assert report["status"] == "REFERENCE BANKS REPACKED"

    for name, config in repack.BANKS.items():
        bank = report["banks"][name]
        assert len(bank["pairs"]) == config["count"]
        for number in range(1, config["count"] + 1):
            loader = by_title(workflow, config["loader_title"].format(n=number))
            slot = by_title(workflow, config["slot_title"].format(n=number))
            assert loader["pos"][0] == slot["pos"][0]
            assert loader["pos"][1] < slot["pos"][1]
            assert loader["size"] == config["loader_size"]
            assert slot["size"] == config["slot_size"]

    # Image bank is a readable 1-2-3 / 4-5-6 / 7-8-9 grid.
    image_positions = [
        by_title(workflow, "IMAGE REF %d — LOAD IMAGE" % number)["pos"]
        for number in range(1, 10)
    ]
    assert image_positions[0][1] == image_positions[1][1] == image_positions[2][1]
    assert image_positions[3][1] == image_positions[4][1] == image_positions[5][1]
    assert image_positions[6][1] == image_positions[7][1] == image_positions[8][1]
    assert image_positions[0][0] < image_positions[1][0] < image_positions[2][0]
    assert image_positions[3][0] < image_positions[4][0] < image_positions[5][0]
    assert image_positions[6][0] < image_positions[7][0] < image_positions[8][0]

    print("PASS compact paired master reference-bank layout")


if __name__ == "__main__":
    main()
