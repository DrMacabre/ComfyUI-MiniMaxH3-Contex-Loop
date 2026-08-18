#!/usr/bin/env python3
"""Migrate maintained H3 Chain workflow JSON to the 0.5 authoring topology.

The migration is deliberately additive. It keeps all 0.4 node ids, widget
positions, and output slots, adds explicit policy nodes, and inserts preflight
without rewriting the sampling body. The source-audio reference demo also
adopts the single typed Source Timeline route.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
SOURCE_AUDIO_DEMO = "MiniMax H3 Ref2V - Studio Tagged Source Audio.json"


def _node(workflow: dict[str, Any], node_type: str) -> dict[str, Any] | None:
    return next((item for item in workflow["nodes"]
                 if item.get("type") == node_type), None)


def _input(node: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in node.get("inputs", [])
                if item.get("name") == name)


def _output(node: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in node.get("outputs", [])
                if item.get("name") == name)


class Graph:
    def __init__(self, workflow: dict[str, Any]):
        self.workflow = workflow
        self.nodes = {item["id"]: item for item in workflow["nodes"]}
        self.links = {item[0]: item for item in workflow["links"]}
        self.next_node = max(self.nodes, default=0) + 1
        self.next_link = max(self.links, default=0) + 1
        self.order = max((int(item.get("order", 0))
                          for item in self.nodes.values()), default=0) + 1

    def add_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node["id"] = self.next_node
        node["order"] = self.order
        self.next_node += 1
        self.order += 1
        self.workflow["nodes"].append(node)
        self.nodes[node["id"]] = node
        return node

    def add_input(self, node: dict[str, Any], name: str, kind: str,
                  *, shape: int | None = 7) -> dict[str, Any]:
        existing = next((item for item in node.get("inputs", [])
                         if item.get("name") == name), None)
        if existing is not None:
            return existing
        value: dict[str, Any] = {"name": name, "type": kind, "link": None}
        if shape is not None:
            value["shape"] = shape
        node.setdefault("inputs", []).append(value)
        return value

    def connect(self, origin: dict[str, Any], origin_slot: int,
                target: dict[str, Any], target_slot: int,
                kind: str) -> int:
        target_input = target["inputs"][target_slot]
        if target_input.get("link") is not None:
            self.remove_link(int(target_input["link"]))
        link_id = self.next_link
        self.next_link += 1
        link = [link_id, origin["id"], origin_slot,
                target["id"], target_slot, kind]
        self.workflow["links"].append(link)
        self.links[link_id] = link
        if origin["outputs"][origin_slot].get("links") is None:
            origin["outputs"][origin_slot]["links"] = []
        origin["outputs"][origin_slot]["links"].append(link_id)
        target_input["link"] = link_id
        return link_id

    def remove_link(self, link_id: int) -> None:
        link = self.links.pop(link_id, None)
        if link is None:
            return
        _link_id, origin_id, origin_slot, target_id, target_slot, _kind = link
        origin_links = self.nodes[origin_id]["outputs"][origin_slot].get(
            "links") or []
        self.nodes[origin_id]["outputs"][origin_slot]["links"] = [
            item for item in origin_links if item != link_id] or None
        self.nodes[target_id]["inputs"][target_slot]["link"] = None
        self.workflow["links"] = [
            item for item in self.workflow["links"] if item[0] != link_id]

    def retarget(self, link_id: int, target: dict[str, Any],
                 target_slot: int) -> None:
        link = self.links[link_id]
        old_target = self.nodes[link[3]]
        old_target["inputs"][link[4]]["link"] = None
        link[3] = target["id"]
        link[4] = target_slot
        target["inputs"][target_slot]["link"] = link_id

    def reorigin(self, link_id: int, origin: dict[str, Any],
                 origin_slot: int) -> None:
        link = self.links[link_id]
        old_origin = self.nodes[link[1]]
        old_links = old_origin["outputs"][link[2]].get("links") or []
        old_origin["outputs"][link[2]]["links"] = [
            item for item in old_links if item != link_id] or None
        link[1] = origin["id"]
        link[2] = origin_slot
        if origin["outputs"][origin_slot].get("links") is None:
            origin["outputs"][origin_slot]["links"] = []
        origin["outputs"][origin_slot]["links"].append(link_id)

    def finish(self) -> None:
        self.workflow["last_node_id"] = max(self.nodes)
        self.workflow["last_link_id"] = max(self.links, default=0)


def _base_node(node_type: str, title: str, pos: list[float],
               size: list[float]) -> dict[str, Any]:
    return {
        "id": 0,
        "type": node_type,
        "pos": pos,
        "size": size,
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": title,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": [],
    }


def _audio_policy_node(plan: dict[str, Any]) -> dict[str, Any]:
    legacy = str(plan["widgets_values"][9])
    values = {
        "source_track": ["source", "on", "off"],
        "generated_audio": ["generated", "off", "on"],
        "source_plus_timeline": ["source", "on", "on"],
    }[legacy]
    x, y = plan["pos"]
    result = _base_node(
        "MiniMaxH3AudioPolicy", "0.5 AUDIO INTENT", [x - 420, y + 160],
        [320, 150])
    result["outputs"] = [
        {"name": "audio_policy", "type": "H3_AUDIO_POLICY", "links": []},
        {"name": "status", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = values
    return result


def _transition_policy_node(plan: dict[str, Any]) -> dict[str, Any]:
    context = int(plan["widgets_values"][5])
    mode = (str(plan["widgets_values"][16])
            if len(plan["widgets_values"]) > 16 else "guide")
    preset = {
        ("guide", 0): "cut",
        ("guide", 22): "guide",
        ("latent_guide", 22): "latent_guide",
        ("tapered_guide", 22): "detail_guide",
        ("masked_av", 39): "hard_av",
        ("feathered_av", 39): "soft_av",
    }.get((mode, context), "guide")
    expert = (mode, context) not in {
        ("guide", 0), ("guide", 22), ("latent_guide", 22),
        ("tapered_guide", 22),
        ("masked_av", 39),
        ("feathered_av", 39),
    }
    x, y = plan["pos"]
    result = _base_node(
        "MiniMaxH3TransitionPolicy", "0.5 INCOMING TRANSITION",
        [x - 420, y + 360], [320, 190])
    result["outputs"] = [
        {"name": "transition_policy", "type": "H3_TRANSITION_POLICY",
         "links": []},
        {"name": "continuation_mode", "type": "STRING", "links": None},
        {"name": "context_length", "type": "INT", "links": None},
        {"name": "status", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = [preset, expert, mode, context]
    return result


def _preflight_node(start: dict[str, Any]) -> dict[str, Any]:
    x, y = start["pos"]
    result = _base_node(
        "MiniMaxH3ChainPreflight", "0.5 PREFLIGHT — BLOCKS BEFORE MODELS",
        [x - 448, y + 256], [384, 260])
    result["inputs"] = [
        {"name": "plan", "type": "H3_CHAIN_PLAN", "link": None},
        {"name": "source_timeline", "shape": 7,
         "type": "H3_SOURCE_TIMELINE", "link": None},
        {"name": "source_audio", "shape": 7,
         "type": "AUDIO", "link": None},
        {"name": "tagged_references", "shape": 7,
         "type": "H3_TAGGED_REFERENCES", "link": None},
        {"name": "reference_schedule", "shape": 7,
         "type": "H3_REFERENCE_SCHEDULE", "link": None},
    ]
    result["outputs"] = [
        {"name": "plan", "type": "H3_CHAIN_PLAN", "links": []},
        {"name": "preflight", "type": "H3_PREFLIGHT", "links": None},
        {"name": "ready", "type": "BOOLEAN", "links": None},
        {"name": "status", "type": "STRING", "links": None},
        {"name": "report_json", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = [1, "", True]
    return result


def _source_timeline_node(audio_loader: dict[str, Any]) -> dict[str, Any]:
    x, y = audio_loader["pos"]
    result = _base_node(
        "MiniMaxH3SourceTimeline", "0.5 SOURCE TIMELINE — SELECT ONCE",
        [x + 416, y], [352, 230])
    result["inputs"] = [
        {"name": "source_video", "shape": 7, "type": "VIDEO", "link": None},
        {"name": "source_audio", "shape": 7, "type": "AUDIO", "link": None},
    ]
    result["outputs"] = [
        {"name": "source_timeline", "type": "H3_SOURCE_TIMELINE", "links": []},
        {"name": "status", "type": "STRING", "links": None},
    ]
    result["widgets_values"] = ["", "", "ignore", 0]
    return result


def _replace_text(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_text(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_text(item, old, new)
                for key, item in value.items()}
    return value


def _reference_registry(workflow: dict[str, Any], graph: Graph
                        ) -> tuple[dict[str, Any], int, str] | None:
    for wrapper_type, input_name, kind in (
        ("MiniMaxH3TaggedReferenceToVideo", "references",
         "H3_TAGGED_REFERENCES"),
        ("MiniMaxH3ScheduledReferenceToVideo", "reference_schedule",
         "H3_REFERENCE_SCHEDULE"),
    ):
        wrapper = _node(workflow, wrapper_type)
        if wrapper is None:
            continue
        value = _input(wrapper, input_name)
        if value.get("link") is None:
            continue
        link = graph.links[int(value["link"])]
        origin = graph.nodes[link[1]]
        # A timeline-derived Tagged Audio node lives downstream of Current
        # Shot. Returning it to preflight or Plan would close an execution
        # cycle, so that demo relies on source-timeline validation instead.
        if origin.get("type") == "MiniMaxH3TaggedAudioReference":
            return None
        return origin, int(link[2]), kind
    return None


def _add_policies(workflow: dict[str, Any], graph: Graph) -> None:
    plan = _node(workflow, "MiniMaxH3ChainPlan")
    assert plan is not None
    if _node(workflow, "MiniMaxH3AudioPolicy") is None:
        audio = graph.add_node(_audio_policy_node(plan))
        plan_input = graph.add_input(
            plan, "audio_policy", "H3_AUDIO_POLICY")
        graph.connect(audio, 0, plan, plan["inputs"].index(plan_input),
                      "H3_AUDIO_POLICY")
    if _node(workflow, "MiniMaxH3TransitionPolicy") is None:
        transition = graph.add_node(_transition_policy_node(plan))
        plan_input = graph.add_input(
            plan, "transition_policy", "H3_TRANSITION_POLICY")
        graph.connect(transition, 0, plan, plan["inputs"].index(plan_input),
                      "H3_TRANSITION_POLICY")


def _add_preflight(workflow: dict[str, Any], graph: Graph) -> None:
    start = _node(workflow, "MiniMaxH3ChainLoopStart")
    assert start is not None
    studio = _node(workflow, "MiniMaxH3ChainPlanStudio")
    registry = _reference_registry(workflow, graph)
    if studio is not None:
        for name, kind in (
            ("source_timeline", "H3_SOURCE_TIMELINE"),
            ("source_audio", "AUDIO"),
            ("tagged_references", "H3_TAGGED_REFERENCES"),
            ("reference_schedule", "H3_REFERENCE_SCHEDULE"),
        ):
            graph.add_input(studio, name, kind)
        if len(studio.get("widgets_values", [])) < 3:
            studio["widgets_values"] = [1, "", True]
        if registry is not None:
            origin, slot, kind = registry
            name = ("tagged_references" if kind == "H3_TAGGED_REFERENCES"
                    else "reference_schedule")
            target_input = _input(studio, name)
            if target_input.get("link") is None:
                graph.connect(origin, slot, studio,
                              studio["inputs"].index(target_input), kind)
        return

    if _node(workflow, "MiniMaxH3ChainPreflight") is not None:
        return
    preflight = graph.add_node(_preflight_node(start))
    plan_socket = _input(start, "plan")
    old_link = int(plan_socket["link"])
    graph.retarget(old_link, preflight, 0)
    graph.connect(preflight, 0, start, start["inputs"].index(plan_socket),
                  "H3_CHAIN_PLAN")
    if registry is not None:
        origin, slot, kind = registry
        target_name = ("tagged_references"
                       if kind == "H3_TAGGED_REFERENCES"
                       else "reference_schedule")
        graph.connect(origin, slot, preflight,
                      preflight["inputs"].index(_input(preflight, target_name)),
                      kind)


def _migrate_source_audio_demo(workflow: dict[str, Any], graph: Graph) -> None:
    revised = _replace_text(
        workflow,
        "@audio_1 is the full source-track audio reference; preserve its exact "
        "scene-local timing and performance identity.",
        "@audio_1 is the exact current-scene source-track slice; preserve its "
        "timing and performance identity.",
    )
    workflow.clear()
    workflow.update(revised)
    graph.workflow = workflow
    graph.nodes = {item["id"]: item for item in workflow["nodes"]}
    graph.links = {item[0]: item for item in workflow["links"]}
    if _node(workflow, "MiniMaxH3SourceTimeline") is not None:
        return
    loader = _node(workflow, "LoadAudio")
    audio_ref = _node(workflow, "MiniMaxH3TaggedAudioReference")
    current = _node(workflow, "MiniMaxH3ChainCurrent")
    start = _node(workflow, "MiniMaxH3ChainLoopStart")
    studio = _node(workflow, "MiniMaxH3ChainPlanStudio")
    manifest = _node(workflow, "MiniMaxH3ChainManifestLoad")
    plan = _node(workflow, "MiniMaxH3ChainPlan")
    assert all(item is not None for item in (
        loader, audio_ref, current, start, studio, manifest, plan))

    timeline = graph.add_node(_source_timeline_node(loader))
    graph.connect(loader, 0, timeline, 1, "AUDIO")

    # Replace the legacy full-track fan-out. The typed descriptor is carried
    # in recursive state and saved metadata; Current Shot exposes only the
    # scene-local reference window.
    for consumer in (start, current, manifest, *[
            item for item in workflow["nodes"]
            if item.get("type") == "MiniMaxH3ChainAssemble"]):
        legacy = next((item for item in consumer.get("inputs", [])
                       if item.get("name") == "source_audio"), None)
        if legacy is not None and legacy.get("link") is not None:
            graph.remove_link(int(legacy["link"]))

    start_timeline = graph.add_input(
        start, "source_timeline", "H3_SOURCE_TIMELINE")
    graph.connect(timeline, 0, start,
                  start["inputs"].index(start_timeline),
                  "H3_SOURCE_TIMELINE")
    studio_timeline = _input(studio, "source_timeline")
    graph.connect(timeline, 0, studio,
                  studio["inputs"].index(studio_timeline),
                  "H3_SOURCE_TIMELINE")
    manifest_timeline = graph.add_input(
        manifest, "source_timeline", "H3_SOURCE_TIMELINE")
    graph.connect(timeline, 0, manifest,
                  manifest["inputs"].index(manifest_timeline),
                  "H3_SOURCE_TIMELINE")

    audio_link = int(_input(audio_ref, "audio")["link"])
    graph.reorigin(audio_link, current, 12)
    audio_ref["widgets_values"] = ["audio_1", "standalone", False]
    audio_ref["title"] = "3 — @audio_1 / CURRENT SCENE SLICE"
    current["widgets_values"] = [True]

    # The previous picture registry remains a static generation fingerprint.
    # Source audio is now recorded as a canonical per-scene dependency, so its
    # downstream slice must not feed back into Plan.
    fingerprint_link = _input(plan, "generation_fingerprint").get("link")
    previous_link = _input(audio_ref, "previous").get("link")
    if fingerprint_link is not None and previous_link is not None:
        previous = graph.links[int(previous_link)]
        graph.reorigin(int(fingerprint_link), graph.nodes[previous[1]], 1)


def migrate(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    if _node(workflow, "MiniMaxH3ChainPlan") is None:
        return workflow
    graph = Graph(workflow)
    _add_policies(workflow, graph)
    _add_preflight(workflow, graph)
    if name == SOURCE_AUDIO_DEMO:
        _migrate_source_audio_demo(workflow, graph)
    graph.finish()
    return workflow


def active_paths() -> list[Path]:
    return sorted(path for path in EXAMPLES.glob("*.json")
                  if _node(json.loads(path.read_text(encoding="utf-8")),
                           "MiniMaxH3ChainPlan") is not None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="Workflow JSON paths (defaults to maintained examples)")
    parser.add_argument("--check", action="store_true",
                        help="Report workflows that still need migration")
    args = parser.parse_args()
    paths = args.paths or active_paths()
    changed = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        workflow = migrate(json.loads(source), path.name)
        rendered = json.dumps(workflow, ensure_ascii=False, indent=2) + "\n"
        if rendered != source:
            changed.append(path)
            if not args.check:
                path.write_text(rendered, encoding="utf-8")
    if args.check and changed:
        for path in changed:
            print(path)
        return 1
    print(("would migrate" if args.check else "migrated"),
          len(changed), "workflow(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
