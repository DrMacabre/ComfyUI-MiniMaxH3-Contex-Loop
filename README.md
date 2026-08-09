# ComfyUI MiniMax H3 Contex Loop

Render an ordered MiniMax H3 scene plan through one recursive ComfyUI sampling
body. Every accepted scene is checkpointed before the next begins, allowing
prompt/seed review, rejection, partial assembly, interruption recovery, and
resume from the first unfinished scene. Motion and optional generated audio
continue across scene boundaries instead of restarting from a still image.

The spelling **Contex** is the repository's chosen public name:
`ComfyUI-MiniMaxH3-Contex-Loop`.

## Relationship to H3 Motion Context

This repository grew from **NikoDemon80's** original
[ComfyUI-H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context),
whose initial implementation, research, and commit history remain credited
here. Niko's upstream project continues as the focused manual Motion Context
pack. This project is the independently namespaced, specialized loop pack.

Both packs may be installed at the same time:

- upstream exclusively owns `MiniMaxH3MotionContext`,
  `MiniMaxH3MotionContextTrim`, `MiniMaxH3MotionContextSaveLatent`, and
  `MiniMaxH3MotionContextLoadLatent`;
- this pack exports the unique `MiniMaxH3LoopTrim` node plus the nine existing
  `MiniMaxH3Chain*` loop nodes;
- the internal ComfyUI runtime wrappers vendor upstream's shared marker and
  ownership ABI. Whichever pack activates first installs the same compatible
  wrapper; the second recognizes it and stands down instead of wrapping
  ComfyUI twice; and
- browser extensions, review events, and HTTP routes also use this pack's own
  namespace.

The loop remains self-contained; installing upstream is optional. Install
upstream as well when you want its manual Motion Context, Save Latent, and Load
Latent workflow. Existing checkpoints remain under
`output/h3_chains/<run_name>/` and retain their previous format, so the rename
does not invalidate resumable renders.

The Ref2VA multi-reference/audio compatibility fix and original global-ref
demonstration were contributed by **seitanism** in the Banodoco MiniMax H3
seamless-extension thread. The visual editor's quick reference/dialogue ideas
were inspired by **nkxx188's** ComfyUI-MiniMaxH3-Easy under its MIT license; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Install

Clone or place the folder at:

```text
ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-Contex-Loop
```

Restart ComfyUI and hard-refresh the browser. Merely importing the pack only
registers its nodes and routes. The internal marker-gated patches self-test and
activate only when `MiniMax H3 Contex Loop Context` executes. They share their
runtime ABI with Niko's upstream pack; workflows that use neither
implementation remain unchanged.

## Loop graph

```text
Contex Loop Plan -> Loop Start -> Current Shot
                                  | prompt / seed / length / audio slice
                                  v
                       MiniMaxH3ReferenceToVideo
                                  v
                         Contex Loop Context
                                  v
                       guider / sampler / decode
                                  v
                         Contex Loop Trim
                           |             |
                           v             v
                  Segment + Checkpoint -> Review Gate
                                             |
                                             v
                                          Loop End
                                             | recurse
                                             v
                                     next planned scene

Loop End.manifest -> Contex Loop Assemble
```

The loop context engine preserves existing Ref2VA image, video, and audio
references, then appends the previous scene's marked continuation audio block.
No external patch script or ComfyUI-core edit is required.

## Automated disk-backed chains

The `MiniMax H3 Contex Loop` nodes (internally `MiniMaxH3Chain*`) turn a
repeated Ref2VA graph into one recursive sampling body. They are specialized
for MiniMax rather than generic carry-value loop
nodes: shot lengths are placed on H3's `17k+5` frame grid, source-song windows
are computed from the delivered frame timeline, clip 1 bypasses Motion Context,
and every later clip receives the preceding frame tail and optional AV latent.
The recursion engine is a self-contained MiniMax adaptation of Ethanfel's SxCP
loop implementation; ComfyUI-Prompt-Builder is not a runtime dependency.

The graph shape is:

```
H3 Chain Plan -> H3 Chain Loop Start -> H3 Chain Current Shot
                                         | prompt / seed / length / audio slice
                                         v
                              MiniMaxH3ReferenceToVideo
                                         v
                                  H3 Chain Context
                                         v
                              guider / sampler / decode
                                         v
                               MiniMax H3 Contex Loop Trim
                                  |                |
                                  v                v
                     H3 Chain Segment +       H3 Chain Review Gate
                         Checkpoint  ---------->    |
                                                   v
                                            H3 Chain Loop End
                                                   | recurse
                                                   v
                                          next planned clip

H3 Chain Loop End.manifest -> H3 Chain Assemble
```

Wire the original song into Loop Start, Current Shot, and Assemble when using a
source-track mode. All three nodes verify the same full-waveform hash, so a
miswire cannot render or mux a different song. Source audio must cover the full
planned video duration; a short track fails before sampling instead of silently
truncating the final video.

Wire `Loop Start.state` into `Current Shot.state`, then use the pass-through
`Current Shot.state` for Chain Context, Segment + Checkpoint, and Loop End.
Wire the Start's `flow` directly to Loop End. The stock Ref2VA node receives
the Current Shot outputs for `prompt`, `width`, `height`, `length`, and its
first standalone audio-reference socket. `noise_seed` goes to Random Noise and
`steps` goes to Basic Scheduler. The sampler's raw output goes to both decode
nodes, Segment + Checkpoint, and Loop End. Trimmed images go to Segment +
Checkpoint and Loop End; trimmed audio goes to Segment + Checkpoint.

For human validation after every iteration, insert `H3 Chain Review Gate`
between Segment + Checkpoint and Loop End, and wire the same frame-exact
trimmed audio into its optional `audio` input. The checkpoint is committed
before review begins. The gate then muxes a temporary review MP4 and waits
asynchronously while its node UI plays the clip with synchronized sound. Its
controls provide:

- **Approve & continue** — accept this clip and render the next scene;
- **Retry prompt / seed** — edit the scene prompt or seed and replace this clip;
- **Reroll seed** — retain the edited prompt, choose a new uint64 seed, and retry;
- **Approve & stop** — keep the checkpoint, end this run, and by default join
  every accepted scene through this point into a partial MP4.

`play_notification_sound` is off by default; enable it for a short local
browser chime when a review is ready. Browsers may require one prior interaction
with the ComfyUI page before allowing notification audio.
`auto_continue_timeout_minutes` shows a live countdown and automatically
approves the clip when it expires; leave it at `0` to wait indefinitely.

`unload_models_while_waiting` is optional and off by default. When enabled it
releases VRAM during review; **Approve & continue** then reloads the model stack.
The cross-thread gate wake-up remains active while unloading. A stop does not
reload models because execution ends at the checkpoint.

`assemble_partial_on_stop` writes
`final/partial_through_clip_NNNN.mp4`. `partial_audio_source=checkpointed` uses
the delivered audio stored by Segment + Checkpoint; `source` requires the full
song on the Review Gate's `source_audio` input; `none` makes a silent partial.
If requested audio is unavailable, the gate still writes a silent partial and
reports the reason.

The bottom of the Review Gate is also a checkpoint browser. **Refresh** lists
the saved scenes for the Plan's current `run_name`; select **Resume scene N**
and press **Load checkpoint** to set Loop Start to `start_clip=N`. Queueing the
workflow then performs the normal hash/integrity validation and loads scene
`N-1` as context. Loading also displays the joined partial video through that
checkpoint when one exists, otherwise it displays the saved predecessor scene.

Prompt and seed retries remain at the same clip index and retain only the last
accepted predecessor as motion/audio context. The rejected artifacts are
replaced by Segment Save's normal transaction. Runtime edits are also copied
back into the visual Plan editor so saving the workflow preserves them. A
browser refresh recovers a pending review instead of releasing the gate.

KJNodes' optional `Model Preview Override` is supported inside the recursive
body. Comfy gives cloned nodes generated execution IDs while KJ's preview
widget lives on the original canvas ID; this pack bridges those IDs only for
events originating under an H3 Chain Loop End. Ordinary KJ previews and
workflows without the H3 loop are unchanged.

The plan is compact JSON. Global prompt text can live in `prompt_prefix`; each
shot supplies only what changes. A shot may omit or leave `prompt` blank when
the shared prompt is non-empty; plans where both are blank are rejected.

For easier human editing, both `prompt_prefix` and per-shot `prompt` may be
arrays of strings. The node joins the entries with real newlines; use an empty
string entry for a blank line. Ordinary string prompts remain supported.

### Built-in scene editor

`H3 Chain Plan` now opens its plan as a visual, multiline scene editor. It is
only a frontend for the existing `plan_json` input: edits serialize back to
the same JSON contract, so existing workflows load unchanged and workflows
without this node are unaffected.

The editor provides:

- a shared prompt for identity, wardrobe, style, and continuity rules;
- multiline prompt boxes with no visible escaped `\n` text;
- draggable scene cards with duplicate, delete, and arrow reordering;
- distinct automatic scene-border colors with persistent per-scene pickers;
- seconds, exact-frame, or inherited duration controls per scene;
- live raw/delivered frame and total-runtime calculations using this pack's
  exact H3 round-up and continuation-overlap rules;
- `@` reference-tag insertion for `<Picture N>`, `<Video N>`, and `<Audio N>`;
- `#` dialogue insertion using MiniMax `<d>...</d>` markup;
- optional per-scene steps and uint64 seeds; and
- a raw JSON escape hatch with copy, import, and export.

Scene colors are stored as editor-only node properties. Changing them does not
alter `plan_json`, generation hashes, rendered output, or resume compatibility.

The `@` reference and `#` dialogue interaction ideas were inspired by
[ComfyUI-MiniMaxH3-Easy](https://github.com/nkxx188/ComfyUI-MiniMaxH3-Easy)
by **nkxx188**, with credit and its MIT notice recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). This pack intentionally
keeps its own MiniMax chain timing, checkpoint, and resume model instead of
adopting Easy's loader/sampler architecture.

For the complete copy/paste format reference—including scene lengths, exact
frame rules, seeds, steps, audio modes, and resume behavior—see
[`H3_CHAIN_FORMAT_GUIDE.md`](H3_CHAIN_FORMAT_GUIDE.md).

```json
{
  "prompt_prefix": "Global subject and continuity instructions.",
  "defaults": {"duration_seconds": 15, "steps": 20},
  "shots": [
    {"id": "intro", "prompt": "Opening shot.", "seed": 123},
    {"id": "street", "prompt": "Continue into the street.", "seed": 456},
    {"id": "outro", "prompt": "Finish the take.", "duration_seconds": 5}
  ]
}
```

You may specify an exact `length` instead of seconds, but it must satisfy
`length % 17 == 5`. Missing seeds are deterministically derived from
`base_seed`, clip index, and shot id. Resolution and context settings are
global and checkpointed; changing them invalidates resume. Set
`generation_fingerprint` to a stable version tag for the external model, VAEs,
global references, CFG, and scheduler, and change that tag whenever any of those
inputs changes. It becomes part of the resume compatibility hash.

### Segments and resume

Every iteration writes these artifacts under
`output/h3_chains/<run_name>/` before the next clip begins:

- `segments/clip_0001.<transaction>.mp4`: video-only H.264 segment;
- `checkpoints/clip_0001.<transaction>.safetensors`: context frames, AV latent,
  and delivered generated audio;
- `checkpoints/clip_0001.json`: prompt/seed/timing hashes and artifact manifest.

The JSON file is the atomic commit point. A retry first writes a new immutable
video/checkpoint pair and their SHA-256 hashes, then switches the fixed JSON slot
to that pair in one rename. An interruption cannot combine a new video with an
old latent checkpoint; successful retries clean the superseded pair.

The loop carries only the last context frames and compact AV latent in memory;
it never builds the multi-gigabyte cumulative IMAGE tensor used by manually
duplicated long-chain workflows. `H3 Chain Assemble` stream-copies the video
segments and muxes audio only at the end.

To resume at clip N, keep the same `run_name` and set `start_clip=N`. The Start
node loads clip N-1, verifies every predecessor against the current plan, and
continues. Prompts for clip N and later may be changed. Any change to an earlier
prompt, seed, duration, resolution, context setting, or audio mode is rejected
until those earlier clips are regenerated. Changing the source song is also
detected from its waveform hash. Re-running a clip overwrites its fixed
segment/checkpoint slot, so rejected attempts do not accumulate.
The Review Gate's checkpoint browser performs this `start_clip` setup without
manually editing Loop Start; the validation rules are identical.

If all clips were saved but the browser, Loop End, or final assembly stopped,
connect the same Plan (and source song when applicable) to `H3 Chain Load
Completed Manifest`. It validates every artifact and rebuilds the manifest for
Assemble without sampling the last clip again.

### Chain audio modes

- `source_track`: Current Shot slices the uploaded song for every Ref2VA clip;
  Motion Context carries video only; Assemble muxes the original song. This is
  the recommended music-video mode. Real source audio must cover the full plan;
  a short genuinely silent placeholder is detected and zero-padded safely.
- `generated_audio`: no source reference is needed; Chain Context carries the
  previous raw audio latent on the timeline and Assemble concatenates the
  checkpointed generated audio. Segment + Checkpoint requires trimmed decoded
  audio in this mode and rejects any sample count that does not exactly match
  the delivered video frames.
- `source_plus_timeline`: supplies both the source-song Ref2VA window and the
  preceding generated audio latent. This is experimental; Assemble uses the
  source track by default.

Segment saving requires the PyAV/libx264 support shipped with normal ComfyUI
installations. Final assembly requires `ffmpeg` on `PATH`.

## Settings and what to pick

**context_length** - how many frames of the previous clip to carry over.
The video VAE only distinguishes certain run lengths, so useful values are
**5, 22, or 39**; anything else snaps down to the nearest. 5 is just barely
fluid, 22 is nearly seamless, 39 is untested. **Use 22.**

**encode_mode** - `video` (default) encodes the whole run in one VAE call
so the motion lives inside the latent. `frames` encodes each frame as a
separate still; it costs twice the rows and left a visible seam in testing.
**Use video.** `frames` remains only for comparison.

**anchor_mode** - `head` (default) pins the frames at the start of the
clip; they come back in the output and the Trim node removes them. `before`
places them at negative time instead so nothing needs trimming - but its
coordinates collide with the text conditioning, which weakens the anchors
and consistently darkens output, failing subtly rather than loudly.
**Use head.** `before` remains only so the failure can be reproduced.

**audio_mode** - `timeline` (default) places the pinned audio on the new
clip's own timeline so the model continues it. `ref` is the stock
placement, which the model *imitates* instead - similar music, not the
same recording, and an audible tick at every join. **Use timeline.**
`ref` remains only for comparison.

**audio_context_length** - how much tail audio to pin, in frames,
independent of the video window. It is end-aligned with the pinned video,
so both always finish at the same instant (the join) and this only controls
how far back the sound reaches. **Use 22** to overlay the video window
exactly; that's the tested config. Longer windows (44, 96) are legal and
land in safe coordinate space, but nobody has rendered one yet.

The Trim node also has `match_tail` (default on). Leave it on: H3 rounds its
40 Hz audio grid to the nearest step, so some frame lengths decode about 8 ms
long and others about 8 ms short. Match Tail truncates or zero-pads that
fractional-step difference so drift cannot grow at every join.

## The audio story

The first version put pinned audio through H3's reference mechanism, which
is where audio conditioning normally lives. Joins had a small tick - the
audio seemed to briefly speed up and go offbeat. Waveform inspection showed
no splice error; both sides of every join were individually smooth.

Cross-correlating each clip's opening against the previous clip's ending
(the `tests/seam_probe.py` script in this repo) revealed the real problem: the
new clip's audio *resembled* the old clip's - same instruments, same
groove - but never matched it. A cover band, not the same recording. The
model was treating the reference as "a separate clip that sounds like
this," which is exactly what references are for, and exactly wrong for
continuation.

The fix mirrors what already worked for video: the rows the model sees are
identical between the two mechanisms; only their **time coordinates**
differ, and the coordinates are what tell the model "separate clip" versus
"this clip, earlier." So the pinned audio keeps riding the reference
machinery for construction, and its coordinates are rewritten onto the new
clip's own timeline, ending exactly where the pinned video ends. After the
change, measured correlation at the joins went from ~0.45 with incoherent
timing to 0.95+ with a flat, stable offset, and the tick disappeared. The
same measurement across a multi-clip chain shows the offset does **not**
grow from join to join - each clip re-anchors from absolute positions, so
timing errors don't compound.

`tests/seam_probe.py` is included. Point it at the previous clip's audio and the
new clip's **untrimmed** audio and it scores the join:

```
python tests/seam_probe.py clipA.flac clipB_untrimmed.flac --frames 22 --win-ms 100 --search-ms 60
```

## Limitations

**Sound quality degrades down a chain.** This is the big one. Each clip's
audio is generated from the previous clip's *output*, which was generated
from the clip before it, and so on. Like photocopying a photocopy, losses
compound, and (like most lossy audio compression) the top end goes first.
In practice: timing and tempo stay locked, but after several clips the
audio gets noticeably duller and more muffled. Video degrades far less
visibly. Two loss sources stack per link: the model's own regeneration
smoothing, and an extra pass through the audio VAE's encode/decode cycle.
The `context_latent` input eliminates the second one by slicing the pinned
audio straight from the previous clip's latent - wire it and the VAE
round trip is gone. How much of the muffling that removes is newly
measurable, not yet established; the model's own smoothing remains either
way. Whatever remains: treat long chains as territory to listen to
critically, and consider placing chain restarts at natural musical
transitions where a fresh start won't be noticed.

**A small constant audio offset.** Measurement shows each context-generated
clip's audio sits a fixed ~10 ms late. It is constant - it does not grow
down the chain and does not affect tempo - and it is below the threshold
where lip-sync errors become perceptible, but it is real and unfixed.

**Testing breadth.** Joins have been verified clean on two very different
kinds of material: dense beat-driven electronic music (where timing errors
are most audible) and spoken word via the latent path (where nothing masks
a seam and the ear is least forgiving about artifacts).

**One machine, one configuration.** Everything here was verified on a
single Windows machine at one resolution with one sampler. The math is
self-tested on first inline activation; the perceptual results are one person's
renders.

**ComfyUI's H3 support is young and moving.** The patches depend on the
current shape of ComfyUI's H3 code. They verify those assumptions when a
Contex Loop Context path first opts in and shut down loudly if anything changed,
so the failure mode is
"the node refuses to run after an update," not corrupted output.

**Turn Spectrum off.** Step-skipping optimizers like
ComfyUI-Spectrum-MiniMax-H3 forecast how the model's state evolves across
steps. Pinned rows never evolve, which is a degenerate case for the
forecaster. Keep it disabled for these graphs.

**License.** The H3 community license reportedly does not currently cover
the EU, UK, Korea, or the US. Verify independently before building
anything shipping on this.

## Recommended starting point

`context_length 22, encode_mode video, anchor_mode head, audio_mode
timeline, audio_context_length 22`, Trim node wired for both picture and
sound with `match_tail` on, Spectrum off. That is the configuration every
"it works" claim in this README refers to.

## Status and testing

Built and verified against ComfyUI master as of early August 2026, while
H3 support was days old. Registering the pack does not patch ComfyUI's model
runtime; the math patches self-test against the live ComfyUI code on first
Contex Loop Context execution, and remain behaviorally gated to its private
conditioning markers. The review routes remain idle until a Review Gate runs.
An upstream change surfaces as a clear refusal, not a bad render. The repo also
ships two standalone patch/node tests
that run without ComfyUI or a GPU (only numpy needed), plus a CPU chain
integration test against an adjacent ComfyUI checkout and frontend tests:

```
python tests/_mock_harness.py       # patch logic against a faithful stock model
python tests/_node_smoke_test.py    # the node end to end, R2V refs + save/load
python tests/_chain_smoke_test.py   # timing, recursion, segments, resume, assemble
node tests/_plan_editor_js_test.mjs # scene-editor parsing and exact timing
node tests/_kj_preview_bridge_js_test.mjs # recursive KJ preview ID mapping
node tests/_chain_review_js_test.mjs # review prompt/uint64 edit handling
```

All six should print their checks and finish with a pass line.

## Files

| File | Role |
|---|---|
| `patch_layout.py` | Marker-gated wrapper that lifts the first/last-only keyframe restriction, moves pinned audio onto the clip timeline, and keeps R2V refs aligned. Self-tests on first inline activation. |
| `patch_payload.py` | Marker-gated wrapper that lets Motion Context video and refs coexist while leaving unmarked H3 payloads stock. |
| `nodes.py` | Internal loop context engine and public frame-exact `MiniMaxH3LoopTrim`. The upstream node ids are deliberately not registered. |
| `chain_nodes.py` | The nine MiniMax-specific plan, recursive loop, review gate, segment/checkpoint, resume/manifest recovery, and assembly nodes. |
| `web/` | Opt-in H3 Chain Plan editor, audiovisual review gate, H3-loop/KJ preview bridge, and testable cores. |
| `tests/seam_probe.py` | Measures whether a join's audio is a true continuation, a sound-alike, or drifting. |
| `tests/` | Standalone patch/node tests plus the CPU chain integration test. |

The primary workflow in `example_workflows/` is the disk-backed recursive
Ref2VA loop. Legacy manual demonstrations are retained as credited historical
references and require NikoDemon80's upstream pack for its original node ids;
see the folder README.
