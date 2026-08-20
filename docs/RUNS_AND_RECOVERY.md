# Runs, review, and recovery

## Review Gate

Place **Review Gate** between Segment + Checkpoint and Loop End. Each scene is
persisted before the gate waits, then the gate offers:

- **Approve & continue**
- **Retry scene / seed / length**
- **Reroll seed**
- **Approve & stop**, optionally assembling a partial video

Set Review Gate's optional **candidate_count** above 1 to collect several
different-seed takes before making a decision. Intermediate takes are saved and
rerolled automatically. When the requested count is reached, use **Choose take**
to preview the candidates, then continue or stop with the selected checkpoint.
The chosen take's saved video frames and AV tensors—not the last generated
take—become the context for the following scene. The default value of 1 keeps
the normal one-take review behavior. The widget can be converted to an input
and driven by a regular INT node; the safety limit is 20 candidates per scene.

Notification sound, automatic timeout, and model unloading while waiting are
optional. Drag the bar below the player to resize it; double-click to restore
the default height.

When a Scene Prompt Editor or Rich Scene Prompt Editor is bound to the same
Plan, Review Gate selects the scene under review there automatically. Editor
changes are used by **Retry prompt / seed** or **Reroll seed** through the live
Plan prompt. In 0.5, Review Gate's own prompt field is disabled by default.
Restore it under **Settings → MiniMax H3 Contex Loop → Interface → Review Gate
→ Enable prompt editing inside Review Gate**. When enabled, text explicitly
typed in that field wins for the submitted retry and is synchronized back to
the Plan and connected editor after the server accepts it.

During sampling, the optional floating **Cancel & reroll scene N** control
targets only the active H3 prompt. It waits for confirmed interruption, writes a
new explicit scene seed, moves Loop Start to that scene, preserves a bounded
range end, and queues normally. Once saving or review begins, Review Gate owns
the retry instead.

Disable the floating control under **Settings → MiniMax H3 Contex Loop →
Interface → Cancel & reroll** without affecting Review Gate.

## Resume

For a fresh run:

```text
run_name: choose a new name
start_clip: 1
scene_range: blank
```

To resume scene N, keep the original `run_name` and dependency settings, then
set `start_clip: N`. The loop loads checkpoint N−1 and validates all completed
predecessors. Editing scene N or later is safe; changing an earlier prompt,
seed, timing, source waveform, Plan compatibility setting, or
`generation_fingerprint` invalidates the dependent resume.

Loop Start's `verify_resume_history` switch is enabled by default. Disable it
only when you intentionally want scene N to consume the existing saved scene
N−1 despite a changed Plan. The override skips Plan/history matching; it does
not skip missing-file checks, SHA-256 artifact validation, checkpoint tensor
validation, or metadata's own recorded-history consistency. Consequently, any
new settings that describe the saved predecessor are not retroactively present
in its pixels or AV latent.

Plan-wide continuation mode and context length are the exceptions: they choose
how the next scene consumes its saved predecessor. Changing either does not
alter completed frames or their saved AV latent, so it does not invalidate the
prefix. If the checkpoint's cached decoded tail is shorter than the newly
requested context, the loop re-decodes its complete saved video latent and
extracts the longer tail without regenerating the scene. Explicit per-scene
continuation and context overrides remain part of that scene's history.

Review Gate's checkpoint browser can set up this resume and preview the joined
partial through the selected predecessor.

**Manifest Load** also supports interrupted runs. It discovers the longest
contiguous active checkpoint prefix beginning at scene 1, verifies every scene
and artifact through that point, and emits a partial manifest when later scenes
have not been saved. Connect that output directly to **Assemble** to recover the
finished prefix without sampling again. A missing scene ends the prefix; an
orphaned later checkpoint is never joined across the gap. When every planned
scene is present, the same node emits the normal completed manifest.

### Restore an earlier scene revision

**Refresh** in Review Gate discovers the active checkpoint and every immutable
revision retained for that scene. Choose the scene to resume, then select the
desired version of each predecessor under **Checkpoint history**. Clicking
**Restore & load** validates the selected MP4, safetensors checkpoint, hashes,
shared prompt, and compatibility contract before atomically promoting the
selected prefix. The corresponding prompts, seeds, lengths, steps, and scene
identifiers are restored into the connected Plan, and Loop Start is armed for
the next scene.

The active versions are selected by default. Restoring an earlier version does
not delete the current one, so another revision can be promoted later. Exact
continuation requires the revision's checkpoint metadata and safetensors file;
an MP4 copied from `segments/` or `reviews/` alone cannot recreate the saved AV
latent. When only video survives, use Existing Video Context as a re-encoded
continuation instead.

Retrying, rerolling, and candidate collection intentionally retain earlier
files as immutable revisions; they are recovery points rather than abandoned
temporary files. Inactive leaf revisions can be deleted from the same panel or
the dedicated Checkpoint Manager to reclaim space.
Review Gate now retrieves a fresh server-side deletion preview before asking
for confirmation. Active revisions and revisions with dependent later scenes
cannot be deleted. Cleanup is limited to that revision's segment, safetensors
checkpoint, prompt/audio/blend sidecars, unshared preview, and versioned
metadata; Plan archives, assets, prompt history, assembled exports, and other
revisions are never included.

## Checkpoint Manager

Connect the active Plan output to **MiniMax H3 Checkpoint Manager**. It passes
the Plan through unchanged and never pauses execution, so it can stay between
Plan and the next consumer. The connected Plan preselects its run; the run
selector can inspect any other folder under `output/h3_chains`.

The manager groups immutable scene revisions into inferred branches. A revision
can appear in more than one branch when it is their shared ancestor. Selecting
a revision shows its saved preview, prompt, seed, timing, canvas, storage,
parent, following scenes, and the exact video/audio frame context those
following scenes consume. Older checkpoints derive this graph from predecessor
revision and checkpoint hashes; newly saved checkpoints also carry a stable
branch id and effective context fields.

Deletion is deliberately one scene revision at a time:

1. Select an inactive revision.
2. Inspect its complete file list, estimated reclaimed size, and preserved
   categories.
3. If later revisions depend on it, select and delete those leaf revisions
   first.
4. Confirm the now-safe leaf deletion. If anything changed after the preview,
   the server refuses it and asks for a fresh preview.

This first release does not bulk-delete branches. The leaf-first workflow makes
the exact context consequences visible and avoids silently orphaning later
checkpoints.

## Run Manager

Connect the active Plan output to **MiniMax H3 Run Manager**. It discovers runs
under the ComfyUI host's `output/h3_chains`, including remote Docker hosts.
Select a run and choose **Load selected archive into Plan**; after confirmation
it restores archived prompts and Plan controls without changing graph links.

The two names at the top are deliberately separate:

- **Active Plan** is the connected Plan's current `run_name`. Generation and
  **Save assets to active Plan** use this name.
- **Selected archive** is only the folder highlighted in the browser. Selecting
  it does not change the Plan. **Load selected archive into Plan** is the only
  action that applies its archived prompts and settings.

When both names match, the archive is marked **ACTIVE PLAN**. When they differ,
the selected archive is labeled **not loaded**, so opening an old folder or
inspecting it cannot be mistaken for switching the generation run.

Restore prefers:

1. `api_prompt.json`;
2. `workflow.json`;
3. effective settings derived from `plan.json` for older runs.

The fallback retains exact scene lengths, steps, and seeds even when an old run
did not archive unused default-widget values.

## Archive reference assets

Connect loader outputs to Run Manager's dynamic **Connect loader asset** socket,
up to 12 assets. Classify each as Picture, Video, Audio reference, or Source
track so a short voice reference cannot be confused with a project soundtrack.

- Archive images and audio default on.
- Archive video defaults off because video references can be large.
- Only files inside ComfyUI's input directory are eligible for fallback copies.
- Content-addressing deduplicates unchanged media and retains changed versions.

Restore first uses the original input-relative path. If it is missing and a
fallback exists, Run Manager copies the archived asset into a unique ComfyUI
input filename and updates a compatible loader. Targets are matched by persistent
binding identity, archived node ID/type, then unambiguous compatible loaders.
Ambiguous targets remain unchanged and are reported.

## Run folder contents

```text
output/h3_chains/<run_name>/
├── plan.json
├── workflow.json
├── api_prompt.json
├── manifest.json
├── prompt_history/<scene_id>/
├── segments/clip_0001.<revision>.mp4
├── segments/clip_0001.<revision>.prompt.txt
├── checkpoints/clip_0001.json
├── checkpoints/clip_0001.<revision>.json
├── checkpoints/clip_0001.<revision>.safetensors
├── generated_audio/
└── final/<filename>.mp4
```

Regenerating a scene updates its active checkpoint pointer but retains all
earlier MP4s, prompt sidecars, metadata, safetensors, and generated WAVs. Each
revision records what it supersedes.

Workflow and API graph metadata are embedded in segment/final files using
ComfyUI's standard tags. `workflow.json` is the preferred file to drag back
into ComfyUI; `plan.json` remains the authoritative effective render record.
Keep run folders private when workflows contain credentials.

## Assembly

Assemble accepts completed or partial manifests, including an interrupted
prefix reconstructed by Manifest Load. Its filename supports date
tokens such as `%date:yyyy-MM-dd%`, `%year%`, `%month%`, `%day%`, `%hour%`,
`%minute%`, and `%second%`. Existing files are never overwritten; numbered
suffixes are added automatically.

### Recovery blend schedules

`blend_schedule` can override the Plan's global visual blend only during
assembly. `plan` preserves the recorded setting. A comma-separated schedule is
applied to scene boundaries in timeline order: `5,30` uses five frames for the
first join and thirty for every later join because the last value repeats.
`0` produces hard cuts. This does not change checkpoints, prompts, seeds, or
generated frames.

When the requested boundary fits inside the saved blend MP4, assembly reuses
that artifact directly. If it requests more overlap than Segment Save retained,
connect the original MiniMax H3 video VAE to `blend_video_vae`. Recovery then
re-decodes the existing safetensors checkpoint into a temporary lossless RGB
video and deletes it after assembly. Diffusion is never rerun. The final video
still receives the one H.264 encode required by any pixel-space crossfade.

Each scheduled value must not exceed that incoming scene's repeated context.
For example, a chain whose first join has five context frames and later joins
have thirty-nine can use `5,30`; requesting thirty at the first join is rejected.

Enable `copy_to_output` to keep the canonical final in the run folder and also
publish an MP4 into the regular ComfyUI output tree. `output_subfolder` is
relative to that output root, supports nested folders and the same date tokens,
and may be empty to place the copy directly in `output/`. The existing
`filename` value is used for both copies, and collisions are versioned.

## Re-decode checkpoints to PNG

Connect a manifest and the original H3 video VAE to **Export PNG Sequence**. It
verifies each safetensors checkpoint, decodes one scene at a time, removes the
repeated overlap, and writes a continuous 8-bit RGB PNG sequence plus
`export.json` under:

```text
output/h3_chains/<run_name>/frames/<export_name>/
```

PNG compression is lossless. Use the same VAE, ComfyUI version, precision, and
decode settings for the closest reconstruction. The checkpointed latent is
exact, but a new VAE decode is not guaranteed to be bit-identical to an older
decode made under different settings.
