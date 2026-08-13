<p align="center">
  <img src="assets/minimax-h3-contex-loop.svg" alt="MiniMax H3 Contex Loop — scene plans that survive the render" width="100%">
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
| 🗓️ | Scene-scheduled picture, video, and audio references |
| 👀 | Video-with-sound review, prompt retry, and seed reroll |
| 💾 | Atomic checkpoints, partial assembly, and safe resume |
| 🕘 | Branching prompt history and saved-run restoration |
| ⏩ | Existing-video continuation and optional source prepend |
| 🖼️ | Lossless PNG re-decode from saved scene latents |
| 🔬 | In-graph audio-seam diagnostics |

The runtime changes are opt-in. Ordinary ComfyUI workflows are not altered by
installing the pack; its guarded H3 patches activate only when a Contex Loop
Context node executes.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop.git
```

Restart ComfyUI and hard-refresh the browser. An `ffmpeg` executable on `PATH`
is preferred, but review and final assembly can fall back to ComfyUI's bundled
PyAV.

NikoDemon80's upstream H3 Motion Context pack is optional and may be installed
alongside this one for its manual Motion Context, Save Latent, and Load Latent
nodes. H3-Multishot is also supported through guarded payload reuse.

## Choose a workflow

Start with one of the maintained v2 examples:

- [Single-image I2VA 20s](<example_workflows/Looping MiniMax H3 V2 - Single Image I2VA 20s.json>)
  is the simplest long-form image-to-video workflow. One image anchors scene 1;
  later scenes continue through motion context.
- [Core FL2VA](<example_workflows/Looping MiniMax H3 V2 - Core FL2VA.json>)
  uses ComfyUI's stock MiniMax H3 Image to Video node with first and last frames,
  review/retry, prompt editing, and safe assembly.
- [Scheduled Ref2VA](<example_workflows/Looping MiniMax H3 Seamless Chain V2 - Scheduled Refs.json>)
  is the complete long-form workflow with per-scene picture, video, paired-audio,
  and source-song references.

See [all example workflows](example_workflows/README.md), including the
experimental existing-video and three-angle performance workflows.

## The loop

```text
Plan → Loop Start → Current Shot → H3 conditioning
                                      ↓
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
3. Choose an audio mode. For a prerecorded song, connect the same full track to
   Loop Start, Current Shot, and Assemble.
4. Queue the workflow. Review Gate pauses after every safely saved scene.
5. Approve, edit and retry, reroll the seed, or approve and stop.
6. Assemble the completed or partial manifest.

Existing output files are preserved. Assemble adds `_001`, `_002`, and so on
instead of overwriting an MP4 with the same requested name.

## Essential Plan settings

| Setting | Good starting point | Meaning |
|---|---:|---|
| `width × height` | `960 × 544` | Multiples of 32 |
| `context_length` | `22` | Repeated motion history carried into continuations |
| `encode_mode` | `video` | Preserves motion in the VAE latent |
| `anchor_mode` | `head` | Regenerates then trims the repeated opening context |
| `crop` | `disabled` | Best when source and target framing already agree |
| `default_duration_seconds` | `15` | Rounded up to H3's valid `17k+5` frame grid |
| `default_steps` | `20` | Override per scene when needed |
| `segment_crf` | `18–20` | Lower values produce larger, higher-quality checkpoints |

Use `generation_fingerprint` to record model, VAE, LoRA, references, CFG,
sampler, and scheduler choices that live outside the Plan. Change it when those
dependencies change so incompatible checkpoints cannot be resumed silently.

## Audio at a glance

| Mode | Use it when |
|---|---|
| `source_track` | A finished song or spoken performance must remain exact in the final video. |
| `generated_audio` | H3 should generate new speech, ambience, effects, or music. |
| `source_plus_timeline` | You intentionally want both the source slice and generated-audio history; experimental. |

For a 362-frame source-audio reference, Current Shot's experimental
`align_audio_reference` switch trims only the Ref2VA slice to **15.070 s**. It
keeps 603 H3 audio steps with a short padded tail and does not modify the full
track used for final assembly.

See [Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) for wiring, generated
WAV preservation, timing behavior, and the Seam Probe.

## Scheduled references at a glance

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
numbering, hover previews, conversion from core Ref2VA, fingerprints, and patch
priority.

## Review, resume, and restore

Review Gate owns retries after a scene has been saved. During sampling, the
optional floating **Cancel & reroll scene N** action cancels only the active H3
prompt, writes a new scene seed, and requeues from that checkpoint position.

To resume manually, keep the same `run_name`, set `start_clip` to the desired
scene, and retain the same dependencies. A bounded `scene_range` accepts one
scene (`3`) or one continuous range (`3:8`).

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
  numbering, previews, compliance, and conversion.
- [Audio and continuity](docs/AUDIO_AND_CONTINUITY.md) — audio modes, 15.070 s
  reference alignment, generated WAVs, trimming, and seam diagnostics.
- [Runs, review, and recovery](docs/RUNS_AND_RECOVERY.md) — Review Gate,
  checkpoints, Run Manager assets, partial output, and PNG export.
- [Advanced workflows](docs/ADVANCED_WORKFLOWS.md) — existing-video extension,
  long context, last-frame targets, and performance re-filming.
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
