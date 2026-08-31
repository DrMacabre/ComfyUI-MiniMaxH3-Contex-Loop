#!/usr/bin/env python3
"""Static regression checks for MASTER's no-shared-core-patch contract."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
entry = (ROOT / "__init__.py").read_text(encoding="utf-8")
entry_tree = ast.parse(entry, filename="__init__.py")
policy = (ROOT / "companion_runtime_policy.py").read_text(encoding="utf-8")
masking = (ROOT / "masking_support.py").read_text(encoding="utf-8")
legacy_widget = (ROOT / "web" / "h3_legacy_widget_width_fix.js").read_text(
    encoding="utf-8")


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return (parent + "." if parent else "") + node.attr
    return ""


# Import-time tokenizer compatibility would mutate the shared ComfyUI MiniMax
# module and therefore influence Ethan's pack. Inspect executable syntax rather
# than raw text so an explanatory comment cannot trip the regression check.
for node in ast.walk(entry_tree):
    if isinstance(node, ast.Import):
        assert all("tokenizer_compat" not in alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        assert "tokenizer_compat" not in str(node.module or "")
        assert all(alias.name != "install_minimax_tokenizer_compat"
                   for alias in node.names)
    elif isinstance(node, ast.Call):
        assert not dotted_name(node.func).endswith(
            "install_minimax_tokenizer_compat")
assert "require_native_minimax_tokenizer" in entry

# The companion must replace legacy H3 guide fallbacks before chain_nodes is
# imported, so chain_nodes captures native-only functions.
policy_pos = entry.index("_install_native_only_guide_policy(")
chain_pos = entry.index("from .chain_nodes import")
assert policy_pos < chain_pos
assert "apply_layout_patch" not in policy
assert "apply_payload_patch" not in policy
assert "claim_layout_patch_ownership" not in policy
assert "claim_payload_patch_ownership" not in policy
assert "native_guides_available" in policy

# Masked paths may inspect the compatibility modules but may never install their
# process-global wrappers from the companion.
assert "ensure_h3_mask_compat" not in masking
assert "ensure_av_mask_payload_compat" not in masking
assert "native_av_mask_payload" in masking
assert "mask_engine_native" in masking
assert "mask_helpers_native" in masking

# The old canvas-wide widget hook is owned only by Ethan's pack.
assert "globalThis.LGraphNode" not in legacy_widget
assert "legacyWidgetWidthFix" not in legacy_widget
assert "LegacyWidgetWidthFixDisabled" in legacy_widget

print("MASTER COMPANION NO-GLOBAL-PATCH CHECKS: OK")
