# Example workflows

Examples are organized first by H3 generation mode, then by authoring level.
Each completed mode should contain the same two-workflow pair:

1. **Normal** — the standard Plan and scene-editor workflow.
2. **Studio** — the same generation graph and prompt plan with Plan Studio as
   the authoring interface.

All maintained 0.5 Chain examples make Audio Policy and Transition Policy
explicit.
Normal workflows place a model-free Preflight node before Loop Start; Studio
workflows use Plan Studio's shared preflight inputs and report. Old Plan audio
and continuation widgets remain readable compatibility controls, not the
recommended authoring surface.

```text
example_workflows/
├── assets/
│   ├── jigen_market_garden_doom_opening.png
│   ├── jigen_market_garden_doom_last.png
│   ├── soldier_crabs_bribie_island_cc0.webm
│   ├── soldier_crabs_inpaint_mask.png
│   └── soldier_crabs_reference_cc0.png
├── EXPERIMENTAL MiniMax H3 Ref2V - Sequential Motion.json
├── MiniMax H3 Deferred Upscale - H3 LBH 3D.json
├── MiniMax H3 Deferred Upscale - SeedVR2 Full Chain.json
├── MiniMax H3 - Masked AV Bridge - Two Clips.json
├── MiniMax H3 - Masked AV Extension - Chain + Reference Image.json
├── MiniMax H3 - Masked AV Extension - Single Clip.json
├── MiniMax H3 - Masked Video Inpaint.json
├── MiniMax H3 FL2V - Normal.json
├── MiniMax H3 I2V - Normal.json
├── MiniMax H3 I2V - Studio.json
├── MiniMax H3 Ref2V - Basic.json
├── MiniMax H3 Ref2V - Masked Video Inpaint.json
├── MiniMax H3 Ref2V - Tagged.json
├── MiniMax H3 Ref2V - Studio Tagged.json
├── MiniMax H3 Ref2V - Studio Tagged Source Audio.json
├── MiniMax H3 T2V - Normal.json
├── MiniMax H3 T2V - Studio.json
└── Archive/
    └── previous mixed and experimental examples
```

Active workflow JSON files remain directly in `example_workflows/` so ComfyUI
can discover them. Only retired examples are nested under `Archive/`. T2V and
I2V are paired Normal/Studio examples. FL2V currently has one Normal workflow
that demonstrates indexed A→B→A endpoints. Ref2V is represented at three
levels: core global references, prompt-driven tagged references with the
standard editor, and tagged references with Studio authoring plus run-asset
restoration. The former numeric-range examples are retained in `Archive/`.
The additional sequential-motion workflow is deliberately prefixed
`EXPERIMENTAL` because it combines a long advancing Ref2VA video timeline with
recursive Motion Context.

## Deferred H3 upscale

[`MiniMax H3 Deferred Upscale - SeedVR2 Full Chain.json`](<MiniMax H3 Deferred Upscale - SeedVR2 Full Chain.json>)
is the low-RAM whole-video route. Checkpoint Manager supplies the selected
generated lineage, including a partial run when later planned scenes have not
been rendered yet; Full-Chain Latent Video Adapter re-decodes the original H3 video
latents scene by scene into a cached lossless native VIDEO, resolves all H3
boundary blends first, and hands that single continuous file to SeedVR2 Direct.
The default disk-backed VAE buffer prevents a decoded scene—let alone the full
chain—from becoming a large resident IMAGE batch. SeedVR2 then uses its own
21-frame chunks with a two-frame context overlap and sends its audio-preserving
VIDEO directly to core Save Video. Install the
[ethanfel SeedVR2 fork](https://github.com/ethanfel/ComfyUI-SeedVR2_VideoUpscaler)
before opening the graph.

[`MiniMax H3 Deferred Upscale - H3 LBH 3D.json`](<MiniMax H3 Deferred Upscale - H3 LBH 3D.json>)
is a standalone second-pass workflow: it contains no first-pass generation
loop or source Plan. Select the latest generated scene you want in Checkpoint
Manager, then queue the child upscale profile. The selected lineage may be
shorter than the saved Plan; for example, scene 1 can be upscaled while scenes
2–4 are still ungenerated. The manager emits that verified immutable lineage
directly; recovery-only Source Timeline metadata stays embedded in the manifest.

The loop sends only the clean 24-channel video x0 through LBH's temporal
**MiniMax H3 Latent Upscaler (3D)**. The default target is 1.5 MP on a grid-32
canvas, followed by a conservative two-step pass at denoise 0.24 with Euler.
The pack rejoins the untouched 32-channel audio, performs NestedTensor-safe
video-only CONST re-noise, and masks audio out of pass 2. Install
[Comfyui_Minimax_h3_latent_Upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler)
and place its 3D checkpoint in `models/latent_upscale_models/` before opening
the graph.

Pass-2 conditioning is rebuilt independently from the learned latent. For
`match` picture refs, the node uses LBH's actual output canvas to re-encode the
picture VAE latent and Qwen presentation before creating a new Guider. `max`
pictures, video refs, audio refs, and Qwen-only semantic anchors keep their
native geometry instead of being blindly multiplied by the upscale factor.

The included Comfy Kitchen attention override is bypassed intentionally. At
large target canvases, Sage prequantized attention can exceed its int32 tensor-stride
range even with ample VRAM; the graph therefore keeps ComfyUI's PyTorch
attention backend.

`save_latent` is off by default. Every delivered HQ scene, prompt, audio
sidecar, integrity record, partial manifest, and final merge remains under
`output/h3_chains/<run>/upscaled/<profile>/`; enable latent saving only when
the full HQ sampler latent itself is needed later. Current Tagged and Scheduled
Ref2VA nodes save the active native VAE/audio reference blocks, compact Qwen
presentation frames, and—starting with cache v2—the original picture masters
needed for target-resolution `match` conditioning. Segment Save automatically
adopts them under
`output/h3_chains/<run>/reference_cache/` and records that run-local descriptor
on the exact source revision. The child workflow therefore finds the matching
scene from the source manifest alone: no Plan, registry, picture, video, or
reference-audio wire is required. Runs created before this cache was introduced
remain supported: they scale the saved presentation picture as a pass-2
fallback. Runs without any cache use the node's `text_only` fallback; select
`error` when an exact cached Ref2VA pass is mandatory.

The masked-video workflow uses the same Chain Loop, checkpoint/review, resume,
and assembly path as the generation examples. A pack-native source-target node
selects the current loop interval and uses the stock H3 joint target as the
authoritative AV grid before applying an arbitrary per-row inpaint mask.

## Masked AV extension and bridge

The AV examples share the bundled modern
[CC0 soldier-crab footage](assets/README.md#soldier_crabs_bribie_island_cc0webm).
They use original natural-history prompts and do not contain or imitate the
copyrighted *Crab Rave* soundtrack, music video, choreography, or branding.
Copy the WebM to `ComfyUI/input/`; the chained Ref2VA example additionally
needs `soldier_crabs_reference_cc0.png`.

- [`MiniMax H3 - Masked AV Extension - Single Clip.json`](<MiniMax H3 - Masked AV Extension - Single Clip.json>)
  uses the normal recursive Chain Loop with a one-scene Plan. Existing Video
  Context preserves the source tail as scene 1's 39-frame/65-audio-step target
  prefix, and Assemble prepends the complete normalized source once.
- [`MiniMax H3 - Masked AV Extension - Chain + Reference Image.json`](<MiniMax H3 - Masked AV Extension - Chain + Reference Image.json>)
  runs three sequential Ref2VA extensions through the same loop. The protected
  AV prefix is authoritative for pose, motion, camera, lighting, and timing;
  the tagged `@crabs` image only stabilizes species appearance.
- [`MiniMax H3 - Masked AV Bridge - Two Clips.json`](<MiniMax H3 - Masked AV Bridge - Two Clips.json>)
  splits the 313-frame 24-fps source into frames 0–98 and 213–312. The
  192-frame bridge protects 39 frames at each endpoint and generates the exact
  114-frame gap before the graph reassembles the original 313-frame timeline.

The extension pair deliberately uses this pack's loop, checkpoints, review
gate, recovery, and disk-backed assembly. The bridge is a single two-ended
masked target and therefore uses the dedicated **Masking · Two-Clip AV Bridge**
node with an ordinary ComfyUI sampler rather than pretending it is recursive.

## Masked video inpaint

[`MiniMax H3 - Masked Video Inpaint.json`](<MiniMax H3 - Masked Video Inpaint.json>)
adapts the earlier standalone PerRowMasking experiment to this pack's
native-first H3 mask runtime and full Chain Loop. It contains no MODEL patch
or LTX AV concat/separate node.

[`MiniMax H3 Ref2V - Masked Video Inpaint.json`](<MiniMax H3 Ref2V - Masked Video Inpaint.json>)
uses the identical source-target, mask, loop, review, and assembly graph with
the Ref2VA base model and a single global `<Picture 1>`. The picture defines
the regenerated crab appearance; the source movie remains the real masked AV
target and is deliberately not connected again as `ref_video_0`.

1. Copy the bundled source video and mask to `ComfyUI/input/`. Also copy the
   bundled reference PNG for the Ref2V variant.
2. Keep the bundled one-frame mask for a fixed region, or replace it with a
   tracked MASK batch covering the complete source timeline.
3. Verify the effective 32×32 H3 cells in Grid Preview.
4. Edit the scene prompt or Plan, then run the loop normally.

Apply Target Mask uses **H3 exact (causal/token max)** in this workflow. It
reduces tracked masks through H3's real causal frame groups and 2×2 latent
tokens rather than interpolating across time. The legacy trilinear choice is
kept only for controlled comparisons with older renders.

The two-scene demo edits 311 frames from the 313-frame source. Each generation
is 175 frames; scene 2 repeats and protects a 39-frame edited prefix, so it
delivers 136 new frames. The workflow preserves source audio. **Loop Mask
Slice** broadcasts its static example mask, but when supplied a tracked batch
it selects frames 0..174 and 136..310 for the two scenes. **Loop Source AV
Target** selects the same source intervals and copies the video/audio encodes
into the exact stock H3 target shapes. This avoids the one-token temporal
mismatch possible when independently encoded streams are combined by a generic
LTX AV node. Chain Context preserves the preceding edited overlap before Apply
Target Mask intersects the spatial mask; Loop Save, review, resume, and
Assemble remain active.

Apply Target Mask intersects any existing nested AV mask, which allows this
manual spatial path to compose with a chain `masked_av` prefix. See
[Masked editing](../docs/MASKED_EDITING.md) for audio modes and preparation of
outpaint or two-clip bridge targets.

The Ref2V variant is the maintained compatibility demonstration for
Ablejones/droz's `droz_MiniMaxH3_LatentMaskInpainting_wReference_v3.1`
workflow. Its H3 mask conversion corresponds to `auto + max + max` with zero
additional grow. Ablejones' Subject Crop/Uncrop, SAM3 tracking, and optional
mask growth remain external preparation/compositing tools; they are not
required for the latent mask to execute correctly.

## T2V

Both files use ComfyUI's core `MiniMaxH3ImageToVideo` node with `first_frame`
and `last_frame` deliberately disconnected, which selects its T2VA path. They
share the same two-scene portrait plan, model graph, seeds, generated-audio
route, 22-frame motion context, checkpointing, Review Gate, recovery path, and
final assembly. The shared model stack uses ComfyUI's
core `ModelAttentionBackend` set to `comfy kitchen attention`, followed by
`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` at strength 1.0.
Both the Plan default and scheduler fallback use eight sampling steps with the
`lcm` sampler and `beta` scheduler.

- [`MiniMax H3 T2V - Normal.json`](<MiniMax H3 T2V - Normal.json>)
  uses the standard Scene Prompt Editor.
- [`MiniMax H3 T2V - Studio.json`](<MiniMax H3 T2V - Studio.json>)
  uses the optional timeline-oriented Plan Studio plus the separate Rich Scene
  Prompt Editor. Neither changes sampling or ComfyUI execution.

Each requested ten-second scene normalizes to 243 raw H3 frames. The second
scene reproduces and removes 22 context frames, so the assembled delivery is
464 frames, or 19.333 seconds at 24 fps. Normal demonstrates a hard trimmed
boundary (`video_blend_frames = 0`); Studio demonstrates a five-frame visual
blend. These are Plan defaults; each scene can override the blend entering that
scene in its advanced settings. Audio remains frame-locked and is not
crossfaded.

### Prompt source

Scene 1 is reproduced verbatim from a prompt shared by **🦙rishappi** in
Banodoco's `#minimax_h3_chatter` on August 11, 2026:
[original Discord message](https://discord.com/channels/1076117621407223829/1532625331960152124/1536689209761599608).
Scene 2 is a new repository-authored continuation using the same H3 T2VA
three-section structure. Each workflow also contains this attribution in a
visible note beside the graph.

## I2V

Both files use one opening image with ComfyUI's core
`MiniMaxH3ImageToVideo`. The Frame Gate
(`MiniMaxH3ChainFirstSceneImage`) sends the opening image only to scene 1;
scene 2 receives no opening image and continues exclusively from the 22-frame
H3 Motion Context. Do not bypass this gate or the opening frame will be
reapplied on every scene.

The same gate also exposes an optional `last_frame` input and output. That
target passes through on every loop where it is supplied. For distinct or
alternating end frames, drive an upstream image-index switch with Current
Shot's `clip_index`, connect the switch output to the gate's `last_frame`, and
connect the gate output to core `MiniMaxH3ImageToVideo.last_frame`. The bundled
I2V pair leaves this optional route disconnected.

- [`MiniMax H3 I2V - Normal.json`](<MiniMax H3 I2V - Normal.json>) uses the
  stable Scene Prompt Editor with rich token presentation but no active prompt
  optimizer UI.
- [`MiniMax H3 I2V - Studio.json`](<MiniMax H3 I2V - Studio.json>) uses Plan
  Studio plus the separate Rich Scene Prompt Editor and its optional optimizer.

The pair uses the same Comfy Kitchen attention, LightX2V eight-step LoRA,
`lcm` sampler, `beta` scheduler, generated-audio route, checkpoint/review path,
and final assembly as T2V. It renders at 896 × 672 to preserve the bundled
image's 4:3 composition. Each scene requests 362 raw frames; after removing 22
repeated frames from scene 2, delivery is 702 frames, or 29.25 seconds at 24
fps. Normal uses a hard boundary and Studio demonstrates a five-frame blend.

Copy [`assets/jigen_market_garden_doom_opening.png`](assets/jigen_market_garden_doom_opening.png)
to `ComfyUI/input/`, then select it in the workflow's Load Image node. The JSON
keeps the basename preselected, but ComfyUI does not load arbitrary files from
a custom-node repository.

### Prompt and image source

Scene 1 and the opening image were shared by **ᴊɪɢᴇɴ** in Banodoco's
`#minimax_h3_gens` on August 12, 2026:
[prompt and source image](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226),
[generated result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555).
The workflow normalizes escaped line breaks and removes the surrounding
code-string quote while preserving the source wording. Scene 2 is a new
repository-authored continuation and intentionally contains no Picture label.

## FL2V

[`MiniMax H3 FL2V - Normal.json`](<MiniMax H3 FL2V - Normal.json>) is a
two-scene A→B→A loop built from the same working I2V graph. It adds this pack's
Frame Index Switch between two Load Image nodes and the Frame Gate:

```text
Current Shot.clip_index ───────────────┐
Frame B ─ frame_1 ┐                    ▼
                  ├─ Frame Index Switch → Frame Gate.last_frame → core last_frame
Frame A ─ frame_2 ┘
Frame A ───────────────────────────────→ Frame Gate.image → core first_frame
```

Scene 1 receives Frame A as its opening and Frame B as its ending, so its
prompt uses the two-picture FL2VA alignment sentence. Scene 2 starts from H3
Motion Context at B, receives only Frame A as its final target, and therefore
uses the one-picture L2VA alignment sentence. The switch wraps by scene index:
scene 1 selects B, scene 2 selects A, and a third scene would select B again.

Frame A is the credited source image used by the I2V pair. Frame B is the
final frame extracted from the credited generated result. Copy both PNG files
from [`assets/`](assets/) to `ComfyUI/input/` before loading the workflow.

## Ref2V

The Ref2V set uses the same two credited Market Garden pictures, the same
two-scene plan, and the same model/sampler stack at every level:

All maintained workflows route Chain Context's LATENT output to the sampler.
That output is a no-op pass-through in the default `guide` mode and carries the
prepared target prefix in `masked_av`, so changing modes cannot silently leave
the sampler on the unprepared conditioner latent.

- [`MiniMax H3 Ref2V - Basic.json`](<MiniMax H3 Ref2V - Basic.json>) connects
  both Load Image nodes directly to ComfyUI's core
  `MiniMaxH3ReferenceToVideo`. Both images are global, so the prompts use the
  native `<Picture 1>` and `<Picture 2>` labels in both scenes.
- [`MiniMax H3 Ref2V - Tagged.json`](<MiniMax H3 Ref2V - Tagged.json>) chains
  two Tagged Picture nodes into `MiniMaxH3TaggedReferenceToVideo`. There are no
  numeric scene selectors: `@style_base` is present in both scene prompts,
  while `@interior` appears only in scene 2. Current Shot supplies
  `clip_index` and `clip_count`, and the final reference fingerprint is
  connected to the Plan for checkpoint safety.
- [`MiniMax H3 Ref2V - Studio Tagged.json`](<MiniMax H3 Ref2V - Studio Tagged.json>)
  keeps that prompt-driven generation path and adds Plan Studio, Rich Scene
  Prompt Editor, and an inline Run Manager. It is also the experimental
  `masked_av` example: Chain Context's latent output feeds the sampler, and a
  39-frame video/65-step audio prefix is preserved before Loop Trim removes the
  repeated delivery overlap. Both image loader outputs connect to raw asset
  sockets as well as their Tagged Picture nodes. The manager archives image
  fallbacks by default and restores each saved run's Plan plus the matching
  loader selections.
- [`MiniMax H3 Ref2V - Studio Tagged Source Audio.json`](<MiniMax H3 Ref2V - Studio Tagged Source Audio.json>)
  derives from Studio Tagged and registers Load Audio once with Source
  Timeline. The descriptor feeds Plan Studio preflight, Loop Start, recovery,
  and assembly through saved state. Current Shot's scene-local slice feeds the
  `@audio_1` Tagged Audio Ref with `align_audio_reference` enabled; its
  downstream fingerprint is deliberately not returned to Plan, avoiding a
  cycle while structured dependencies retain exact PCM provenance.
- [`EXPERIMENTAL MiniMax H3 Ref2V - Sequential Motion.json`](<EXPERIMENTAL MiniMax H3 Ref2V - Sequential Motion.json>)
  adds one long video with embedded audio as `@motion` + `@motion_audio` and
  predates the dedicated Tagged Motion Ref. For new motion-transfer workflows,
  replace its generic Tagged Video node with Tagged Motion Ref so `@motion`
  compiles as a reusable action Subject instead of the whole `<Video N>`.
  Its timeline remains `sequential`. Current Shot `state` is mandatory:
  scene 1 receives source frames `0:243` and scene 2 receives `221:464`, so the
  source repeats the same 22-frame interval as Motion Context instead of
  replaying frame zero. The included Patch Priority pass-through is inert on
  updated ComfyUI and remains wired only to protect the legacy compatibility
  path when this experimental workflow is opened on an older build.

The tagged wrapper activates only registered aliases found in the resolved
prompt and compiles them to native H3 labels. Generic reference nodes do not
insert subject definitions; Tagged Motion Ref deliberately inserts its one
compiler-owned action Subject definition. Every scene therefore
contains the complete user-editable Ref2VA structure in this order:
`subject_definitions`, `summary`, `retention_analysis`,
`detailed_description`, `overall_soundscape`, and `non_diegetic_music`.

Copy both PNG files from [`assets/`](assets/) to `ComfyUI/input/` before
loading any Ref2V example. The prompt concept and first image came from
[ᴊɪɢᴇɴ's Banodoco post](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226);
the second image is the last frame of the
[credited result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555).

The sequential example does not bundle its motion video. Select a source with
embedded audio that remains at least 464 frames / 19.333 seconds after 24 fps
conversion. Reference Video Prep validates the complete timeline before the
prompt-driven wrapper slices it. The Plan uses `generated_audio`; paired
`@motion_audio` is weak rhythmic guidance, not the assembled output track.

## Archive

[`Archive/`](Archive/) contains the previous mixed catalog unchanged for
compatibility, research, and migration. These workflows are not deleted, but
they are not the recommended type-based starting points for the 0.5 examples.
The archived catalog explains their historical purpose and extra dependencies.
