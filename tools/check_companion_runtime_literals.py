#!/usr/bin/env python3
"""Standalone regression test for companion runtime node-id literal rewriting."""

from __future__ import annotations

import importlib.util
import sys
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


ns = load_module(
    "companion_namespace_runtime_literal_test",
    ROOT / "companion_namespace.py",
)

owned = {
    "MiniMaxH3ChainPlan",
    "MiniMaxH3ChainPlanStudio",
    "MiniMaxH3ChainCurrent",
}
ns.register_owned_node_ids(owned)

package_name = "fake_master_companion_package"
module_name = package_name + ".runtime"
old_package = sys.modules.get(package_name)
old_module = sys.modules.get(module_name)

package = types.ModuleType(package_name)
package.__path__ = []
module = types.ModuleType(module_name)
module.__package__ = package_name
sys.modules[package_name] = package
sys.modules[module_name] = module

source = '''
def probe(value):
    if value == "MiniMaxH3ChainPlan":
        return ("MiniMaxH3ChainCurrent", "KSampler")
    return None

class Holder:
    @staticmethod
    def accepts(value):
        return value in ("MiniMaxH3ChainPlanStudio", "VAEDecode")

    @classmethod
    def current(cls):
        return "MiniMaxH3ChainCurrent"
'''
exec(compile(source, "<fake-companion-runtime>", "exec"), module.__dict__)

try:
    assert module.probe("MiniMaxH3ChainPlan") == (
        "MiniMaxH3ChainCurrent", "KSampler")
    assert module.Holder.accepts("MiniMaxH3ChainPlanStudio") is True
    assert module.Holder.current() == "MiniMaxH3ChainCurrent"

    rewritten = ns.rewrite_package_node_id_literals(package_name)
    assert rewritten >= 4, rewritten

    plan = ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlan"
    studio = ns.NODE_ID_PREFIX + "MiniMaxH3ChainPlanStudio"
    current = ns.NODE_ID_PREFIX + "MiniMaxH3ChainCurrent"

    assert module.probe(plan) == (current, "KSampler")
    assert module.probe("MiniMaxH3ChainPlan") is None
    assert module.Holder.accepts(studio) is True
    assert module.Holder.accepts("MiniMaxH3ChainPlanStudio") is False
    assert module.Holder.accepts("VAEDecode") is True
    assert module.Holder.current() == current

    # Running the rewrite twice is safe: already namespaced constants are not
    # in the original owned-id set, so the second pass changes nothing.
    assert ns.rewrite_package_node_id_literals(package_name) == 0
finally:
    if old_package is None:
        sys.modules.pop(package_name, None)
    else:
        sys.modules[package_name] = old_package
    if old_module is None:
        sys.modules.pop(module_name, None)
    else:
        sys.modules[module_name] = old_module

print("MASTER COMPANION RUNTIME LITERAL CHECK: OK")
print("rewritten_literals=%d" % rewritten)
