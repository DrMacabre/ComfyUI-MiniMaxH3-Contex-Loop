<p align="center">
  <img src="assets/minimax-h3-contex-loop.svg" alt="MiniMax H3 Contex Loop v0.5 — scene plans that survive the render" width="100%">
</p>

# ComfyUI MiniMax H3 Contex Loop

Build a multi-scene MiniMax H3 video with one reusable sampling body. Review
each scene, retry when needed, resume after interruption, and assemble the
accepted scenes without keeping the whole production in memory.

[Quick start](#quick-start) · [Choose a workflow](#choose-a-workflow) ·
[Feature map](#feature-map) · [Documentation](#documentation) ·
[Feature origins](docs/FEATURE_TRACEABILITY.md) · [Changelog](CHANGELOG.md)

> **Version 0.5 status:** this README describes `feature/0.5-workflow-ux`.
> Saved 0.4 workflows and checkpoints remain supported. See
> [Migrating to 0.5](docs/MIGRATING_TO_0_5.md).

> **Contex** is the intentional public repository spelling.

## What can it do?

| Goal | What this pack provides |
|---|---|
| Make a longer story | A visual scene Plan drives one recursive H3 graph. |
| Keep motion and sound connected | Choose clean Guide continuity or protected AV-prefix transitions. |
| Direct each scene | Use per-scene prompts, seeds, timing, pictures, motion video, and audio references. |
| Work from existing footage | Continue a clip, follow a source timeline, inpaint selected regions, or bridge two endpoints. |
| Iterate safely | Review, edit and retry, reroll, stop early, or resume from atomic checkpoints. |
| Recover the production | Restore Plans and assets, assemble partial runs, or re-decode saved latents to PNG. |

The maintained workflows cover **T2V, I2V, FL2V, and Ref2V**, plus masked
video editing and AV extension. Start from an example rather than constructing
the recursive graph by hand.

## Quick start

### 1. Install

From `ComfyUI/custom_nodes`:

```bash
git clone --branch feature/0.5-workflow-ux \
  https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop.git
```

Restart ComfyUI and reload the browser.

Version 0.5 expects a current ComfyUI build with the native **Add Guide for
MiniMax H3** implementation from
[ComfyUI PR #15439](https://github.com/Comfy-Org/ComfyUI/pull/15439). An
`ffmpeg` executable on `PATH` is preferred; ComfyUI's bundled PyAV is used for
review and assembly when FFmpeg is unavailable.

The model files used by the example graphs are not bundled. ComfyUI will show
missing model selections when an example is opened.

### 2. Open an example

Drag a workflow JSON from [`example_workflows/`](example_workflows/) onto the
ComfyUI canvas. **Normal** workflows use the standard Plan and Scene Prompt
Editor. **Studio** workflows add the optional experimental timeline UI without
changing the generation graph.

Some examples use bundled media. Copy the files identified in
[`example_workflows/assets/README.md`](example_workflows/assets/README.md) to
`ComfyUI/input/` before running them.

### 3. Run the Plan

1. Give the Plan a unique `run_name`.
2. Edit its scene prompts and confirm the selected Audio and Transition
   policies.
3. Queue the workflow. Preflight reports missing media, invalid timing,
   incompatible continuation settings, or unsafe resume state before H3 loads.
4. At Review Gate, approve, retry with an edited prompt, reroll the seed, or
   approve and stop.
5. Assemble the completed or partial manifest. Existing MP4 files are never
   overwritten; the pack adds `_001`, `_002`, and so on.

Good first settings are `960 × 544`, Guide, Generated audio, `video` encode,
`head` anchor, and the workflow's supplied frame counts. H3 dimensions must be
multiples of 32, and scene lengths are normalized to its `17k+5` frame grid.

## Choose a workflow

| I want to… | Start here |
|---|---|
| Generate from text | [T2V Normal](<example_workflows/MiniMax H3 T2V - Normal.json>) |
| Animate an opening image | [I2V Normal](<example_workflows/MiniMax H3 I2V - Normal.json>) |
| Move between indexed first/last images | [FL2V Normal](<example_workflows/MiniMax H3 FL2V - Normal.json>) |
| Use prompt-driven pictures | [Ref2V Tagged](<example_workflows/MiniMax H3 Ref2V - Tagged.json>) |
| Author on the Studio timeline | [T2V Studio](<example_workflows/MiniMax H3 T2V - Studio.json>), [I2V Studio](<example_workflows/MiniMax H3 I2V - Studio.json>), or [Ref2V Studio Tagged](<example_workflows/MiniMax H3 Ref2V - Studio Tagged.json>) |
| Guide scenes with a source soundtrack | [Ref2V Studio Tagged Source Audio](<example_workflows/MiniMax H3 Ref2V - Studio Tagged Source Audio.json>) |
| Inpaint a fixed or tracked region | [Masked Video Inpaint](<example_workflows/MiniMax H3 - Masked Video Inpaint.json>) |
| Continue an existing clip | [Masked AV Extension — Single Clip](<example_workflows/MiniMax H3 - Masked AV Extension - Single Clip.json>) |
| Build a reviewed multi-scene extension | [Masked AV Extension — Chain + Reference Image](<example_workflows/MiniMax H3 - Masked AV Extension - Chain + Reference Image.json>) |
| Generate the gap between two clips | [Two-Clip Masked AV Bridge](<example_workflows/MiniMax H3 - Masked AV Bridge - Two Clips.json>) |

The [complete workflow catalog](example_workflows/README.md) explains required
assets, graph topology, expected timing, experimental status, and prompt/media
credits. Retired and legacy examples remain under `example_workflows/Archive/`.

## How the loop works

```text
Audio Policy ─┐
Transition ───┼→ Plan → Preflight → Loop Start → Current Shot
Source Timeline┘                                  ↓
                                           H3 conditioning
                                                  ↓
                                      sample → decode → trim
                                                  ↓
                                checkpoint → review → Loop End ──↺

Loop End manifest → Assemble
```

Only one scene travels through the sampling body at a time. The accepted
predecessor supplies the next scene's continuity context; completed media and
recovery metadata live on disk.

## Choose continuity

The Transition Policy describes the boundary **entering** a scene.

| Transition | Carries into the next scene | Use when |
|---|---|---|
| **Cut** | Nothing | The next scene should start independently. |
| **Guide** | 22 clean RGB/VAE frames | You want the default, broadly compatible motion handoff. |
| **Tone Carry Guide** | Guide plus a saved boundary-tone correction | You are testing automatic color/tone continuity. Experimental. |
| **Latent Guide** | 22 sampled video-latent guide frames | You want to avoid the generated RGB → VAE round trip. Opt-in. |
| **Detail Guide** | A disposable tapered chroma-noise Guide | You are testing identity/detail recovery. Experimental. |
| **Hard AV** | Exact protected 39-frame picture prefix and optional audio | You need strict AV-prefix continuity. |
| **Soft AV** | Exact picture plus an eight-tick generated-audio release | You want the recommended AV-mask handoff. |
| **Detail AV** | Disposable tapered-noise Hard AV picture prefix | You are comparing the experimental 39-frame latent-noise recipe. |

AV-mask transitions require `video` encode, `head` anchor, and an exact shared
video/audio boundary. Start with 39 context frames. Details, supported expert
lengths, and upstream origins are in
[Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) and the
[feature traceability matrix](docs/FEATURE_TRACEABILITY.md).

## Choose audio behavior

Audio Policy keeps three decisions independent:

| Decision | Choices | Controls |
|---|---|---|
| Final audio | Generated / Source / None | What Assemble places in the final MP4. |
| Source reference | On / Off | Whether the current source window guides H3. |
| Generated continuity | On / Off | Whether the preceding sampled audio latent enters the next scene. |

Register long source media once with **Source Timeline**. Current Shot decodes
only the active scene window, while the saved manifest retains enough
information for recovery and final assembly. See
[Audio and continuity](docs/AUDIO_AND_CONTINUITY.md).

## Feature map

| If you need… | Use | Read |
|---|---|---|
| Clear scene-by-scene authoring | Plan + Scene Prompt Editor | [Scene authoring](docs/SCENE_AUTHORING.md) |
| Pictures, motion, or audio only when named | Tagged refs with `@tags` | [Scheduled and tagged references](docs/SCHEDULED_REFERENCES.md) |
| Timed semantic picture reinforcement | `#picture[time]` anchors | [Semantic anchors](docs/SCHEDULED_REFERENCES.md#tagged-semantic-picture-anchors) |
| Long file-backed source media | Source Timeline | [Source Timeline wiring](docs/AUDIO_AND_CONTINUITY.md#source-timeline-wiring) |
| Inpaint, outpaint, tracked masks, or a clip bridge | Masking nodes | [Masked editing](docs/MASKED_EDITING.md) |
| Review, retries, resume, and partial assembly | Review Gate + Run Manager | [Runs and recovery](docs/RUNS_AND_RECOVERY.md) |
| Existing-video continuation or long context | Existing Video Context | [Advanced workflows](docs/ADVANCED_WORKFLOWS.md) |
| Older 0.4 graphs | Legacy policy adapter or unchanged saved widgets | [Migration guide](docs/MIGRATING_TO_0_5.md) |
| Why a feature exists and where it came from | Origin and implementation evidence | [Feature traceability](docs/FEATURE_TRACEABILITY.md) |

### Masked editing in one paragraph

The masking route can align source picture and sound to the loop's exact H3
target, slice a static or tracked mask for the current scene, preview H3's
effective 32×32 source-pixel cells, and compose the spatial edit with an
existing AV-prefix mask. Apply Target Mask defaults to exact H3 causal/token
conversion, preserving thin and moving selections that temporal interpolation
can weaken. Ordinary AV extension creates its own temporal mask and does not
need a user-supplied one.

### References in one paragraph

Register stable aliases such as `@hero`, `@performance`, and `@voice`, then
mention only the media needed by each scene. Tagged Ref2VA compiles active
aliases to native H3 media labels. Tagged Motion Ref can transfer performance
without asking H3 to inherit source identity or setting; semantic picture
anchors add optional Qwen-only checkpoints. Numeric scene schedules remain as
a compatibility and explicit-control route.

## Compatibility notes

- NikoDemon80's upstream H3 Motion Context pack is optional and can be
  installed beside this one; public node IDs are kept separate.
- Current ComfyUI handles native guide placement and per-token AV masking. The
  AV-mask compatibility path activates lazily only on older supported builds.
- Known H3-Multishot and SolAttn wrappers are preserved. Unknown layout or
  payload wrappers stop with an actionable compatibility error.
- Release-versioned frontend imports reduce stale-browser-module problems
  after updates.

See [Compatibility](docs/COMPATIBILITY.md) for the full matrix.

## Documentation

| Guide | Use it for |
|---|---|
| [Documentation index](docs/README.md) | Find the focused guide for a task. |
| [Workflow catalog](example_workflows/README.md) | Pick an example and prepare its assets. |
| [Scene authoring](docs/SCENE_AUTHORING.md) | Plan, prompts, timing, seeds, and revisions. |
| [References](docs/SCHEDULED_REFERENCES.md) | Tagged media, semantic anchors, schedules, and fingerprints. |
| [Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) | Audio policies, transitions, timing, trimming, and seam analysis. |
| [Masked editing](docs/MASKED_EDITING.md) | Inpaint/outpaint masks, exact cells, source targets, and AV bridges. |
| [Runs and recovery](docs/RUNS_AND_RECOVERY.md) | Review, retries, checkpoints, restoration, and assembly. |
| [Complete Plan format](H3_CHAIN_FORMAT_GUIDE.md) | Full JSON and node-setting reference. |
| [Feature traceability](docs/FEATURE_TRACEABILITY.md) | Original, adapted, inspired, integrated, and compatibility features. |
| [Third-party notices](THIRD_PARTY_NOTICES.md) | Authoritative attribution, revisions, and licenses. |
| [Contributing](CONTRIBUTING.md) | Compatibility rules, provenance requirements, and validation commands. |

## Project history and license

This project began with **NikoDemon80's**
[H3 Motion Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)
and grew into a separate checkpointed production-loop pack so both projects
could coexist. Contributions, upstream adaptations, inspirations, ComfyUI
integrations, and local implementation evidence are mapped in
[Feature traceability](docs/FEATURE_TRACEABILITY.md).

Licensed under GPL-3.0. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
