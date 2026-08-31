#!/usr/bin/env python3
"""Transform the authoritative Default H3 workflow into the reusable master UI.

This tool intentionally edits the supplied workflow in place structurally; it
never reconstructs a project from remembered node ids. Stable roles are found
from node types, socket names and the nine h3-ref-slot-* loader bindings.

Usage:
    python tools/build_master_workflow.py "Default H3.json" \
        --output "Default H3 - MASTER.json"

The generated workflow remains runtime-inconclusive until opened and exercised
inside the user's actual ComfyUI installation.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Iterable


PLUGIN_AUX = "ethanfel/ComfyUI-MiniMaxH3-Contex-Loop"
PLUGIN_CNR = "comfyui-minimaxh3-contex-loop"
PLUGIN_VER = "0.6.37-master-ui"
CORE_VER = "0.33.0"

OLD_REFERENCE_TYPES = {
    "MiniMaxH3TaggedPictureReference",
    "MiniMaxH3OptionalTaggedPictureReference",
    "MiniMaxH3TaggedVideoReference",
    "MiniMaxH3TaggedAudioReference",
    "MiniMaxH3ScheduledPictureReference",
    "MiniMaxH3ScheduledVideoReference",
    "MiniMaxH3ScheduledAudioReference",
}

GROUP_ORDER = (
    "MODEL STACK",
    "REFERENCE BANK — IMAGES 1–9",
    "REFERENCE BANK — VIDEOS 1–3",
    "REFERENCE BANK — AUDIO 1–3",
    "SOURCE MEDIA",
    "MODE / ROUTING CONTROLS",
    "PLAN / PLAN STUDIO / PROMPT EDITOR",
    "H3 GENERATION CORE",
    "REVIEW / SAVE / CHECKPOINT",
    "VIDEO OUTPUT / MASTER EXPORT",
    "RECOVERY",
)


class WorkflowError(RuntimeError):
    pass


def _input(name: str, typ: str, *, widget: bool = False,
           optional: bool = False, label: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "localized_name": name,
        "name": name,
        "type": typ,
        "link": None,
    }
    if optional:
        value["shape"] = 7
    if widget:
        value["widget"] = {"name": name}
    if label:
        value["label"] = label
    return value


def _output(name: str, typ: str) -> dict[str, Any]:
    return {
        "localized_name": name,
        "name": name,
        "type": typ,
        "links": None,
    }


def _plugin_properties(node_type: str) -> dict[str, Any]:
    return {
        "aux_id": PLUGIN_AUX,
        "ver": PLUGIN_VER,
        "Node name for S&R": node_type,
        "cnr_id": PLUGIN_CNR,
        "ue_properties": {
            "input_ue_unconnectable": {},
            "version": "7.8",
            "widget_ue_connectable": {},
        },
    }


def _core_properties(node_type: str) -> dict[str, Any]:
    return {
        "cnr_id": "comfy-core",
        "ver": CORE_VER,
        "Node name for S&R": node_type,
        "ue_properties": {
            "input_ue_unconnectable": {},
            "version": "7.8",
            "widget_ue_connectable": {},
        },
    }


def _node(node_id: int, node_type: str, title: str, inputs: list[dict[str, Any]],
          outputs: list[dict[str, Any]], widgets: list[Any] | None = None,
          widgets_named: dict[str, Any] | None = None, *,
          size: tuple[int, int] = (420, 220), collapsed: bool = False,
          core: bool = False) -> dict[str, Any]:
    return {
        "id": int(node_id),
        "type": node_type,
        "pos": [0, 0],
        "size": [int(size[0]), int(size[1])],
        "flags": {"collapsed": True} if collapsed else {},
        "order": 0,
        "mode": 0,
        "inputs": inputs,
        "outputs": outputs,
        "title": title,
        "properties": _core_properties(node_type) if core else _plugin_properties(node_type),
        "widgets_values": list(widgets or []),
        "widgets_values_named": dict(widgets_named or {}),
    }


class Graph:
    def __init__(self, workflow: dict[str, Any]):
        self.workflow = workflow
        self.nodes: list[dict[str, Any]] = workflow.setdefault("nodes", [])
        self.links: list[list[Any]] = workflow.setdefault("links", [])
        self.next_node_id = max(
            [int(workflow.get("last_node_id", 0))]
            + [int(n.get("id", 0)) for n in self.nodes]) + 1
        self.next_link_id = max(
            [int(workflow.get("last_link_id", 0))]
            + [int(link[0]) for link in self.links if isinstance(link, list) and link]) + 1

    def by_id(self, node_id: int) -> dict[str, Any]:
        for node in self.nodes:
            if int(node.get("id", -1)) == int(node_id):
                return node
        raise WorkflowError("Missing node id %s" % node_id)

    def one(self, node_type: str) -> dict[str, Any]:
        matches = [n for n in self.nodes if n.get("type") == node_type]
        if len(matches) != 1:
            raise WorkflowError(
                "Expected exactly one %s node; found %d" % (node_type, len(matches)))
        return matches[0]

    def all(self, node_type: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes if n.get("type") == node_type]

    def input_index(self, node: dict[str, Any], name: str) -> int:
        for index, item in enumerate(node.get("inputs", [])):
            if item.get("name") == name:
                return index
        raise WorkflowError("%s has no input %r" % (node.get("type"), name))

    def output_index(self, node: dict[str, Any], name: str) -> int:
        for index, item in enumerate(node.get("outputs", [])):
            if item.get("name") == name:
                return index
        raise WorkflowError("%s has no output %r" % (node.get("type"), name))

    def link_record(self, link_id: int) -> list[Any]:
        for link in self.links:
            if int(link[0]) == int(link_id):
                return link
        raise WorkflowError("Missing link id %s" % link_id)

    def disconnect_input(self, node: dict[str, Any], name: str) -> None:
        index = self.input_index(node, name)
        link_id = node["inputs"][index].get("link")
        if link_id is not None:
            self.remove_link(int(link_id))

    def remove_link(self, link_id: int) -> None:
        record = None
        for item in self.links:
            if int(item[0]) == int(link_id):
                record = item
                break
        if record is None:
            return
        _, origin_id, origin_slot, target_id, target_slot, _typ = record
        try:
            origin = self.by_id(int(origin_id))
            output = origin.get("outputs", [])[int(origin_slot)]
            links = output.get("links") or []
            output["links"] = [x for x in links if int(x) != int(link_id)] or None
        except (WorkflowError, IndexError, TypeError):
            pass
        try:
            target = self.by_id(int(target_id))
            target.get("inputs", [])[int(target_slot)]["link"] = None
        except (WorkflowError, IndexError, TypeError):
            pass
        self.links.remove(record)

    def disconnect_node(self, node: dict[str, Any]) -> None:
        ids: set[int] = set()
        for item in node.get("inputs", []):
            if item.get("link") is not None:
                ids.add(int(item["link"]))
        for output in node.get("outputs", []):
            for link_id in output.get("links") or []:
                ids.add(int(link_id))
        for link_id in sorted(ids):
            self.remove_link(link_id)

    def remove_node(self, node: dict[str, Any]) -> None:
        self.disconnect_node(node)
        self.nodes.remove(node)

    def clear_output_links(self, node: dict[str, Any], slot: int = 0) -> None:
        output = node.get("outputs", [])[slot]
        for link_id in list(output.get("links") or []):
            self.remove_link(int(link_id))

    def add_node(self, node: dict[str, Any]) -> dict[str, Any]:
        node["id"] = self.next_node_id
        self.next_node_id += 1
        self.nodes.append(node)
        return node

    def new(self, node_type: str, title: str, inputs: list[dict[str, Any]],
            outputs: list[dict[str, Any]], widgets: list[Any] | None = None,
            widgets_named: dict[str, Any] | None = None, *,
            size: tuple[int, int] = (420, 220), collapsed: bool = False,
            core: bool = False) -> dict[str, Any]:
        return self.add_node(_node(
            0, node_type, title, inputs, outputs, widgets, widgets_named,
            size=size, collapsed=collapsed, core=core))

    def connect(self, origin: dict[str, Any], origin_slot: int,
                target: dict[str, Any], target_input: int, typ: str) -> int:
        existing = target.get("inputs", [])[target_input].get("link")
        if existing is not None:
            self.remove_link(int(existing))
        link_id = self.next_link_id
        self.next_link_id += 1
        record = [
            link_id, int(origin["id"]), int(origin_slot),
            int(target["id"]), int(target_input), typ,
        ]
        self.links.append(record)
        target["inputs"][target_input]["link"] = link_id
        output = origin["outputs"][origin_slot]
        values = list(output.get("links") or [])
        values.append(link_id)
        output["links"] = values
        return link_id

    def connect_names(self, origin: dict[str, Any], output_name: str,
                      target: dict[str, Any], input_name: str,
                      typ: str | None = None) -> int:
        oslot = self.output_index(origin, output_name)
        islot = self.input_index(target, input_name)
        return self.connect(
            origin, oslot, target, islot,
            typ or str(origin["outputs"][oslot].get("type") or "*"))

    def origin_for_input(self, node: dict[str, Any], name: str) -> tuple[dict[str, Any], int, str] | None:
        index = self.input_index(node, name)
        link_id = node["inputs"][index].get("link")
        if link_id is None:
            return None
        record = self.link_record(int(link_id))
        return self.by_id(int(record[1])), int(record[2]), str(record[5])

    def finish(self) -> None:
        self.workflow["last_node_id"] = max(int(n["id"]) for n in self.nodes)
        self.workflow["last_link_id"] = max([0] + [int(link[0]) for link in self.links])
        for order, node in enumerate(sorted(self.nodes, key=lambda n: int(n["id"]))):
            node["order"] = order


def _binding_id(node: dict[str, Any]) -> str | None:
    mapping = node.get("properties", {}).get("h3_asset_binding_ids", {})
    if isinstance(mapping, dict):
        value = mapping.get("0", mapping.get(0))
        return str(value) if value else None
    return None


def _set_binding(node: dict[str, Any], binding_id: str) -> None:
    node.setdefault("properties", {})["h3_asset_binding_ids"] = {"0": binding_id}


def _set_widget(node: dict[str, Any], name: str, value: Any) -> None:
    named = node.setdefault("widgets_values_named", {})
    named[name] = value
    widget_names = [
        item.get("widget", {}).get("name")
        for item in node.get("inputs", [])
        if isinstance(item.get("widget"), dict)
    ]
    values = node.setdefault("widgets_values", [])
    try:
        index = widget_names.index(name)
    except ValueError:
        return
    while len(values) <= index:
        values.append(None)
    values[index] = value


def _clear_loader(node: dict[str, Any], widget_name: str) -> None:
    _set_widget(node, widget_name, "")
    if widget_name == "image":
        _set_widget(node, "upload", "image")
    elif widget_name in ("audio", "file"):
        _set_widget(node, "upload", None)


def _picture_slot(g: Graph, number: int) -> dict[str, Any]:
    return g.new(
        "MiniMaxH3MasterPictureReferenceSlot",
        "IMAGE REF %d — ON/OFF + @tag" % number,
        [_input("enabled", "BOOLEAN", widget=True),
         _input("tag", "STRING", widget=True),
         _input("image", "IMAGE"),
         _input("previous", "H3_TAGGED_REFERENCES", optional=True)],
        [_output("references", "H3_TAGGED_REFERENCES"),
         _output("reference_fingerprint", "STRING"),
         _output("status", "STRING")],
        [False, "image_ref_%d" % number],
        {"enabled": False, "tag": "image_ref_%d" % number},
        size=(430, 180))


def _video_slot(g: Graph, number: int) -> dict[str, Any]:
    return g.new(
        "MiniMaxH3MasterVideoReferenceSlot",
        "VIDEO REF %d — ON/OFF + @tag" % number,
        [_input("enabled", "BOOLEAN", widget=True),
         _input("tag", "STRING", widget=True),
         _input("video", "VIDEO"),
         _input("previous", "H3_TAGGED_REFERENCES", optional=True)],
        [_output("references", "H3_TAGGED_REFERENCES"),
         _output("reference_fingerprint", "STRING"),
         _output("status", "STRING")],
        [False, "video_ref_%d" % number],
        {"enabled": False, "tag": "video_ref_%d" % number},
        size=(430, 180))


def _audio_slot(g: Graph, number: int) -> dict[str, Any]:
    return g.new(
        "MiniMaxH3MasterAudioReferenceSlot",
        "AUDIO REF %d — ON/OFF + @tag" % number,
        [_input("enabled", "BOOLEAN", widget=True),
         _input("tag", "STRING", widget=True),
         _input("audio", "AUDIO"),
         _input("previous", "H3_TAGGED_REFERENCES", optional=True)],
        [_output("references", "H3_TAGGED_REFERENCES"),
         _output("reference_fingerprint", "STRING"),
         _output("status", "STRING")],
        [False, "audio_ref_%d" % number],
        {"enabled": False, "tag": "audio_ref_%d" % number},
        size=(430, 180))


def _load_audio(g: Graph, title: str, binding: str) -> dict[str, Any]:
    node = g.new(
        "LoadAudio", title,
        [_input("audio", "COMBO", widget=True),
         _input("audioUI", "AUDIO_UI", widget=True),
         _input("upload", "AUDIOUPLOAD", widget=True)],
        [_output("AUDIO", "AUDIO")],
        ["", None, None], {"audio": "", "upload": None},
        size=(430, 140), core=True)
    _set_binding(node, binding)
    return node


def _load_video(g: Graph, title: str, binding: str) -> dict[str, Any]:
    # Current core LoadVideo uses one uploaded Combo named `file` and returns VIDEO.
    node = g.new(
        "LoadVideo", title,
        [_input("file", "COMBO", widget=True)],
        [_output("video", "VIDEO")],
        [""], {"file": ""}, size=(430, 160), core=True)
    _set_binding(node, binding)
    return node


def _mode_nodes(g: Graph) -> dict[str, dict[str, Any]]:
    audio = g.new(
        "MiniMaxH3MasterAudioMode", "AUDIO MODE",
        [_input("audio_mode", "COMBO", widget=True),
         _input("generated_level", "FLOAT", widget=True),
         _input("external_level", "FLOAT", widget=True)],
        [_output("chain_policy", "H3_CHAIN_POLICY"),
         _output("audio_control", "H3_MASTER_AUDIO_CONTROL"),
         _output("status", "STRING")],
        ["H3 GENERATED", 1.0, 1.0],
        {"audio_mode": "H3 GENERATED", "generated_level": 1.0,
         "external_level": 1.0}, size=(500, 240))
    transition = g.new(
        "MiniMaxH3MasterTransitionMode", "CONTINUATION MODE",
        [_input("continuation_mode", "COMBO", widget=True)],
        [_output("transition_control", "H3_MASTER_TRANSITION_CONTROL"),
         _output("status", "STRING")],
        ["NEW SHOT / GUIDE"],
        {"continuation_mode": "NEW SHOT / GUIDE"}, size=(500, 150))
    video = g.new(
        "MiniMaxH3MasterVideoMode", "SOURCE VIDEO MODE",
        [_input("video_mode", "COMBO", widget=True)],
        [_output("video_control", "H3_MASTER_VIDEO_CONTROL"),
         _output("status", "STRING")],
        ["H3 GENERATION"], {"video_mode": "H3 GENERATION"}, size=(500, 150))
    policy = g.new(
        "MiniMaxH3MasterChainPolicyRouter", "INTERNAL — POLICY ROUTER",
        [_input("audio_control", "H3_MASTER_AUDIO_CONTROL"),
         _input("transition_control", "H3_MASTER_TRANSITION_CONTROL")],
        [_output("chain_policy", "H3_CHAIN_POLICY"), _output("status", "STRING")],
        size=(360, 120), collapsed=True)
    gate = g.new(
        "MiniMaxH3MasterSourceAudioGate", "INTERNAL — SOURCE AUDIO GATE",
        [_input("audio_control", "H3_MASTER_AUDIO_CONTROL"),
         _input("source_audio", "AUDIO", optional=True)],
        [_output("source_audio", "AUDIO"), _output("status", "STRING")],
        size=(360, 120), collapsed=True)
    audio_router = g.new(
        "MiniMaxH3MasterAudioRouter", "INTERNAL — FINAL AUDIO ROUTER",
        [_input("state", "H3_CHAIN_STATE"),
         _input("audio_control", "H3_MASTER_AUDIO_CONTROL"),
         _input("source_audio", "AUDIO", optional=True),
         _input("generated_audio", "AUDIO", optional=True),
         _input("external_audio", "AUDIO", optional=True)],
        [_output("audio", "AUDIO"), _output("status", "STRING")],
        size=(390, 160), collapsed=True)
    existing_video = g.new(
        "MiniMaxH3MasterExistingVideoRouter", "INTERNAL — SOURCE VIDEO CONTINUE",
        [_input("plan", "H3_CHAIN_PLAN"),
         _input("video_control", "H3_MASTER_VIDEO_CONTROL"),
         _input("source_video", "VIDEO", optional=True)],
        [_output("external_context", "H3_EXTERNAL_CONTEXT"),
         _output("status", "STRING")], size=(390, 140), collapsed=True)
    source_target = g.new(
        "MiniMaxH3MasterSourceVideoTarget", "INTERNAL — SOURCE VIDEO EDIT",
        [_input("state", "H3_CHAIN_STATE"), _input("latent", "LATENT"),
         _input("vae", "VAE"),
         _input("video_control", "H3_MASTER_VIDEO_CONTROL"),
         _input("source_video", "VIDEO", optional=True)],
        [_output("latent", "LATENT"), _output("status", "STRING")],
        size=(390, 160), collapsed=True)
    export_profile = g.new(
        "MiniMaxH3MasterExportProfile", "EXPORT PROFILE — ONE CONTROL FOR ALL OUTPUTS",
        [_input("profile", "COMBO", widget=True)],
        [_output("export_config", "H3_MASTER_EXPORT_CONFIG"),
         _output("status", "STRING")],
        ["HIGH QUALITY"], {"profile": "HIGH QUALITY"}, size=(520, 150))
    return {
        "audio": audio, "transition": transition, "video": video,
        "policy": policy, "gate": gate, "audio_router": audio_router,
        "existing_video": existing_video, "source_target": source_target,
        "export_profile": export_profile,
    }


def _master_export(g: Graph, title: str, filename: str) -> dict[str, Any]:
    return g.new(
        "MiniMaxH3MasterExport", title,
        [_input("manifest", "H3_CHAIN_MANIFEST"), _input("video_vae", "VAE"),
         _input("export_config", "H3_MASTER_EXPORT_CONFIG"),
         _input("filename", "STRING", widget=True),
         _input("source_audio", "AUDIO", optional=True)],
        [_output("video", "VIDEO"), _output("video_path", "STRING"),
         _output("status", "STRING")],
        [filename], {"filename": filename}, size=(620, 220))


def _note(g: Graph, title: str, text: str) -> dict[str, Any]:
    return g.new(
        "Note", title, [], [], [text], {"text": text},
        size=(700, 300), core=True)


def _bounds(nodes: Iterable[dict[str, Any]], margin: int = 80) -> list[int]:
    values = list(nodes)
    if not values:
        return [0, 0, 500, 300]
    x1 = min(float(n["pos"][0]) for n in values) - margin
    y1 = min(float(n["pos"][1]) for n in values) - margin
    x2 = max(float(n["pos"][0]) + float(n["size"][0]) for n in values) + margin
    y2 = max(float(n["pos"][1]) + float(n["size"][1]) for n in values) + margin
    return [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]


def _pack(nodes: list[dict[str, Any]], x0: int, y0: int,
          columns: int = 2, gap_x: int = 100, gap_y: int = 80) -> None:
    if not nodes:
        return
    columns = max(1, int(columns))
    col_width = max(int(n.get("size", [360, 160])[0]) for n in nodes) + gap_x
    ys = [y0 for _ in range(columns)]
    for index, node in enumerate(nodes):
        col = min(range(columns), key=lambda c: ys[c])
        node["pos"] = [x0 + col * col_width, ys[col]]
        ys[col] += int(node.get("size", [360, 160])[1]) + gap_y


def _group(title: str, nodes: list[dict[str, Any]], color: str) -> dict[str, Any]:
    return {
        "id": title.lower().replace(" ", "_").replace("/", "_")[:64],
        "title": title,
        "bounding": _bounds(nodes),
        "color": color,
        "font_size": 24,
        "flags": {},
    }


def _overlap(a: dict[str, Any], b: dict[str, Any], gap: int = 10) -> bool:
    ax, ay = map(float, a.get("pos", (0, 0)))
    aw, ah = map(float, a.get("size", (0, 0)))
    bx, by = map(float, b.get("pos", (0, 0)))
    bw, bh = map(float, b.get("size", (0, 0)))
    return not (
        ax + aw + gap <= bx or bx + bw + gap <= ax or
        ay + ah + gap <= by or by + bh + gap <= ay)


def _validate(g: Graph) -> list[str]:
    errors: list[str] = []
    ids = [int(n["id"]) for n in g.nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate node ids")
    link_ids = [int(link[0]) for link in g.links]
    if len(link_ids) != len(set(link_ids)):
        errors.append("duplicate link ids")
    node_map = {int(n["id"]): n for n in g.nodes}
    for link in g.links:
        if not isinstance(link, list) or len(link) < 6:
            errors.append("malformed link %r" % (link,))
            continue
        lid, oid, oslot, tid, tslot, _typ = link[:6]
        origin = node_map.get(int(oid))
        target = node_map.get(int(tid))
        if origin is None or target is None:
            errors.append("link %s points to missing node" % lid)
            continue
        if int(oslot) >= len(origin.get("outputs", [])):
            errors.append("link %s origin slot missing" % lid)
            continue
        if int(tslot) >= len(target.get("inputs", [])):
            errors.append("link %s target slot missing" % lid)
            continue
        if int(lid) not in (origin["outputs"][int(oslot)].get("links") or []):
            errors.append("link %s missing from origin output metadata" % lid)
        if target["inputs"][int(tslot)].get("link") != int(lid):
            errors.append("link %s missing from target input metadata" % lid)

    expected = {
        "MiniMaxH3MasterPictureReferenceSlot": 9,
        "MiniMaxH3MasterVideoReferenceSlot": 3,
        "MiniMaxH3MasterAudioReferenceSlot": 3,
        "MiniMaxH3MasterAudioMode": 1,
        "MiniMaxH3MasterTransitionMode": 1,
        "MiniMaxH3MasterVideoMode": 1,
        "MiniMaxH3MasterExportProfile": 1,
    }
    for typ, count in expected.items():
        actual = len(g.all(typ))
        if actual != count:
            errors.append("%s count=%d expected=%d" % (typ, actual, count))
    stale = [n for n in g.nodes if n.get("type") in OLD_REFERENCE_TYPES]
    if stale:
        errors.append("stale legacy reference nodes remain: %s" %
                      [n.get("id") for n in stale])

    try:
        ref2va = g.one("MiniMaxH3TaggedReferenceToVideo")
        last_audio = g.all("MiniMaxH3MasterAudioReferenceSlot")[-1]
        origin = g.origin_for_input(ref2va, "references")
        if origin is None or int(origin[0]["id"]) != int(last_audio["id"]):
            errors.append("Ref2VA references are not fed by final master ref slot")
        plan = g.one("MiniMaxH3ChainPlan")
        policy = g.one("MiniMaxH3MasterChainPolicyRouter")
        origin = g.origin_for_input(plan, "chain_policy")
        if origin is None or int(origin[0]["id"]) != int(policy["id"]):
            errors.append("Plan chain_policy is not fed by internal master policy router")
        loop_start = g.one("MiniMaxH3ChainLoopStart")
        gate = g.one("MiniMaxH3MasterSourceAudioGate")
        origin = g.origin_for_input(loop_start, "source_audio")
        if origin is None or int(origin[0]["id"]) != int(gate["id"]):
            errors.append("Loop Start source_audio is not gated")
        loop_trim = next((n for n in g.nodes if n.get("type") == "MiniMaxH3LoopTrim"), None)
        audio_router = g.one("MiniMaxH3MasterAudioRouter")
        if loop_trim is not None:
            origin = g.origin_for_input(loop_trim, "audio")
            if origin is None or int(origin[0]["id"]) != int(audio_router["id"]):
                errors.append("Loop Trim audio is not fed by Master Audio Router")
        context = g.one("MiniMaxH3ChainContext")
        source_target = g.one("MiniMaxH3MasterSourceVideoTarget")
        origin = g.origin_for_input(context, "latent")
        if origin is None or int(origin[0]["id"]) != int(source_target["id"]):
            errors.append("Chain Context latent does not pass through Source Video Edit")
    except (WorkflowError, IndexError) as exc:
        errors.append(str(exc))

    visible = [n for n in g.nodes if n.get("type") != "Reroute"]
    for index, node in enumerate(visible):
        for other in visible[index + 1:]:
            if _overlap(node, other):
                errors.append("node overlap: %s(%s) / %s(%s)" % (
                    node.get("title", node.get("type")), node.get("id"),
                    other.get("title", other.get("type")), other.get("id")))
                if len(errors) > 30:
                    return errors
    return errors


def migrate(workflow: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out = copy.deepcopy(workflow)
    g = Graph(out)

    # Authoritative role discovery: nine exact loader bindings must exist.
    image_loaders: list[dict[str, Any]] = []
    for number in range(1, 10):
        binding = "h3-ref-slot-%02d" % number
        matches = [n for n in g.nodes if _binding_id(n) == binding]
        if len(matches) != 1 or matches[0].get("type") != "LoadImage":
            raise WorkflowError(
                "Authoritative workflow must contain exactly one LoadImage binding %s; found %d"
                % (binding, len(matches)))
        image_loaders.append(matches[0])

    ref2va = g.one("MiniMaxH3TaggedReferenceToVideo")
    plan = g.one("MiniMaxH3ChainPlan")
    loop_start = g.one("MiniMaxH3ChainLoopStart")
    current = g.one("MiniMaxH3ChainCurrent")
    context = g.one("MiniMaxH3ChainContext")
    loop_end = g.one("MiniMaxH3ChainLoopEnd")
    dec_audio = g.one("VAEDecodeAudio")
    trim_nodes = [n for n in g.nodes if n.get("type") == "MiniMaxH3LoopTrim"]
    if len(trim_nodes) != 1:
        raise WorkflowError("Expected one MiniMaxH3LoopTrim; found %d" % len(trim_nodes))
    loop_trim = trim_nodes[0]

    video_vae_origin = g.origin_for_input(ref2va, "vae")
    if video_vae_origin is None:
        raise WorkflowError("Ref2VA video VAE input is not connected")
    video_vae, video_vae_slot, video_vae_type = video_vae_origin
    latent_origin = g.origin_for_input(context, "latent")
    if latent_origin is None:
        raise WorkflowError("Chain Context latent input is not connected")

    # Delete demo notes and all legacy tagged/scheduled source nodes. Loaders are
    # retained or recreated below; Plan Studio/Prompt Editor/Review/Resume remain.
    for node in list(g.nodes):
        if node.get("type") == "Note" or node.get("type") in OLD_REFERENCE_TYPES:
            g.remove_node(node)
    for node in list(g.nodes):
        if node.get("type") == "MiniMaxH3ChainPolicy":
            g.remove_node(node)

    # Clear the nine real image loaders and make the bank generic.
    for number, loader in enumerate(image_loaders, 1):
        g.clear_output_links(loader, 0)
        loader["title"] = "IMAGE REF %d — LOAD IMAGE" % number
        _clear_loader(loader, "image")
        loader["color"] = "#744c8c"
        loader["bgcolor"] = "rgba(24,24,27,.9)"

    source_audio_candidates = [
        n for n in g.nodes
        if n.get("type") == "LoadAudio" and _binding_id(n) == "h3-source-audio-01"]
    if not source_audio_candidates:
        source_audio_candidates = [n for n in g.nodes if n.get("type") == "LoadAudio"]
    if source_audio_candidates:
        source_audio = source_audio_candidates[0]
        g.clear_output_links(source_audio, 0)
        source_audio["title"] = "SOURCE / EXTERNAL AUDIO"
        _set_binding(source_audio, "h3-source-audio-01")
        _clear_loader(source_audio, "audio")
    else:
        source_audio = _load_audio(g, "SOURCE / EXTERNAL AUDIO", "h3-source-audio-01")

    # New permanent banks: 9 picture slots, 3 native VIDEO slots, 3 audio refs.
    previous: dict[str, Any] | None = None
    picture_slots: list[dict[str, Any]] = []
    for number, loader in enumerate(image_loaders, 1):
        slot = _picture_slot(g, number)
        picture_slots.append(slot)
        g.connect_names(loader, "IMAGE", slot, "image", "IMAGE")
        if previous is not None:
            g.connect_names(previous, "references", slot, "previous",
                            "H3_TAGGED_REFERENCES")
        previous = slot

    video_loaders: list[dict[str, Any]] = []
    video_slots: list[dict[str, Any]] = []
    for number in range(1, 4):
        loader = _load_video(
            g, "VIDEO REF %d — LOAD VIDEO" % number,
            "h3-video-ref-%02d" % number)
        slot = _video_slot(g, number)
        video_loaders.append(loader)
        video_slots.append(slot)
        g.connect_names(loader, "video", slot, "video", "VIDEO")
        assert previous is not None
        g.connect_names(previous, "references", slot, "previous",
                        "H3_TAGGED_REFERENCES")
        previous = slot

    audio_loaders: list[dict[str, Any]] = []
    audio_slots: list[dict[str, Any]] = []
    for number in range(1, 4):
        loader = _load_audio(
            g, "AUDIO REF %d — LOAD AUDIO" % number,
            "h3-audio-ref-%02d" % number)
        slot = _audio_slot(g, number)
        audio_loaders.append(loader)
        audio_slots.append(slot)
        g.connect_names(loader, "AUDIO", slot, "audio", "AUDIO")
        assert previous is not None
        g.connect_names(previous, "references", slot, "previous",
                        "H3_TAGGED_REFERENCES")
        previous = slot

    assert previous is not None
    g.connect_names(previous, "references", ref2va, "references",
                    "H3_TAGGED_REFERENCES")
    if any(inp.get("name") == "generation_fingerprint" for inp in plan.get("inputs", [])):
        g.connect_names(previous, "reference_fingerprint", plan,
                        "generation_fingerprint", "STRING")

    source_video = _load_video(g, "SOURCE VIDEO", "h3-source-video-01")
    modes = _mode_nodes(g)

    # One Audio Mode + one Continuation Mode -> hidden canonical H3 Chain Policy.
    g.connect_names(modes["audio"], "audio_control", modes["policy"],
                    "audio_control", "H3_MASTER_AUDIO_CONTROL")
    g.connect_names(modes["transition"], "transition_control", modes["policy"],
                    "transition_control", "H3_MASTER_TRANSITION_CONTROL")
    g.connect_names(modes["policy"], "chain_policy", plan, "chain_policy",
                    "H3_CHAIN_POLICY")

    # Source audio is lazy at Loop Start and can be independently requested by
    # the final-audio mixer. No audio-reference node can become Source Timeline.
    g.connect_names(modes["audio"], "audio_control", modes["gate"],
                    "audio_control", "H3_MASTER_AUDIO_CONTROL")
    g.connect_names(source_audio, "AUDIO", modes["gate"], "source_audio", "AUDIO")
    g.connect_names(modes["gate"], "source_audio", loop_start, "source_audio", "AUDIO")
    g.connect_names(current, "state", modes["audio_router"], "state", "H3_CHAIN_STATE")
    g.connect_names(modes["audio"], "audio_control", modes["audio_router"],
                    "audio_control", "H3_MASTER_AUDIO_CONTROL")
    if any(out.get("name") == "source_audio_slice" for out in current.get("outputs", [])):
        g.connect_names(current, "source_audio_slice", modes["audio_router"],
                        "source_audio", "AUDIO")
    g.connect_names(dec_audio, "AUDIO", modes["audio_router"],
                    "generated_audio", "AUDIO")
    g.connect_names(source_audio, "AUDIO", modes["audio_router"],
                    "external_audio", "AUDIO")
    g.connect_names(modes["audio_router"], "audio", loop_trim, "audio", "AUDIO")

    # Source-video mode stays independent from audio mode. Existing video is
    # lazy continuation context; edit mode inserts picture target before Chain Context.
    plan_origin = g.origin_for_input(loop_start, "plan")
    if plan_origin is None:
        plan_origin = (plan, g.output_index(plan, "plan"), "H3_CHAIN_PLAN")
    g.connect(plan_origin[0], plan_origin[1], modes["existing_video"],
              g.input_index(modes["existing_video"], "plan"), "H3_CHAIN_PLAN")
    g.connect_names(modes["video"], "video_control", modes["existing_video"],
                    "video_control", "H3_MASTER_VIDEO_CONTROL")
    g.connect_names(source_video, "video", modes["existing_video"],
                    "source_video", "VIDEO")
    if any(inp.get("name") == "external_context" for inp in loop_start.get("inputs", [])):
        g.connect_names(modes["existing_video"], "external_context", loop_start,
                        "external_context", "H3_EXTERNAL_CONTEXT")

    # Re-resolve original latent origin because removing legacy refs did not touch it.
    latent_origin = g.origin_for_input(context, "latent") or latent_origin
    g.disconnect_input(context, "latent")
    g.connect(latent_origin[0], latent_origin[1], modes["source_target"],
              g.input_index(modes["source_target"], "latent"), "LATENT")
    g.connect_names(current, "state", modes["source_target"], "state", "H3_CHAIN_STATE")
    g.connect(video_vae, video_vae_slot, modes["source_target"],
              g.input_index(modes["source_target"], "vae"), video_vae_type)
    g.connect_names(modes["video"], "video_control", modes["source_target"],
                    "video_control", "H3_MASTER_VIDEO_CONTROL")
    g.connect_names(source_video, "video", modes["source_target"],
                    "source_video", "VIDEO")
    g.connect_names(modes["source_target"], "latent", context, "latent", "LATENT")

    # Neutralize project-specific Plan payload while preserving every technical
    # Plan widget not explicitly changed here.
    generic_plan = json.dumps({
        "shots": [
            {"id": "intro", "prompt": "Describe the opening shot."},
            {"id": "continuation", "prompt": "Continue the same take."},
        ]
    }, ensure_ascii=False, indent=2)
    _set_widget(plan, "plan_json", generic_plan)
    _set_widget(plan, "run_name", "h3_master")
    plan["title"] = "MASTER PLAN"

    # Run Manager keeps all loader bindings without evaluating media.
    run_managers = g.all("MiniMaxH3ChainRunManager")
    binding_records: list[dict[str, Any]] = []
    assets: list[tuple[dict[str, Any], str, str, str]] = []
    for number, loader in enumerate(image_loaders, 1):
        assets.append((loader, "h3-ref-slot-%02d" % number, "picture", "image"))
    for number, loader in enumerate(video_loaders, 1):
        assets.append((loader, "h3-video-ref-%02d" % number, "video", "file"))
    for number, loader in enumerate(audio_loaders, 1):
        assets.append((loader, "h3-audio-ref-%02d" % number, "audio_reference", "audio"))
    assets += [
        (source_video, "h3-source-video-01", "source_track", "file"),
        (source_audio, "h3-source-audio-01", "source_track", "audio"),
    ]
    for loader, binding, role, widget_name in assets:
        binding_records.append({
            "binding_id": binding,
            "label": loader["title"],
            "role": role,
            "node_id": str(loader["id"]),
            "node_type": loader["type"],
            "node_title": loader["title"],
            "output_slot": 0,
            "output_type": loader["outputs"][0]["type"],
            "widget_name": widget_name,
            "original_value": "",
        })
    for manager in run_managers:
        # Remove stale asset_* graph links/inputs but preserve Plan and current
        # required/optional interface fields from this exact workflow version.
        for item in list(manager.get("inputs", [])):
            if str(item.get("name", "")).startswith("asset_"):
                if item.get("link") is not None:
                    g.remove_link(int(item["link"]))
                manager["inputs"].remove(item)
        insert_at = 1 if manager.get("inputs") else 0
        for index, (loader, _binding, _role, _widget) in enumerate(assets):
            manager["inputs"].insert(
                insert_at + index,
                _input("asset_%d" % index, "*", optional=True,
                       label="%d: %s" % (index, loader["title"])))
            g.connect(loader, 0, manager, insert_at + index, "*")
        manager.setdefault("properties", {})["h3_asset_roles"] = {
            binding: role for _loader, binding, role, _widget in assets}
        _set_widget(manager, "archive_images", True)
        _set_widget(manager, "archive_audio", True)
        _set_widget(manager, "archive_video", True)
        _set_widget(manager, "asset_bindings_json", json.dumps(
            binding_records, ensure_ascii=False, separators=(",", ":")))
        manager["title"] = "RUN MANAGER — MASTER ASSETS / RESTORE"
        if any(inp.get("name") == "tagged_references" for inp in manager.get("inputs", [])):
            g.connect_names(previous, "references", manager, "tagged_references",
                            "H3_TAGGED_REFERENCES")

    # One shared export profile fans out to normal Loop End and every recovery
    # manifest loader. Old stream-copy Assemble nodes are retained but muted so
    # recovery/resume functionality is not deleted or silently invoked.
    main_export = _master_export(g, "FINAL MASTER EXPORT", "master")
    g.connect_names(loop_end, "manifest", main_export, "manifest", "H3_CHAIN_MANIFEST")
    g.connect(video_vae, video_vae_slot, main_export,
              g.input_index(main_export, "video_vae"), video_vae_type)
    g.connect_names(modes["export_profile"], "export_config", main_export,
                    "export_config", "H3_MASTER_EXPORT_CONFIG")
    g.connect_names(source_audio, "AUDIO", main_export, "source_audio", "AUDIO")

    recovery_exports: list[dict[str, Any]] = []
    for number, manifest_load in enumerate(g.all("MiniMaxH3ChainManifestLoad"), 1):
        export = _master_export(
            g, "RECOVERY MASTER EXPORT %d" % number,
            "recovery_master_%d" % number)
        recovery_exports.append(export)
        g.connect_names(manifest_load, "manifest", export, "manifest", "H3_CHAIN_MANIFEST")
        g.connect(video_vae, video_vae_slot, export,
                  g.input_index(export, "video_vae"), video_vae_type)
        g.connect_names(modes["export_profile"], "export_config", export,
                        "export_config", "H3_MASTER_EXPORT_CONFIG")
        g.connect_names(source_audio, "AUDIO", export, "source_audio", "AUDIO")
    for assemble in g.all("MiniMaxH3ChainAssemble"):
        assemble["mode"] = 4
        assemble["title"] = "LEGACY STREAM-COPY ASSEMBLY — MUTED"

    quick_note = _note(
        g, "MASTER WORKFLOW — QUICK START",
        "1. Pick only the IMAGE / VIDEO / AUDIO refs you need and switch each slot ON.\n"
        "2. Use @image_ref_N / @video_ref_N / @audio_ref_N in scene prompts.\n"
        "3. CONTINUATION MODE controls Guide / Masked AV / Soft AV / Cut.\n"
        "4. SOURCE VIDEO MODE is independent from AUDIO MODE.\n"
        "5. AUDIO MODE is one choice; references are always standalone and never become Source Timeline.\n"
        "6. EXPORT PROFILE is shared by normal and recovery master outputs.\n\n"
        "Exact Final Timeline hidden raw tail is not allowed to borrow media from the next delivered scene."
    )
    status_note = _note(
        g, "VALIDATION STATUS",
        "Generated by tools/build_master_workflow.py from the supplied Default H3.json.\n"
        "Static graph/link/slot/layout validation passed at build time.\n"
        "Runtime status remains INCONCLUSIVE until tested in the actual ComfyUI installation."
    )

    # Deterministic non-overlapping layout by functional zones. Existing useful
    # nodes are preserved and repacked; Reroutes stay with the generation core.
    categories: dict[str, list[dict[str, Any]]] = {name: [] for name in GROUP_ORDER}
    refs_set = {int(n["id"]) for n in image_loaders + picture_slots}
    vrefs_set = {int(n["id"]) for n in video_loaders + video_slots}
    arefs_set = {int(n["id"]) for n in audio_loaders + audio_slots}
    source_set = {int(source_audio["id"]), int(source_video["id"])}
    control_set = {int(n["id"]) for n in modes.values() if n is not modes["export_profile"]}
    output_set = {int(modes["export_profile"]["id"]), int(main_export["id"]),
                  int(quick_note["id"]), int(status_note["id"])}
    recovery_set = {int(n["id"]) for n in recovery_exports}
    plan_types = {
        "MiniMaxH3ChainPlan", "MiniMaxH3ChainPlanStudio",
        "MiniMaxH3ChainRunManager", "MiniMaxH3ChainRichScenePromptEditor",
        "MiniMaxH3ChainScenePromptEditor", "ResolutionSelector",
    }
    review_types = {
        "MiniMaxH3ChainSegmentSave", "MiniMaxH3ChainReview",
        "MiniMaxH3ChainLoopEnd", "MiniMaxH3SecondPassSwitch",
        "MiniMaxH3ChainFinalizeSecondPass",
    }
    recovery_types = {"MiniMaxH3ChainManifestLoad", "MiniMaxH3ChainAssemble"}
    model_ids = {int(n["id"]) for n in g.nodes if n.get("type") in (
        "UNETLoader", "CLIPLoader", "VAELoader")}
    for node in g.nodes:
        nid = int(node["id"])
        typ = str(node.get("type"))
        if nid in refs_set:
            group = GROUP_ORDER[1]
        elif nid in vrefs_set:
            group = GROUP_ORDER[2]
        elif nid in arefs_set:
            group = GROUP_ORDER[3]
        elif nid in source_set:
            group = GROUP_ORDER[4]
        elif nid in control_set:
            group = GROUP_ORDER[5]
        elif nid in output_set:
            group = GROUP_ORDER[9]
        elif nid in recovery_set or typ in recovery_types:
            group = GROUP_ORDER[10]
        elif nid in model_ids:
            group = GROUP_ORDER[0]
        elif typ in plan_types:
            group = GROUP_ORDER[6]
        elif typ in review_types:
            group = GROUP_ORDER[8]
        else:
            group = GROUP_ORDER[7]
        categories[group].append(node)

    placements = {
        GROUP_ORDER[0]: (-7800, -1200, 1),
        GROUP_ORDER[1]: (-6600, 0, 3),
        GROUP_ORDER[2]: (-6600, 2600, 3),
        GROUP_ORDER[3]: (-6600, 3700, 3),
        GROUP_ORDER[4]: (-3000, -1200, 1),
        GROUP_ORDER[5]: (-1900, -1200, 2),
        GROUP_ORDER[6]: (0, -1200, 2),
        GROUP_ORDER[7]: (2600, -1200, 3),
        GROUP_ORDER[8]: (6000, -1200, 2),
        GROUP_ORDER[9]: (8400, -1200, 1),
        GROUP_ORDER[10]: (8400, 1700, 2),
    }
    for title in GROUP_ORDER:
        x, y, cols = placements[title]
        _pack(sorted(categories[title], key=lambda n: int(n.get("order", 0))),
              x, y, columns=cols)

    colors = [
        "#364152", "#5b3f78", "#355e6b", "#6b4d35", "#65404b",
        "#6b5420", "#3f4e68", "#315f46", "#3f4e2f", "#245d68", "#7a552b",
    ]
    out["groups"] = [
        _group(title, categories[title], colors[index])
        for index, title in enumerate(GROUP_ORDER) if categories[title]
    ]
    # LiteGraph serializes group ids as numeric values. Keep them stable and
    # deterministic instead of deriving ids from titles.
    for group_id, group in enumerate(out["groups"], 1):
        group["id"] = group_id

    g.finish()
    errors = _validate(g)
    if errors:
        raise WorkflowError(
            "Master workflow validation failed:\n- " + "\n- ".join(errors))
    report = {
        "status": "STRUCTURE VERIFIED / RUNTIME INCONCLUSIVE",
        "nodes": len(g.nodes),
        "links": len(g.links),
        "picture_refs": len(picture_slots),
        "video_refs": len(video_slots),
        "audio_refs": len(audio_slots),
        "recovery_master_exports": len(recovery_exports),
        "source_audio_lazy": True,
        "source_video_audio_independent": True,
        "shared_export_profile": True,
    }
    return out, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Authoritative Default H3.json")
    parser.add_argument("--output", help="Output workflow path")
    parser.add_argument("--report", help="Optional JSON validation report path")
    args = parser.parse_args(argv)
    source = Path(args.input)
    if not source.is_file():
        raise SystemExit("Input workflow not found: %s" % source)
    output = Path(args.output) if args.output else source.with_name(
        source.stem + " - MASTER.json")
    with source.open("r", encoding="utf-8-sig") as handle:
        workflow = json.load(handle)
    migrated, report = migrate(workflow)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(migrated, handle, ensure_ascii=False, indent=2)
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
