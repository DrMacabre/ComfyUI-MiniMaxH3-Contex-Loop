# MASTER development isolation contract

This branch is the continuation point for the experimental `Default H3 - MASTER` work.

## Hard isolation rule

The installed legacy pack used by existing workflows must remain pinned to commit `0d79a0922c4be5cc97e93b4e169287fd9ba93d4a` (`fool-for-love-upstream-0.6.37`) until a later legacy change is explicitly validated.

MASTER development must not replace or patch that installed legacy package in place.

## Local layout

- Active legacy package: `ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-Contex-Loop`
- MASTER development worktree/copy: outside `ComfyUI/custom_nodes`, under a dedicated MASTER development directory.
- Only one experimental MASTER package may be activated for a dedicated MASTER runtime test, and it must never overwrite the legacy worktree.

## Compatibility requirement

Existing workflow node ids and runtime behavior are a protected compatibility surface. Experimental MASTER overlays such as generated-audio tail/boundary assembly and export verification must not be installed as unconditional import-time patches on the legacy package.

The final MASTER architecture must either:

1. use a companion/custom-node package with unique MASTER node ids and no mutation of legacy module globals; or
2. use a separately activated runtime profile/worktree that never co-loads or overwrites the legacy package.

Until companion isolation is complete and tested, use option 2.

## Regression gate

Before any MASTER change is promoted into the normal node pack, representative pre-MASTER workflows must load and queue without new validation/runtime errors. MASTER-only success is insufficient.
