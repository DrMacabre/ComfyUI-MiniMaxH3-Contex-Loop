"""Runtime namespace isolation for the DrMacabre MiniMax H3 MASTER companion pack.

The companion is a complete copy of the H3 runtime, but it must be able to live
next to Ethan's legacy pack inside one ordinary ComfyUI process.  This module
keeps that separation mechanical and centralized:

* every public Comfy node id exported by this package receives a unique prefix;
* runtime code literals and GraphBuilder calls target those private ids;
* PromptServer routes/events captured by this package receive a private API
  namespace while the real global PromptServer object is restored immediately
  after package import;
* the browser bundle is generated from this package's own ``web`` directory
  with the same node/API namespace rewrite, so it never targets Ethan's nodes.

Nothing here imports, edits, or monkeypatches an installed Ethan nodepack.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import types
from pathlib import Path
from typing import Any, Iterable, Mapping


NODE_ID_PREFIX = "DrMacabreH3Master_"
SOURCE_RUNTIME_TOKEN = "minimax_h3"
COMPANION_RUNTIME_TOKEN = "drmacabre_h3_master"
SOURCE_CAMEL_TOKEN = "minimaxH3"
COMPANION_CAMEL_TOKEN = "drmacabreH3Master"
WEB_SOURCE_DIRECTORY = "web"
WEB_COMPANION_DIRECTORY = ".web_master_companion"
WEB_SIGNATURE_FILE = ".companion-signature"

_owned_original_node_ids: frozenset[str] = frozenset()


def register_owned_node_ids(node_ids: Iterable[str]) -> frozenset[str]:
    """Publish the exact original ids owned by this package copy."""
    global _owned_original_node_ids
    _owned_original_node_ids = frozenset(str(value) for value in node_ids)
    return _owned_original_node_ids


def companion_node_id(class_type: Any) -> Any:
    """Rewrite one package-owned public node id and leave everything else alone."""
    if not isinstance(class_type, str):
        return class_type
    if class_type.startswith(NODE_ID_PREFIX):
        return class_type
    if class_type in _owned_original_node_ids:
        return NODE_ID_PREFIX + class_type
    return class_type


def namespace_node_mappings(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a collision-free public mapping for ComfyUI registration."""
    result: dict[str, Any] = {}
    for original_id, node_class in mapping.items():
        public_id = NODE_ID_PREFIX + str(original_id)
        if public_id in result:
            raise RuntimeError("Duplicate MASTER companion node id %r." % public_id)
        result[public_id] = node_class
    return result


def namespace_display_mappings(
        class_mapping: Mapping[str, Any],
        display_mapping: Mapping[str, str]) -> dict[str, str]:
    """Prefix display labels as well as machine ids so the two packs are obvious."""
    return {
        NODE_ID_PREFIX + str(original_id): "MASTER · %s" %
        str(display_mapping.get(original_id, original_id))
        for original_id in class_mapping
    }


def _rewrite_runtime_token(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.replace(SOURCE_RUNTIME_TOKEN, COMPANION_RUNTIME_TOKEN)


class _RoutesFacade:
    def __init__(self, routes: Any):
        self._routes = routes

    def __getattr__(self, name: str):
        attribute = getattr(self._routes, name)
        if not callable(attribute):
            return attribute

        def wrapped(*args, **kwargs):
            if args and isinstance(args[0], str):
                args = (_rewrite_runtime_token(args[0]), *args[1:])
            return attribute(*args, **kwargs)

        return wrapped


class _PromptServerInstanceFacade:
    def __init__(self, instance: Any):
        self._instance = instance

    @property
    def routes(self):
        return _RoutesFacade(self._instance.routes)

    def send_sync(self, event: Any, *args, **kwargs):
        return self._instance.send_sync(
            _rewrite_runtime_token(event), *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._instance, name)


class _PromptServerFacade:
    """Package-local view of PromptServer with namespaced routes/events."""

    def __init__(self, real_prompt_server: Any):
        self._real_prompt_server = real_prompt_server

    @property
    def instance(self):
        instance = getattr(self._real_prompt_server, "instance", None)
        if instance is None:
            return None
        return _PromptServerInstanceFacade(instance)

    def __getattr__(self, name: str):
        return getattr(self._real_prompt_server, name)


def install_import_shims() -> dict[str, Any]:
    """Temporarily expose package-local facades while our modules import.

    Modules using ``from server import PromptServer`` or
    ``from comfy_execution.graph_utils import GraphBuilder`` capture the facade
    into their own module namespace.  The real global module attributes are
    restored by :func:`restore_import_shims` as soon as this package finishes
    importing, so no other custom node sees these shims.
    """
    state: dict[str, Any] = {}

    try:
        import server  # type: ignore
    except Exception:
        server = None
    if server is not None and hasattr(server, "PromptServer"):
        real_prompt_server = server.PromptServer
        state["server_module"] = server
        state["prompt_server"] = real_prompt_server
        server.PromptServer = _PromptServerFacade(real_prompt_server)

    try:
        import comfy_execution.graph_utils as graph_utils  # type: ignore
    except Exception:
        graph_utils = None
    if graph_utils is not None and hasattr(graph_utils, "GraphBuilder"):
        real_graph_builder = graph_utils.GraphBuilder
        state["graph_utils_module"] = graph_utils
        state["graph_builder"] = real_graph_builder

        class CompanionGraphBuilder(real_graph_builder):
            def node(self, class_type, *args, **kwargs):
                return super().node(
                    companion_node_id(class_type), *args, **kwargs)

        CompanionGraphBuilder.__name__ = "DrMacabreH3MasterGraphBuilder"
        graph_utils.GraphBuilder = CompanionGraphBuilder

    return state


def restore_import_shims(state: Mapping[str, Any]) -> None:
    """Restore the real global ComfyUI objects after our imports complete."""
    server = state.get("server_module")
    if server is not None and "prompt_server" in state:
        server.PromptServer = state["prompt_server"]

    graph_utils = state.get("graph_utils_module")
    if graph_utils is not None and "graph_builder" in state:
        graph_utils.GraphBuilder = state["graph_builder"]


def _rewrite_code_constant(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        rewritten = companion_node_id(value)
        return rewritten, int(rewritten != value)
    if isinstance(value, types.CodeType):
        return _rewrite_code_object(value)
    if isinstance(value, tuple):
        total = 0
        rewritten_items = []
        for item in value:
            rewritten, count = _rewrite_code_constant(item)
            rewritten_items.append(rewritten)
            total += count
        return tuple(rewritten_items), total
    if isinstance(value, frozenset):
        total = 0
        rewritten_items = []
        for item in value:
            rewritten, count = _rewrite_code_constant(item)
            rewritten_items.append(rewritten)
            total += count
        return frozenset(rewritten_items), total
    return value, 0


def _rewrite_code_object(code: types.CodeType) -> tuple[types.CodeType, int]:
    total = 0
    constants = []
    for value in code.co_consts:
        rewritten, count = _rewrite_code_constant(value)
        constants.append(rewritten)
        total += count
    if total:
        code = code.replace(co_consts=tuple(constants))
    return code, total


def _rewrite_function_node_literals(function: Any, seen: set[int]) -> int:
    if not isinstance(function, types.FunctionType):
        return 0
    identity = id(function)
    if identity in seen:
        return 0
    seen.add(identity)
    code, count = _rewrite_code_object(function.__code__)
    if count:
        function.__code__ = code
    return count


def rewrite_package_node_id_literals(package_name: str) -> int:
    """Rewrite exact package-owned node-id literals in loaded companion code.

    Saved workflow ``class_type`` values use the public namespaced ids.  The
    inherited runtime still contains a few exact string comparisons such as
    ``MiniMaxH3ChainLoopStart`` / ``MiniMaxH3ChainPlan``.  Rewriting only exact
    constants after imports keeps those comparisons and explicit GraphBuilder
    calls private without editing Ethan's source tree or registering aliases.
    Mapping-dictionary keys are already materialized data and are deliberately
    left unchanged as the internal/original id registry.
    """
    prefix = str(package_name) + "."
    modules = [
        module for name, module in tuple(sys.modules.items())
        if module is not None and (name == package_name or name.startswith(prefix))
    ]
    seen: set[int] = set()
    total = 0

    for module in modules:
        for value in tuple(vars(module).values()):
            if isinstance(value, types.FunctionType):
                if str(getattr(value, "__module__", "")).startswith(package_name):
                    total += _rewrite_function_node_literals(value, seen)
                continue
            if not isinstance(value, type):
                continue
            if not str(getattr(value, "__module__", "")).startswith(package_name):
                continue
            for descriptor in tuple(vars(value).values()):
                functions = []
                if isinstance(descriptor, types.FunctionType):
                    functions.append(descriptor)
                elif isinstance(descriptor, (staticmethod, classmethod)):
                    functions.append(descriptor.__func__)
                elif isinstance(descriptor, property):
                    functions.extend(
                        item for item in (descriptor.fget, descriptor.fset, descriptor.fdel)
                        if item is not None)
                for function in functions:
                    total += _rewrite_function_node_literals(function, seen)

    return total


def _transform_web_text(text: str, original_node_ids: Iterable[str]) -> str:
    # One regex substitution is essential here: replacement text still contains
    # the original id, so a sequence of str.replace calls could double-prefix a
    # longer id when a shorter owned id is processed later.
    node_ids = sorted(
        {str(value) for value in original_node_ids if str(value)},
        key=len, reverse=True)
    if node_ids:
        pattern = re.compile("|".join(re.escape(value) for value in node_ids))
        text = pattern.sub(lambda match: NODE_ID_PREFIX + match.group(0), text)

    # REST endpoints, websocket event names and extension ids all share this token.
    text = text.replace(SOURCE_RUNTIME_TOKEN, COMPANION_RUNTIME_TOKEN)
    text = text.replace(SOURCE_CAMEL_TOKEN, COMPANION_CAMEL_TOKEN)

    # The MASTER simplification stylesheet intentionally changes Plan Studio and
    # Scene Plan presentation. Give those DOM namespaces private prefixes so its
    # CSS cannot hide controls on Ethan's legacy nodes in the same browser.
    text = text.replace("h3studio", "dmh3studio")
    text = text.replace("h3c-", "dmh3c-")
    text = text.replace("h3c ", "dmh3c ")
    text = text.replace("h3c\"", "dmh3c\"")
    text = text.replace("h3c'", "dmh3c'")

    # Style element ids and other hyphenated frontend-only ids are also private.
    # Web module filenames use underscores (h3_*.js), so this does not rewrite
    # import paths or the source file layout.
    text = text.replace("h3-", "dmh3-")
    return text


def _web_signature(source: Path, original_node_ids: Iterable[str]) -> str:
    digest = hashlib.sha256()
    digest.update(NODE_ID_PREFIX.encode("utf-8"))
    digest.update(COMPANION_RUNTIME_TOKEN.encode("utf-8"))
    for node_id in sorted(str(value) for value in original_node_ids):
        digest.update(node_id.encode("utf-8"))
        digest.update(b"\0")
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare_companion_web_directory(
        package_directory: str | os.PathLike[str],
        original_node_ids: Iterable[str]) -> str:
    """Build a private frontend bundle from this package's own web sources."""
    package = Path(package_directory)
    source = package / WEB_SOURCE_DIRECTORY
    target = package / WEB_COMPANION_DIRECTORY
    marker = target / WEB_SIGNATURE_FILE

    if not source.is_dir():
        raise RuntimeError("MASTER companion web source directory is missing: %s" % source)

    node_ids = tuple(str(value) for value in original_node_ids)
    signature = _web_signature(source, node_ids)
    if target.is_dir() and marker.is_file():
        try:
            if marker.read_text(encoding="utf-8").strip() == signature:
                return "./" + WEB_COMPANION_DIRECTORY
        except OSError:
            pass

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    text_suffixes = {".js", ".mjs", ".css", ".html", ".json"}
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        target_path = target / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.suffix.lower() in text_suffixes:
            text = source_path.read_text(encoding="utf-8")
            target_path.write_text(
                _transform_web_text(text, node_ids), encoding="utf-8")
        else:
            shutil.copy2(source_path, target_path)

    marker.write_text(signature + "\n", encoding="utf-8")
    return "./" + WEB_COMPANION_DIRECTORY


__all__ = [
    "NODE_ID_PREFIX",
    "register_owned_node_ids",
    "companion_node_id",
    "namespace_node_mappings",
    "namespace_display_mappings",
    "install_import_shims",
    "restore_import_shims",
    "rewrite_package_node_id_literals",
    "prepare_companion_web_directory",
]
