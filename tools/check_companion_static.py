#!/usr/bin/env python3
"""Standalone checks for the independent MASTER companion namespace.

Runs without ComfyUI, torch, aiohttp or any model files.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ns = load_module("companion_namespace_static_test", ROOT / "companion_namespace.py")
migrator = load_module(
    "companion_migrator_static_test", ROOT / "tools" / "migrate_workflow_to_companion.py")


# Public node ids are mechanically disjoint. Include an overlapping pair to
# protect the single-pass browser rewrite from double-prefix regressions.
owned = {
    "MiniMaxH3ChainPlan",
    "MiniMaxH3ChainPlanStudio",
    "MiniMaxH3ChainCurrent",
    "MiniMaxH3MasterAudioMode",
}
ns.register_owned_node_ids(owned)
classes = {key: object() for key in owned}
namespaced = ns.namespace_node_mappings(classes)
assert set(namespaced).isdisjoint(owned)
assert set(namespaced) == {ns.NODE_ID_PREFIX + value for value in owned}
assert ns.companion_node_id("MiniMaxH3ChainPlan") == ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan"
assert ns.companion_node_id("KSampler") == "KSampler"
assert ns.companion_node_id(ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan") == (
    ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan")


# PromptServer facade rewrites only this pack's route/event namespace.
class FakeRoutes:
    def __init__(self):
        self.paths = []

    def post(self, path):
        self.paths.append(path)
        return lambda fn: fn


class FakePromptInstance:
    def __init__(self):
        self.routes = FakeRoutes()
        self.sent = []
        self.client_id = "client"

    def send_sync(self, event, *args, **kwargs):
        self.sent.append((event, args, kwargs))
        return event


class FakePromptServer:
    instance = FakePromptInstance()


facade = ns._PromptServerFacade(FakePromptServer)
facade.instance.routes.post("/minimax_h3_context_loop/review")
assert FakePromptServer.instance.routes.paths == [
    "/drmacabre_h3_master_context_loop/review"]
facade.instance.send_sync("minimax_h3_context_loop_review", {"ok": True})
assert FakePromptServer.instance.sent[0][0] == "drmacabre_h3_master_context_loop_review"


# Import shims are temporary globally, while captured GraphBuilder behavior is
# permanently companion-aware inside modules that import it during the window.
old_server = sys.modules.get("server")
old_comfy_execution = sys.modules.get("comfy_execution")
old_graph_utils = sys.modules.get("comfy_execution.graph_utils")

server_module = types.ModuleType("server")
server_module.PromptServer = FakePromptServer
sys.modules["server"] = server_module

comfy_execution_module = types.ModuleType("comfy_execution")
graph_utils_module = types.ModuleType("comfy_execution.graph_utils")


class FakeGraphBuilder:
    def __init__(self):
        self.calls = []

    def node(self, class_type, *args, **kwargs):
        self.calls.append((class_type, args, kwargs))
        return class_type


graph_utils_module.GraphBuilder = FakeGraphBuilder
comfy_execution_module.graph_utils = graph_utils_module
sys.modules["comfy_execution"] = comfy_execution_module
sys.modules["comfy_execution.graph_utils"] = graph_utils_module

try:
    ns.register_owned_node_ids(owned)
    state = ns.install_import_shims()
    captured_builder = graph_utils_module.GraphBuilder
    assert captured_builder is not FakeGraphBuilder
    builder = captured_builder()
    assert builder.node("MiniMaxH3ChainPlan", "x") == (
        ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan")
    assert builder.node("KSampler", "y") == "KSampler"
    captured_prompt_server = server_module.PromptServer
    assert captured_prompt_server is not FakePromptServer
    ns.restore_import_shims(state)
    assert graph_utils_module.GraphBuilder is FakeGraphBuilder
    assert server_module.PromptServer is FakePromptServer
    # The captured facade still delegates to the real fake server after restore.
    captured_prompt_server.instance.send_sync("minimax_h3_context_loop_probe", {})
    assert FakePromptServer.instance.sent[-1][0] == (
        "drmacabre_h3_master_context_loop_probe")
finally:
    if old_server is None:
        sys.modules.pop("server", None)
    else:
        sys.modules["server"] = old_server
    if old_comfy_execution is None:
        sys.modules.pop("comfy_execution", None)
    else:
        sys.modules["comfy_execution"] = old_comfy_execution
    if old_graph_utils is None:
        sys.modules.pop("comfy_execution.graph_utils", None)
    else:
        sys.modules["comfy_execution.graph_utils"] = old_graph_utils


# Frontend generation rewrites node ids, API/events, extension tokens, and the
# MASTER DOM/style namespaces that would otherwise alter legacy UI.
with tempfile.TemporaryDirectory() as temp_dir:
    package = Path(temp_dir)
    web = package / "web"
    web.mkdir()
    sample = web / "sample.js"
    sample.write_text(
        'const A="MiniMaxH3ChainPlan";\n'
        'const B="MiniMaxH3ChainPlanStudio";\n'
        'const U="/minimax_h3_context_loop/review";\n'
        'const E="minimax_h3_context_loop_review";\n'
        'const X="minimaxH3.master";\n'
        'const C="h3studio h3c-audio";\n'
        'const S="h3-chain-plan-editor-style h3-plan-studio-style";\n',
        encoding="utf-8")
    generated = ns.prepare_companion_web_directory(package, owned)
    assert generated == "./.web_master_companion"
    output = (package / ".web_master_companion" / "sample.js").read_text(
        encoding="utf-8")
    assert ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan" in output
    assert ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlanStudio" in output
    assert (ns.NODE_ID_PREFIX + ns.NODE_ID_PREFIX) not in output
    assert "/drmacabre_h3_master_context_loop/review" in output
    assert "drmacabre_h3_master_context_loop_review" in output
    assert "drmacabreH3Master.master" in output
    assert "dmh3studio" in output
    assert "dmh3c-audio" in output
    assert "dmh3-chain-plan-editor-style" in output
    assert "dmh3-plan-studio-style" in output
    # Cached second call must remain valid and deterministic.
    assert ns.prepare_companion_web_directory(package, owned) == generated


# The workflow migrator discovers literal source mappings without importing the
# Comfy package, then rewrites only type/class_type fields owned by this tree.
discovered = migrator.discover_owned_node_ids(ROOT)
assert "MiniMaxH3ChainPlan" in discovered
assert "MiniMaxH3ChainCurrent" in discovered
assert "MiniMaxH3MasterAudioMode" in discovered
assert len(discovered) >= 20

stats = {"rewritten": 0}
workflow = {
    "nodes": [
        {"id": 1, "type": "MiniMaxH3ChainPlan"},
        {"id": 2, "type": "KSampler"},
    ],
    "prompt": {
        "3": {"class_type": "MiniMaxH3MasterAudioMode"},
        "4": {"class_type": "VAEDecode"},
    },
}
migrated = migrator.migrate_value(workflow, discovered, stats)
assert migrated["nodes"][0]["type"] == ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan"
assert migrated["nodes"][1]["type"] == "KSampler"
assert migrated["prompt"]["3"]["class_type"] == (
    ns.NODE_ID_PREFIX + "MiniMaxH3MasterAudioMode")
assert migrated["prompt"]["4"]["class_type"] == "VAEDecode"
assert stats["rewritten"] == 2
leftovers = []
migrator.remaining_legacy_types(migrated, discovered, leftovers)
assert leftovers == []


# Syntax-only checks for the entrypoint and tools; importing __init__.py here
# would require a full ComfyUI runtime, which is intentionally outside this test.
for path in [
    ROOT / "__init__.py",
    ROOT / "companion_namespace.py",
    ROOT / "tools" / "migrate_workflow_to_companion.py",
]:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

print("MASTER COMPANION STATIC CHECKS: OK")
print("discovered_owned_node_ids=%d" % len(discovered))
