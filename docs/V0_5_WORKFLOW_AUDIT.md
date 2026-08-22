# Version 0.5 workflow audit

Audit date: 2026-08-22

Audited base: `feature/0.5-workflow-ux` at `4aceb9d`

## Result

All maintained 0.5 workflow graphs pass the repository's topology, contract,
timing, migration, and mocked-runtime validation. No dangling or mismatched
serialized links were found. Maintained examples open on the compact control
surface; advanced and experimental settings remain available only after an
explicit disclosure.

The audit found one stale regression fixture: Segment Save's reference-cache
lookup now needs the Plan canvas width and height, but the minimal segment-
revision test Plan omitted them. The fixture now supplies the same geometry a
normalized runtime Plan always contains, and the regression passes.

## Workflow coverage

- 17 maintained JSON workflows and 9 archived JSON workflows have valid,
  bidirectional serialized link records.
- Every maintained recursive workflow uses one-wire Chain Policy and the 0.5
  Plan contract. Normal workflows route through model-free Preflight; Studio
  workflows use Plan Studio's equivalent preflight surface.
- Current Shot state is the authoritative input to Loop Trim. Maintained
  workflows do not use the stale Plan or Current Shot blend-integer outputs;
  overlap images are wired to Segment Save where blending is supported.
- Chain Context's target latent reaches the sampler input in every applicable
  recursive generation workflow. Masked-editing graphs additionally preserve
  their target/mask composition path.
- The sequential motion-reference example routes source video and embedded
  audio through Reference Video Prep, Tagged Video Ref, scene-aware Ref2VA,
  Patch Priority, and Chain Context; its reference fingerprint reaches Plan.
- Source Timeline audio reaches Loop Start, Studio, recovery, preview, tagged
  references, and assembly consumers without duplicate legacy full-track
  wiring.
- Deferred learned-H3 and whole-chain SeedVR2 workflows consume Checkpoint
  Manager's selected immutable lineage and keep their first-pass Plan and loop
  dependencies out of the finishing graph.

## Regression coverage

The complete local suite passed:

```bash
for test_file in tests/_*_test.py; do python "$test_file" || exit 1; done
for test_file in tests/_*_test.mjs; do node "$test_file" || exit 1; done
```

This executes 40 Python and 21 JavaScript test programs. Coverage includes
motion-context guides, all transition recipes, source/reference audio timing,
masked AV and masking, checkpoint/revision recovery, resume dependency guards,
review and assembly, workflow migration, browser presentation, and both
deferred-upscale paths.

## Validation boundary

This is a static, contract, mocked-runtime, and media-assembly audit. A live H3
render still depends on a current ComfyUI installation, compatible models and
VAEs, available GPU memory, and the selected input media. Run the workflow's
Preflight node inside that target ComfyUI environment before sampling.
