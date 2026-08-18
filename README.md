<p align="center">
  <img src="assets/minimax-h3-contex-loop.svg" alt="MiniMax H3 Contex Loop v0.5 — scene plans that survive the render" width="100%">
</p>

# ComfyUI MiniMax H3 Contex Loop

Turn one MiniMax H3 sampling body into a scene-by-scene production loop. Each
accepted scene carries motion and optional audio forward, saves a resumable
checkpoint, can be reviewed or retried, and joins into a final video without a
giant cumulative image tensor.

[Install](#install) · [Choose a workflow](#choose-a-workflow) ·
[Documentation](#documentation) · [Changelog](CHANGELOG.md)

> **Contex** is the intentional public repository spelling.

## What you get

| | Feature |
|---|---|
| 🎬 | Visual multiline scene planner with exact H3 timing |
| 🔁 | One recursive sampling body for a complete scene plan |
| 🧬 | Motion and optional generated-audio continuity |
| 🏷️ | Prompt-driven picture, video, and audio references with stable `@tags` |
| 🗓️ | Optional legacy scene-range scheduling for explicit reference control |
| 👀 | Video-with-sound review, prompt retry, and seed reroll |
| 💾 | Atomic checkpoints, partial assembly, and safe resume |
| 🕘 | Branching prompt history and saved-run restoration |
| 🧭 | Optional Plan Studio and Rich Scene Prompt Editor |
| ⏩ | Existing-video continuation and optional source prepend |
| 🩹 | Native-first spatial/temporal AV masks for video inpainting |
| 🖼️ | Lossless PNG re-decode from saved scene latents |
| 🔬 | In-graph audio-seam diagnostics |
| 🧭 | Model-free preflight with scene-level dependency diffs |

In the default `guide` mode and opt-in `latent_guide` and `tapered_guide`
variants, updated ComfyUI core owns guide placement and reference-payload
merging; this pack does not patch H3. The experimental `masked_av`,
`tapered_av`, and `feathered_av` modes additionally
need the per-stream H3 video/audio noise masks merged into ComfyUI by PR
#15375. Current ComfyUI owns that path natively; older builds lazily receive
the vendored runtime compatibility only when an AV mask mode executes.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop.git
```

Restart ComfyUI and reload the browser. Release-versioned web-module imports
prevent older cached helpers from disabling the Plan editor after an update,
so clearing all browser data should not be necessary. An `ffmpeg` executable
on `PATH` is preferred, but review and final assembly can fall back to
ComfyUI's bundled PyAV when FFmpeg is missing or cannot launch.

Version 0.5 expects a ComfyUI build containing the native **Add Guide for
MiniMax H3** implementation from
[PR #15439](https://github.com/Comfy-Org/ComfyUI/pull/15439). Update ComfyUI
before starting a new v0.5 workflow.

NikoDemon80's upstream H3 Motion Context pack is optional and may be installed
alongside this one for its manual Motion Context, Save Latent, and Load Latent
nodes. H3-Multishot is also supported through guarded payload reuse.

## Choose a workflow

Start with the maintained v0.5 example for your generation mode:

- [T2V — Normal](<example_workflows/MiniMax H3 T2V - Normal.json>) or
  [Studio](<example_workflows/MiniMax H3 T2V - Studio.json>).
- [I2V — Normal](<example_workflows/MiniMax H3 I2V - Normal.json>) or
  [Studio](<example_workflows/MiniMax H3 I2V - Studio.json>).
- [FL2V — indexed A→B→A](<example_workflows/MiniMax H3 FL2V - Normal.json>).
- [Ref2V — Basic](<example_workflows/MiniMax H3 Ref2V - Basic.json>),
  [Tagged](<example_workflows/MiniMax H3 Ref2V - Tagged.json>), or
  [Studio Tagged](<example_workflows/MiniMax H3 Ref2V - Studio Tagged.json>).
  Use [Studio Tagged Source Audio](<example_workflows/MiniMax H3 Ref2V - Studio Tagged Source Audio.json>)
  for the canonical single-wire Source Timeline audio-reference example.
- [Sequential motion reference](<example_workflows/EXPERIMENTAL MiniMax H3 Ref2V - Sequential Motion.json>)
  remains explicitly experimental.
- [Masked video inpaint](<example_workflows/MiniMax H3 - Masked Video Inpaint.json>)
  runs through Chain Loop, frame-locks source picture and sound to the stock
  H3 target, slices static or tracked masks per scene, and regenerates only
  the selected 32px video cells.
- [Masked AV extension — single clip](<example_workflows/MiniMax H3 - Masked AV Extension - Single Clip.json>)
  and [looped Ref2VA chain](<example_workflows/MiniMax H3 - Masked AV Extension - Chain + Reference Image.json>)
  continue the bundled modern CC0 soldier-crab footage with the 0.5 Soft AV
  policy and a full 39-frame visual seam blend.
- [Two-clip masked AV bridge](<example_workflows/MiniMax H3 - Masked AV Bridge - Two Clips.json>)
  protects both source endpoints and generates only the missing interval.

Normal workflows use the stable Plan and Scene Prompt Editor. Studio workflows
add the optional timeline-oriented Plan Studio and Rich Scene Prompt Editor.
See [all example workflows](example_workflows/README.md); retired v2 and
numeric-schedule examples remain available under `example_workflows/Archive/`.

## The loop

```text
Audio Policy ─┐
Transition ───┼→ Plan → Preflight → Loop Start → Current Shot → H3 conditioning
Source Timeline┘                                  ↓
                                           Contex Loop Context
                                                  ↓
                                       sample → decode → Loop Trim
                                                  ↓
                                 Segment + Checkpoint → Review Gate
                                                  ↓
                                              Loop End ──↺

Loop End manifest → Assemble
```

For a first run:

1. Open an example and give the Plan a unique `run_name`.
2. Edit the scene prompts in the Plan or the large Scene Prompt Editor.
3. Choose an Audio Policy and incoming Transition. Register source media once
   with Source Timeline, then connect that descriptor to Preflight (or Plan
   Studio) and Loop Start. Do not repeat the full AUDIO wire downstream.
4. Queue the workflow. Review Gate pauses after every safely saved scene.
5. Approve, edit and retry, reroll the seed, or approve and stop.
6. Assemble the completed or partial manifest.

Existing output files are preserved. Assemble adds `_001`, `_002`, and so on
instead of overwriting an MP4 with the same requested name.

## Essential Plan settings

| Setting | Good starting point | Meaning |
|---|---:|---|
| `width × height` | `960 × 544` | Multiples of 32 |
| Incoming Transition | `Guide (22f)` | Semantic choice into each scene: Cut, Guide, Tone Carry Guide, Latent Guide, Detail Guide, Detail AV, Hard AV, or Soft AV |
| Context | preset-controlled | Advanced overrides can set the exact repeated motion history |
| `encode_mode` | `video` | Preserves motion in the VAE latent |
| `anchor_mode` | `head` | Regenerates then trims the repeated opening context |
| `crop` | `disabled` | Best when source and target framing already agree |
| `default_duration_seconds` | `15` | Rounded up to H3's valid `17k+5` frame grid |
| `default_steps` | `20` | Override per scene when needed |
| `segment_crf` | `18–20` | Lower values produce larger, higher-quality checkpoints |

Use `generation_fingerprint` to record model, VAE, LoRA, references, CFG,
sampler, and scheduler choices that live outside the Plan. Change it when those
dependencies change so incompatible checkpoints cannot be resumed silently.

### Cut, Guide, Tone Carry Guide, Latent Guide, Detail Guide, Detail AV, Hard AV, and Soft AV transitions

The semantic Transition Policy maps `Cut` to no carried picture, `Guide` to
22 RGB/VAE guide frames, experimental `Tone Carry Guide` to the same 22-frame
RGB path with a saved predecessor tone correction, `Latent Guide` to 22 direct
sampled-latent guide frames, experimental `Detail Guide` to a tapered
chroma-noise 22-frame guide,
experimental `Detail AV` to a disposable latent-noise 39-frame picture
prefix, `Hard AV` to a protected 39-frame picture prefix, and `Soft AV` to the same
exact picture prefix with a half-cosine release over the final carried-audio
ticks when Generated continuity is on.
The old Plan `continuation_mode`,
`context_length`, and combined `audio_mode` widgets are hidden from the normal
0.5 interface so they do not compete with the policy nodes. Existing 0.4
workflows still deserialize and execute those saved values unchanged. For a
deliberately old-style graph, use **Legacy 0.4 Policy Adapter** and connect its
two typed outputs to Plan; the node translates the old choices without making
them a second set of controls on Plan.

`guide` leaves the target latent noisy and supplies the previous scene as
fixed conditioning rows. H3 regenerates the repeated head, and Loop Trim
removes it. This remains the default.

`tone_carry_guide` starts as normal RGB Guide. After each generated scene,
Segment Save compares its first four delivered frames with the Guide appearance
it actually received. A coherent small tone step is stored as a capped direct
curve in the checkpoint metadata. If the next scene selects **Tone Carry
Guide**, that curve is applied to its predecessor RGB context before video-VAE
encoding. No curve means an automatic fallback to regular Guide. This mode
intentionally does not use the direct video-latent shortcut; final automatic
tone assembly recognizes the carried boundary and does not grade it twice.

`latent_guide` keeps those same Guide semantics and leaves the new target
latent untouched, but supplies the phase-aligned video tail directly from the
previous scene's saved sampler output. It avoids the decoded RGB → video-VAE
round trip at generated scene boundaries. Imported Existing Video Context, an
incompatible latent geometry, or a missing saved latent automatically uses the
unchanged RGB/VAE Guide path instead. The 22-frame preset requires
`encode_mode=video`; positive expert values must be at least 5 frames.

`tapered_guide` uses the same guide placement and trim, but VAE-encodes a
disposable noisy copy of the predecessor tail. Independent 16px chroma blocks
are blended at 0.30 while preserving source luma, then taper to zero over the
final eight context frames so the last boundary frame remains clean. The
accepted predecessor and its checkpoint remain clean. **Detail Guide** selects
the published 22-frame baseline. Expert override may pair `tapered_guide` with
39 frames or another supported Guide length, but those lengths are
experimental and should be compared against clean Guide with the same seed.

Incoming transition can be overridden per scene in **Show advanced** without
adding another scene-card row. The choice describes the transition **into that
scene**. Scene 1 uses it only when Existing Video Context supplies a
predecessor. Legacy Plan JSON may still set `shots[n].continuation_mode` and
`context_length`; omitting them inherits the Plan defaults.

The same Advanced group has per-scene **Context into scene** and **Audio
context** controls. Blank inherits the corresponding Plan default. Video `0`
starts a visually independent scene; a positive audio value can still carry
dialogue, ambience, or music into that new shot. Explicit audio `0` carries no
preceding generated sound. For scene 1, these control Existing Video Context;
a zero-video-context imported original can still be prepended during assembly.
Independent audio context applies to all Guide variants with generated-audio
continuity. AV mask modes use a positive audio context to carry the matching
shared-clock audio prefix; explicit audio `0`, or Generated continuity off,
keeps the picture prefix but leaves target audio fully denoisable. A paired
motion soundtrack then covers the complete raw target window, while
`source_track` continues to use its exact timeline slice.

`masked_av` writes the previous scene's decoded video tail into the beginning
of the current target video latent and protects it with a `0 = preserve`,
`1 = generate` denoise mask. With Generated continuity on it also copies and
protects the matching previous sampled-audio tail. With that policy off, the
audio target stays fully denoisable so source/reference audio can drive the
entire raw scene. Wire the new **Chain Context latent** output to
the sampler's `latent_image`; the output passes the original target through on
scene 1 and in every Guide mode, so that one wire supports every mode.

`tapered_av`, selected by experimental **Detail AV**, starts from the same
39-frame hard AV prefix, but first makes a disposable copy of its 12 video
latent steps. It blends matched-standard-deviation Gaussian noise at 0.30,
tapering through 0.225, 0.15, and 0.075 to a completely clean final step over
the last four steps. The carried audio
latent and both denoise masks are byte-for-byte the Hard AV path; audio is
never noised. The accepted predecessor checkpoint remains clean, and Loop
Trim removes the complete treated prefix. When assembly blending is enabled,
Segment Save restores clean predecessor RGB in that separate blend artifact,
so the disposable noise cannot leak into the final overlap. The deterministic
noise seed is derived from the scene seed, and the complete recipe is recorded
in the incoming-boundary dependency fingerprint. This implementation adapts
the context-noise recipe published by
[beijinren/ComfyUI-H3-Context-Noise](https://github.com/beijinren/ComfyUI-H3-Context-Noise)
without importing that node pack.

`audio_feathered_av`, selected by **Soft AV**, keeps all 12 video latent steps
exact. When Generated continuity is on, it protects the first 57 of 65 audio
steps and releases only the final 8 audio ticks with a half-cosine ramp. When
continuity is off, it carries no stale audio prefix. This matches the tested
upstream AV extension recipe. The older `feathered_av` implementation remains available
through Expert override: it softens the final four video steps as well as the
audio and is retained as an experimental compatibility option.

All AV mask continuations require `encode_mode=video`, `anchor_mode=head`,
and an exact shared video/audio boundary: **39, 90, 141, 192, or 243 context
frames**. The shortest and normal choice is 39 frames: at 24 fps it is exactly
1.625 seconds and exactly 65 audio-latent steps at H3's 40 Hz audio grid. A
Detail AV v2 transition specifically requires 39 frames. A
per-scene override participates in the Plan/history hashes from that
scene onward, so a checkpoint cannot silently resume under the wrong method.
When modes are mixed, use settings compatible with masked AV for the whole
Plan—normally `context_length=39`, `encode_mode=video`, and `anchor_mode=head`.

### General masked editing

The public **Masking · Loop Source AV Target**, **Masking · Loop Mask Slice**,
**Masking · Trim Source AV**, **Masking · Grid Preview**, and **Masking · Apply
Target Mask** nodes expose the same per-row H3 machinery for video editing.
Loop Source AV Target selects the current scene from Chain state and fits both
VAE encodes to the stock H3 joint target; it does not independently concatenate
LTX video/audio latents. Loop Mask Slice broadcasts a single mask or selects
the matching frames from a complete tracked-mask timeline, including the same
continuation overlap. Existing masks are intersected, so a spatial edit can
compose with the prefix created by either AV mask continuation while
preservation remains authoritative.

The bundled inpaint workflow uses distinct `MiniMaxH3Contex…` node IDs and can
coexist with the earlier standalone PerRowMasking pack. It needs no MODEL patch
node: mask compatibility activates lazily when Apply Target Mask executes.
See [Masked editing](docs/MASKED_EDITING.md) for audio modes, grid behavior,
outpainting preparation, and two-ended clip bridging.

For timeline-driven FL2VA, **Masking · Master Audio + Video Prefix** inserts
the exact current interval from a prerecorded audio timeline into the target
audio latent and protects the complete audio stream. The source can be music,
dialogue, narration, or effects. Clip 1 generates all picture rows; later
clips also protect the preceding decoded-video tail while future picture rows
remain denoisable.

**Masking · Two-Clip AV Bridge** is the complementary two-ended operation. It
places a source tail and destination head into an empty joint AV target,
protects both windows, and denoises only the middle. A 39-frame endpoint is an
exact 65-step video/audio boundary. The bundled CC0 bridge workflow splits one
modern crab clip around a known 114-frame gap so the result can be compared
against the original source timeline.

## Audio at a glance

Audio Policy separates three decisions that the old mode selector combined:

| Axis | Choices | Meaning |
|---|---|---|
| Final audio | Generated / Source / None | What Assemble places in the final MP4 |
| Source reference | On / Off | Whether the exact current source window guides H3 |
| Generated continuity | On / Off | Whether the previous sampled audio latent enters the next scene |

Saved 0.4 modes remain compatible: `generated_audio` maps to
Generated/Off/On, `source_track` to Source/On/Off, and
`source_plus_timeline` to Source/On/On.

For a 362-frame source-audio reference, Current Shot's experimental
`align_audio_reference` switch trims only the Ref2VA slice to **15.070 s**. It
keeps 603 H3 audio steps with a short padded tail and does not modify the full
track used for final assembly.

See [Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) for wiring, generated
WAV preservation, timing behavior, and the Seam Probe.

## Prompt-driven references at a glance

```text
Load Image ─→ Tagged Picture Ref ─┐
24 fps IMAGE (+ paired AUDIO) ─→ Tagged Video Ref ─┐
24 fps motion IMAGE ─→ Tagged Motion Ref ──────────┤
Load Video + Load Audio ─→ Source Timeline ─┬→ Preflight / Plan Studio
                                            └→ Loop Start
Source Timeline ─→ Tagged Motion Ref (Source Timeline) ─────────────────┤
Standalone AUDIO ─→ Tagged Audio Ref ──────────────┴→ Tagged Ref2VA

Current Shot prompt / scene / dimensions / length ───────────────────↗
Current Shot state ──────────────────────────────────────────────────↗
```

Register stable aliases such as `@hero`, `@performance`, and `@voice`, then
mention only the media needed by each scene. Tagged Ref2VA activates those
sources and compiles their aliases to compact native `<Picture N>`, `<Video N>`,
and `<Audio N>` labels. Generic Picture, Video, and Audio refs do not insert
semantic prompt text; the user remains responsible for their definitions.

Tagged pictures also support scene-local semantic anchors such as
`#hero[2.50s]`. The `#` form repeats that picture in Qwen's timed media
presentation without creating another native VAE reference. Use `@hero` for
native Ref2VA identity conditioning, `#hero[...]` for sparse semantic
reinforcement, or both for a character-swap A/B test. Timestamps are
approximate semantic checkpoints within the current scene—not hard frame,
pose, spatial, or continuation locks. See
[Scheduled references](docs/SCHEDULED_REFERENCES.md#tagged-semantic-picture-anchors).

Tagged Ref2VA's **semantic anchor mode** can instead be set to
`picture_storyboard`. In that mode, every referenced tag remains one separate
Qwen-only `<Picture N>` and the compiler adds scene-relative approximate-time
instructions for its `#tag[timestamp]` occurrences. It is useful when several
high-detail stills describe a shot's visual progression. The Pictures are not
VAE encoded, fused, or fixed to exact frames. Anchor resolution is independent
from native `@` references and supports 384, 512, 768, 1024, 1280, or source;
use 1024/1280 selectively because Qwen visual-token cost rises substantially.

Use **Tagged Motion Ref**, rather than generic Tagged Video Ref, when a clip
supplies action instead of appearance or whole-video structure. Its native
media remains `<Video N>`, but its `@tag` compiles to a separate reusable
`<Subject N>` sourced from that Video. The compiler adds the motion-Subject
definition and explicitly transfers only its visible performance to the chosen
target Subject, excluding source identity, wardrobe, setting, lighting, and
composition. By default it also reduces the motion video's short edge to 384
pixels before native Ref2VA encoding, lowering its spatial token pressure while
retaining coarse pose and timing; select `source` for a full-resolution A/B
baseline. The clip is still a native Ref2VA video block, so this is an H3
semantic/low-bandwidth separation rather than a pose extractor or ControlNet.
In `sequential` mode, masked AV scenes advance motion on the delivered output
timeline: the repeated continuation prefix is excluded from the native video
reference and from its paired audio. This prevents H3 from replaying one
context span of motion after the protected prefix. Generic Tagged Video Ref
keeps overlap-inclusive target-window slicing.

For long control videos, **Tagged Motion Ref (Lazy VIDEO/Path)** avoids holding
the complete decoded float32 IMAGE batch in RAM. Register the native file-backed
video and its embedded or external audio once with **Source Timeline**. The
descriptor retains the shared skip origin and lets Current Shot decode only the
active picture/audio window. **Lazy Motion AV Loader** remains as a 0.4
compatibility adapter, but new workflows do not need its full decoded-audio
fan-out.

Core **Load Video** remains supported for generated-audio workflows: the
tagged node reads only its loader disk path—never `get_components()`—and the
same native `VIDEO` can connect to Run Manager. Its direct `video_path` widget
also remains a compatibility fallback. The node fingerprints the media file at
registration time, then Tagged Ref2VA decodes and resizes only the active Plan
scene. Constant-frame-rate sources such as 25 or 30 fps are resampled to 24 fps
inside that scene window, so Reference Video Prep and its full-video tensors
are not required. Optional embedded audio is decoded from the identical time
window, preserving duration and synchronization. `skip_first_frames` moves
the timeline origin by native source frames (25 means one second on a 25 fps
file); video and audio receive the same offset. The decoder seeks backward to
a nearby keyframe, so the skipped prefix is neither tensorized nor normally
decoded from frame zero. Its
`preview_source` can feed **Lazy Motion Scene Preview** together with the Plan;
the integer scene widget selects the exact window to inspect. With no Plan—or
when the selected scene does not activate the motion tag—the preview emits no
IMAGE or AUDIO. Keeping preview on a separate branch avoids a circular
Plan/reference fingerprint connection.

For a song or other full source track, choose Source as final audio and enable
Source reference in Audio Policy. Connect the full loader only to Source
Timeline. Current Shot exposes the exact scene-local slice, which can feed a
standalone Tagged Audio Ref while its state feeds Tagged Ref2VA. Keep the
picture/reference-registry fingerprint connected to Plan; do not return a
downstream Current-Shot audio fingerprint to Plan, which would form a graph
cycle. The structured scene dependency already records the canonical PCM
window. The
[Studio Tagged Source Audio example](<example_workflows/MiniMax H3 Ref2V - Studio Tagged Source Audio.json>)
shows this single-wire timeline, `@audio_1` activation, H3-grid alignment,
assembly, recovery, and Run Manager asset binding.

The original numeric-range nodes remain available in the **legacy schedule**
category when explicit selectors are useful.

## Legacy scheduled references

```text
Load Image ─→ Scheduled Picture Ref ─┐
24 fps IMAGE (+ paired AUDIO) ─→ Scheduled Video Ref ─┐
Standalone AUDIO ─→ Scheduled Audio Ref ──────────────┴→ Scheduled Ref2VA

Current Shot prompt / scene / dimensions / length ───────────────────────↗
```

Stable aliases such as `@hero`, `@performance`, and `@voice` are optional. The
scheduler resolves active aliases to native `<Picture N>`, `<Video N>`, and
`<Audio N>` labels for each scene. It never writes semantic prompt definitions
for you.

The compliance control has three levels:

| Policy | Behavior |
|---|---|
| `strict` | Compile valid aliases and stop on scheduler mistakes. |
| `soft` | Compile valid aliases, warn about unresolved prompt tags, and continue. |
| `disabled` | Pass prompt text unchanged and make scheduler-owned checks non-blocking. |

See [Scheduled references](docs/SCHEDULED_REFERENCES.md) for selectors, native
numbering, hover previews, fingerprints, and patch priority.

## Review, resume, and restore

Review Gate owns retries after a scene has been saved. During sampling, the
optional floating **Cancel & reroll scene N** action cancels only the active H3
prompt, writes a new scene seed, and requeues from that checkpoint position.
During review, a prompt editor bound to the same Plan follows the active scene
and supplies the live prompt for retry or reroll. Review Gate's own prompt
textarea is disabled by default in 0.5; it can be restored in ComfyUI Settings
under **MiniMax H3 Contex Loop → Interface → Review Gate**, where an explicit
edit remains a fallback that overrides the connected editor for that retry.

To resume manually, keep the same `run_name`, set `start_clip` to the desired
scene, and retain the same dependencies. A bounded `scene_range` accepts one
scene (`3`) or one continuous range (`3:8`).

Loop Start keeps `verify_resume_history` enabled by default. If you
deliberately changed the Plan but still want to consume the already-generated
predecessor, turn it off before resuming. This bypasses Plan/history matching
only: saved MP4/checkpoint hashes, required tensors, shapes, and internal
metadata consistency remain mandatory. The saved predecessor does not acquire
your new settings retroactively.

Run Manager can restore archived prompts and Plan settings and optionally
archive loader-backed image/audio/video assets under the run folder. See
[Runs, review, and recovery](docs/RUNS_AND_RECOVERY.md).

## Documentation

- [Documentation index](docs/README.md) — choose a focused guide by task.
- [Prompt and timing guide](H3_CHAIN_FORMAT_GUIDE.md) — complete Plan JSON and
  node-setting reference.
- [Scene authoring](docs/SCENE_AUTHORING.md) — Plan editor, Prompt Editor,
  revisions, seeds, and bounded ranges.
- [Scheduled references](docs/SCHEDULED_REFERENCES.md) — tags, selectors,
  numbering, previews, compliance, and fingerprints.
- [Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) — audio modes, 15.070 s
  reference alignment, generated WAVs, trimming, and seam diagnostics.
- [Runs, review, and recovery](docs/RUNS_AND_RECOVERY.md) — Review Gate,
  checkpoints, Run Manager assets, partial output, and PNG export.
- [Advanced workflows](docs/ADVANCED_WORKFLOWS.md) — existing-video extension,
  long context, last-frame targets, and performance re-filming.
- [Masked editing](docs/MASKED_EDITING.md) — video inpainting, H3 mask cells,
  audio preservation, outpainting, and clip-bridge target preparation.
- [Compatibility](docs/COMPATIBILITY.md) — patch ownership, native guides,
  SolAttn, H3-Multishot, and frontend workarounds.
- [Example workflow notes](example_workflows/README.md)
- [Changelog](CHANGELOG.md)
- [Third-party credits](THIRD_PARTY_NOTICES.md)

## Project history and credits

This project began with **NikoDemon80's**
[H3 Motion Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)
and grew into a separate production-loop pack so both projects could remain
clear and coexist. The Ref2VA multi-reference/audio fix and first global-ref
demo were contributed by **seitanism**. The editor's quick reference/dialogue
interactions were inspired by **nkxx188's**
[ComfyUI-MiniMaxH3-Easy](https://github.com/nkxx188/ComfyUI-MiniMaxH3-Easy).

Full attribution is recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

GPL-3.0. See [LICENSE](LICENSE).
