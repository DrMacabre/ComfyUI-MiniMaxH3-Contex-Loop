#!/usr/bin/env python3
"""Normalize the maintained 0.5 example workflow layouts.

This is deliberately geometry-only: node IDs, links, widgets, modes, and
workflow metadata are preserved.  It keeps the generation lane above the
authoring lane and gives media/mask helpers their own unclipped space.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
AUTHORING_TYPES = {
    "MiniMaxH3ChainPlan",
    "MiniMaxH3ChainScenePromptEditor",
    "MiniMaxH3ChainPlanStudio",
    "MiniMaxH3ChainRichScenePromptEditor",
    "MiniMaxH3ChainPolicy",
}


def group(workflow, title):
    return next(
        (item for item in workflow.get("groups", [])
         if item.get("title") == title),
        None,
    )


def add_group(workflow, title, bounding, color):
    if group(workflow, title) is not None:
        return
    next_id = max(
        (int(item.get("id", 0)) for item in workflow.get("groups", [])),
        default=0,
    ) + 1
    workflow.setdefault("groups", []).append({
        "id": next_id,
        "title": title,
        "bounding": list(bounding),
        "color": color,
        "flags": {},
    })


def move(node, x=None, y=None, dx=0, dy=0):
    if not isinstance(node.get("pos"), list) or len(node["pos"]) < 2:
        return
    node["pos"][0] = (x if x is not None else node["pos"][0] + dx)
    node["pos"][1] = (y if y is not None else node["pos"][1] + dy)


def repair(path):
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = workflow.get("nodes", [])
    by_id = {item.get("id"): item for item in nodes}
    model_group = group(workflow, "H3 MODEL STACK")
    if model_group is None:
        bridge_output = group(
            workflow,
            "Final 39-frame linear overlaps + original audio around generated middle",
        )
        if bridge_output is None:
            return False
        bridge_output["bounding"][0] = 2144
        bridge_output["bounding"][2] = 2006
        rendered = json.dumps(workflow, indent=2, ensure_ascii=False) + "\n"
        original = path.read_text(encoding="utf-8")
        if rendered == original:
            return False
        path.write_text(rendered, encoding="utf-8")
        return True

    # Include the model-stack note instead of letting its lower edge be
    # clipped by the group title boundary.
    model_group["bounding"][1] = -1536
    model_group["bounding"][3] = 1162

    # The long guide note gets a stable lane left of all media loaders.
    guide = by_id.get(1906)
    if guide is not None:
        move(guide, x=-3936)
        add_group(
            workflow,
            "WORKFLOW GUIDE",
            [-4000, -1152, 864, 1280],
            "#2f596b",
        )

    # Review nodes are intentionally tall.  Reserve their full height, then
    # move authoring below the generation lane instead of drawing through it.
    core = next(
        (item for item in workflow.get("groups", [])
         if str(item.get("title", "")).startswith("CORE ")),
        None,
    )
    if core is not None:
        core["bounding"][3] = 1568

    authoring = next(
        (item for item in workflow.get("groups", [])
         if "PLAN" in str(item.get("title", ""))
         and not str(item.get("title", "")).startswith("EXPERIMENTAL")),
        None,
    )
    if authoring is not None:
        old_x, _old_y, old_width, old_height = authoring["bounding"]
        old_right = old_x + old_width
        authoring["bounding"] = [
            -1152,
            1280,
            old_right + 1152,
            max(old_height, 1728 if old_height <= 1280 else 1472),
        ]
        for item in nodes:
            if item.get("type") in AUTHORING_TYPES:
                target_y = (1504 if item.get("type") == "MiniMaxH3ChainPolicy"
                            else 1344)
                move(item, y=target_y)
            elif item.get("id") == 1932:
                move(item, y=1312)

    # Preflight belongs to the generation lane.  Keeping it below image
    # loaders avoids the old FL2V/I2V collision.
    preflight = next(
        (item for item in nodes
         if item.get("type") == "MiniMaxH3ChainPreflight"),
        None,
    )
    if preflight is not None:
        move(preflight, y=256)
        if "Sequential Motion" in path.name:
            move(preflight, x=-672)
        elif core is not None and core["bounding"][0] == -704:
            old_right = core["bounding"][0] + core["bounding"][2]
            core["bounding"][0] = -1056
            core["bounding"][2] = old_right + 1056

    # Existing-video setup sits below Loop Start, never on top of it.
    external = next(
        (item for item in nodes
         if item.get("type") == "MiniMaxH3ChainExternalVideo"),
        None,
    )
    if external is not None:
        if core is not None and core["bounding"][0] == -448:
            move(external, x=-416, y=96)
        else:
            move(external, x=-1024, y=96)
            if core is not None and core["bounding"][0] == -704:
                old_right = core["bounding"][0] + core["bounding"][2]
                core["bounding"][0] = -1056
                core["bounding"][2] = old_right + 1056

    # Source-audio Timeline previously crossed both its loader and Picture 1.
    timeline = next(
        (item for item in nodes if item.get("type") == "MiniMaxH3SourceTimeline"),
        None,
    )
    if timeline is not None:
        move(timeline, y=512)
        reference_group = next(
            (item for item in workflow.get("groups", [])
             if "SOURCE-AUDIO REFERENCES" in str(item.get("title", ""))),
            None,
        )
        if reference_group is not None:
            reference_group["bounding"][3] = 1152

    # The sequential motion source is a distinct stage between tagged stills
    # and authoring.  Move it clear of both neighboring group boundaries.
    motion_group = group(
        workflow,
        "EXPERIMENTAL LONG MOTION TIMELINE — VIDEO + AUDIO REQUIRED",
    )
    if motion_group is not None:
        motion_group["bounding"] = [-2432, 576, 1712, 480]
        motion_positions = {
            1950: [-2368, 640],
            1951: [-1760, 672],
            1952: [-1280, 672],
        }
        for node_id, position in motion_positions.items():
            if node_id in by_id:
                move(by_id[node_id], x=position[0], y=position[1])

    run_group = group(workflow, "STUDIO RUN RESTORE + ASSET ARCHIVE")
    if run_group is not None:
        run_group["bounding"][3] = 720

    # Mask helpers form a lower generation sub-lane.  Their original inserted
    # positions covered the scheduler, sampler, Studio, editor, and previews.
    if any(item.get("type") == "MiniMaxH3ContexMaskedTarget" for item in nodes):
        masked_positions = {
            "MiniMaxH3ContexLoopSourceAVTarget": [1344, 96],
            "MiniMaxH3ContexMaskedTarget": [1904, 480],
            "MiniMaxH3ContexLoopMaskSlice": [704, 576],
            "MiniMaxH3ContexMaskGridPreview": [1216, 592],
            "PreviewImage": [2400, 480],
            "PreviewAny": [2400, 842],
        }
        for item in nodes:
            position = masked_positions.get(item.get("type"))
            if position is not None:
                move(item, x=position[0], y=position[1])
        if group(workflow, "SOURCE AV + STATIC/TRACKED MASK + PICTURE 1") is None:
            add_group(
                workflow,
                "SOURCE VIDEO + STATIC/TRACKED MASK",
                [-3072, -480, 544, 1024],
                "#3f789e",
            )

    # The two extension examples use a left-hand source-video loader outside
    # every existing group.  Give it an explicit, non-overlapping stage.
    if (external is not None
            and not any("SOURCE VIDEO" in str(item.get("title", ""))
                        for item in workflow.get("groups", []))):
        add_group(
            workflow,
            "EXISTING VIDEO INPUT",
            [-3072, -480, 544, 576],
            "#3f789e",
        )

    rendered = json.dumps(workflow, indent=2, ensure_ascii=False) + "\n"
    original = path.read_text(encoding="utf-8")
    if rendered == original:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def main():
    changed = []
    for path in sorted(EXAMPLES.glob("*.json")):
        if "Deferred Upscale" in path.name:
            continue
        if repair(path):
            changed.append(path.name)
    print("Repaired %d workflow layout(s):" % len(changed))
    for name in changed:
        print("-", name)


if __name__ == "__main__":
    main()
