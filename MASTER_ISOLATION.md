# MASTER independent nodepack contract

This branch is the continuation point for the experimental `Default H3 - MASTER` work and now implements the selected companion-pack architecture.

## Hard isolation rule

The installed legacy pack used by existing workflows remains a separate compatibility surface and must not be overwritten or patched in place by MASTER development.

Target normal ComfyUI layout:

- `ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-Contex-Loop` — Ethan/legacy pack for existing workflows.
- `ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-MASTER` — DrMacabre MASTER companion pack.

Both are intended to load in the user's ordinary ComfyUI process. A second ComfyUI profile/port is not the target architecture.

## Companion isolation mechanics

The MASTER companion keeps its own copy of the runtime and does not import Ethan's installed package.

- Public Comfy node ids are exported with the unique `DrMacabreH3Master_` prefix.
- Package-local GraphBuilder calls rewrite only node ids owned by the MASTER copy.
- Package-local PromptServer routes and websocket events use the `drmacabre_h3_master` namespace.
- The browser bundle is generated from the MASTER package's own `web/` sources and rewritten to target only MASTER node ids/routes/events.
- MASTER Plan Studio / Scene Plan DOM namespaces are separated where the simplified MASTER UI would otherwise alter legacy controls.
- Exact-timeline / generated-audio / export overlays patch the MASTER package's local modules, not Ethan's installed module objects.

## Workflow migration

`tools/migrate_workflow_to_companion.py` rewrites saved MASTER workflow `type` / `class_type` fields only when they exactly match node ids owned by this source tree. Generic ComfyUI nodes are left untouched.

The migration tool writes a separate `*-MASTER-COMPANION.json` by default; `--in-place` makes a timestamped backup first.

## Regression gate

Before the companion is considered runtime-valid:

1. Ethan's legacy pack and the MASTER companion must co-load in one normal ComfyUI startup without duplicate node/API/extension registration failures.
2. A representative pre-MASTER workflow must still load and queue with the legacy pack.
3. The migrated MASTER workflow must load with `DrMacabreH3Master_*` node types and queue through its own runtime.
4. The controlled MASTER audio-reference test must be rerun only after those coexistence checks pass.

Current runtime status: **INCONCLUSIVE** until installed-side coexistence and render tests are performed.
