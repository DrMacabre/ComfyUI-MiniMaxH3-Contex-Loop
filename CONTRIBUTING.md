# Contributing

Focused fixes, workflow improvements, compatibility updates, and documentation
corrections are welcome. Open an issue before a large redesign so its runtime
and saved-workflow compatibility can be discussed first.

## Keep version 0.5 compatible

Version 0.5 preserves saved 0.4 workflows and checkpoints. Unless a change is
explicitly planned as a breaking release:

- do not reuse or rename an existing public node class ID;
- do not reorder existing positional inputs or outputs;
- append new optional inputs and outputs instead of inserting them;
- retain readable legacy widget values and checkpoint formats;
- keep compatible H3-Multishot, SolAttn, and shared patch markers intact.

The frozen rules are documented in
[Version 0.5 architecture](docs/V0_5_ARCHITECTURE.md) and enforced by
`tests/fixtures/v0_4_public_contract.json`.

## Document behavior from evidence

Use the implementation, tests, maintained workflows, and upstream source as
the authority. A user-facing claim should point to a working example or a
specific implementation path. Mark experiments as experimental and describe
their fallback or compatibility behavior.

When a change is derived from another project, update
[Feature traceability](docs/FEATURE_TRACEABILITY.md) and
[Third-party notices](THIRD_PARTY_NOTICES.md) together. Record:

1. the upstream repository and author;
2. the revision or pull request used;
3. the upstream license;
4. the local files that implement the feature;
5. whether the relationship is **adapted**, **inspired**, **integrated**, or
   **compatibility-only**.

Do not describe an integration with an upstream API as copied code, and do not
describe an adaptation as an original implementation.

## Validate a change

Run the focused test for the area you changed. Before release or a broad pull
request, run at least:

```bash
python tests/_node_smoke_test.py
python tests/_chain_smoke_test.py
python tests/_workflow_catalog_unit_test.py
python tests/_v05_contract_unit_test.py
```

Masking, source-timeline, frontend, and migration changes have additional
targeted scripts under `tests/`. JavaScript tests use Node directly, for
example:

```bash
node tests/_plan_editor_js_test.mjs
```

Tests intentionally use mock ComfyUI modules where possible. Real generation
still needs a current ComfyUI installation, H3 models, and appropriate media.

## Keep the README approachable

The README is a workflow chooser and quick start. Put algorithms, complete
node settings, and recovery internals in the focused guides under `docs/`.
Prefer short tables, task-based headings, and links to deeper explanations.

When adding or retiring a maintained workflow, update
`example_workflows/README.md` and `tests/_workflow_catalog_unit_test.py` in the
same change. Keep prompt and media attribution beside the workflow that uses
it.
