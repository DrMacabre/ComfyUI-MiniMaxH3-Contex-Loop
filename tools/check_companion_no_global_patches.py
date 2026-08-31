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
core_compat = (ROOT / "companion_core_compat.py").read_text(encoding="utf-8")
core_tree = ast.parse(core_compat, filename="companion_core_compat.py")
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
# than raw text so explanatory comments cannot trip the regression check.
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
assert "scoped_compat" in policy

# The companion must replace legacy H3 guide fallbacks before chain_nodes is
# imported, so chain_nodes captures native-only functions. Guides are the one
# capability that remains mandatory from shared core on the user's build.
policy_pos = entry.index("_install_native_only_guide_policy(")
chain_pos = entry.index("from .chain_nodes import")
assert policy_pos < chain_pos
assert "apply_layout_patch" not in policy
assert "apply_payload_patch" not in policy
assert "claim_layout_patch_ownership" not in policy
assert "claim_payload_patch_ownership" not in policy
assert "native_guides_available" in policy

# Masked paths may import the private companion implementation but may never
# install the historical process-global wrappers.
assert "ensure_h3_mask_compat" not in masking
assert "ensure_av_mask_payload_compat" not in masking
assert "companion_core_compat" in masking

# Scoped core compatibility must use clone-local facilities. In particular it
# must never assign to a comfy.* attribute/class or replace the global sampler.
assert "set_model_denoise_mask_function" in core_compat
assert 'add_object_patch("__class__"' in core_compat
assert 'add_object_patch("diffusion_model.__class__"' in core_compat
assert "KSamplerX0Inpaint" not in core_compat
assert "install_minimax_tokenizer_compat" not in core_compat
assert "MiniMaxQwenSDTokenizer =" not in core_compat
assert "MiniMaxH3Model._forward =" not in core_compat
assert "MiniMaxH3.extra_conds =" not in core_compat

for node in ast.walk(core_tree):
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target]
        )
        for target in targets:
            name = dotted_name(target)
            assert not name.startswith("comfy."), (
                "companion_core_compat assigns shared core: %s" % name)

# The old canvas-wide widget hook is owned only by Ethan's pack.
assert "globalThis.LGraphNode" not in legacy_widget
assert "legacyWidgetWidthFix" not in legacy_widget
assert "LegacyWidgetWidthFixDisabled" in legacy_widget

print("MASTER COMPANION NO-GLOBAL-PATCH CHECKS: OK")
