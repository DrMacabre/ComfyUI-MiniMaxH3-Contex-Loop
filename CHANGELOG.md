# Changelog

Newest first. This file keeps release history out of the onboarding README.

## Unreleased — Experimental authoring interfaces

- Added an optional timeline-oriented Plan Studio without changing the original
  Plan node.
- Added an alternate prompt-only Rich Scene Prompt Editor with color-coded
  reference tokens, outline media icons, image miniatures, hover video/audio
  previews, prompt guides, reversible history, and optional one-click
  Codex/Hermes rewriting through `comfyui-mcp`.
- The original Plan and Scene Prompt Editor remain available and unchanged.

## v0.3.27 — True disabled scheduler compliance

Disabled policy reaches upstream Schedule nodes, converts scheduler-owned
validation into warnings, and omits unusable media. An empty
`source_audio_slice` left wired in `generated_audio` mode no longer stops a
render.

## v0.3.26 — Three-level prompt compliance

Scheduled Ref2VA offers strict, soft, and disabled policy. Strict blocks
scheduler mistakes; soft relaxes prompt-alias failures; disabled passes prompt
text through unchanged and makes scheduler checks non-blocking.

## v0.3.25 — Portable run assets and optional tag warnings

Run Manager accepts dynamic loader-asset connections, records persistent
binding identities and original input paths, and can retain content-addressed
image/audio/video fallbacks under the run folder. Restore prefers the original
input file and materializes an archived fallback only when needed. Scheduled
Ref2VA can downgrade unresolved prompt-tag failures to visible log warnings.

## v0.3.24 — Saved Run Manager

A companion node browses projects under `output/h3_chains`, reports scene and
checkpoint details, and restores archived prompts and Plan settings after
confirmation. Exact API/workflow inputs are preferred, with `plan.json` as the
older-run fallback.

## v0.3.23 — Branching scene-prompt history

The Scene Prompt Editor keeps lazy per-scene revisions outside workflow and
Plan JSON. Its compact `‹ 2 / 5 ›` control navigates versions, shows execution
state and timestamp, and creates a child branch when an executed revision is
edited.

## v0.3.22 — Optional floating reroll control

A ComfyUI setting under **MiniMax H3 Contex Loop → Interface → Cancel &
reroll** can hide the floating in-progress action. Review Gate controls remain
available.

## v0.3.21 — Upstream continuity update and exact assembly

Motion Context preserves a stock H3 `last_frame` target while replacing a
conflicting first-frame anchor with its carried head. Added 56-frame context,
the in-graph Seam Probe, cumulative generated-audio sample budgeting, and
stitcher-ready retained visual overlap. The cumulative-audio approach was
inspired by **seitanism's**
[MultiRef implementation](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef).

## v0.3.20 — Cancel and reroll the active scene

During generation, a guarded floating action can cancel only the active prompt,
assign a new explicit scene seed, preserve the selected range end, and requeue
through ComfyUI's normal queue.

## v0.3.19 — Plan and review UX pass

Plan controls retain pointer input, editor and preview sizes persist, scene
seeds remain visible, and reference menus show only sources active in the
selected scene. Documentation clarifies that `@aliases` are optional.

## v0.3.14 — Explicit compatible patch priority

The optional wired **MiniMax H3 Patch Priority** pass-through can promote this
pack over an older compatible Motion Context copy while retaining recognized
H3-Multishot and SolAttn behavior.

## v0.3.13 — Open a Plan's output folder

A compact **Output** action creates and opens
`output/h3_chains/<run_name>` on the ComfyUI host. Headless hosts fall back to
copying the host path into the browser clipboard.

## v0.3.12 — Clearer Plan guidance and looping I2VA

Expanded Plan tooltips, clarified audio modes and seed rerolls, and added a
single-image I2VA example plus First-Scene Image Gate.

## v0.3.11 — Invisible legacy widget-width repair

While a Contex Loop node is on the canvas, the pack repairs the LiteGraph
widget-width regression across all nodes. Regenerated scenes retain previous
segment and checkpoint revisions instead of deleting the superseded take.

## v0.3.10 — Scene-scheduled Ref2VA

Added chained picture, video, paired-video-audio, and standalone-audio
references under stable `@tags`, with per-scene activation and compact native
label numbering. A right-click converter migrates an already-wired core Ref2VA
node.

## v0.3.8 — One-pass performance re-filming

Reference Video Prep converts native VIDEO or decoded IMAGE/AUDIO to exact
24 fps Ref2VA input, copies its soundtrack without padding or time-stretching,
and powers the experimental three-angle guitar workflow.

## v0.3.7 — Flexible video loaders

Existing Video Context accepts either native ComfyUI VIDEO or separate
IMAGE + AUDIO + FPS outputs.

## v0.3.6 — Extend an existing video

A typed adapter turns decoded video and optional audio into scene 1 context,
with optional normalized-source prepend for partial and final output.

## v0.3.5 — Native guides and portable assembly

Added automatic support for ComfyUI's native arbitrary-position AV guides,
retained the guarded legacy path, and added PyAV fallback when `ffmpeg` is not
available.

## v0.3.4 — Scene Prompt Editor

Added the synchronized large-format scene editor with navigation, reference and
dialogue shortcuts, and adjustable type size.

## v0.3.3 — Reliable preview resizing

Review video sizing remains stable when the ComfyUI canvas is zoomed.

## v0.3.2 — Resizable review video

The bar beneath Review Gate's player adjusts preview height.

## v0.3.1 — Friendlier JSON defaults

Top-level `duration_seconds` and `steps` shorthand populate visual Plan defaults
correctly.

## v0.3.0 — Archival PNG export

Saved scene checkpoints can be re-decoded into a continuous lossless PNG
sequence without holding the complete production in RAM.

## v0.2.0 — Recovery, metadata, and compatibility

- Persisted each scene prompt, effective plan, workflow, and API prompt beside
  the rendered chain.
- Added scene-range rendering, resumable review checkpoints, partial assembly,
  notification/timeout controls, and Firefox-safe Review Gate recovery.
- Added guarded compatibility with H3-Multishot, SolAttn, Ref2VA, and upstream
  H3 Motion Context.
- Added Comfy Registry publishing and a shorter project-focused README.

## v0.1.0 — The production loop takes shape

- Introduced the visual scene-plan editor, multiline prompts, automatic scene
  colors, responsive layout, and collapsible raw JSON.
- Added the recursive one-body chain, frame-locked audio trimming, per-scene
  checkpoints, interactive review/retry, and looping Ref2VA example.
- Renamed the expanded project **MiniMax H3 Contex Loop** so it could coexist
  clearly with NikoDemon80's manual Motion Context tools.

## Origins — Motion Context and Ref2VA continuation

The project began with MiniMax H3 clip chaining and generated-audio
continuation, then added Ref2VA Motion Context, opt-in compatibility patches,
and the resumable disk-backed production loop.
