# Scheduled references

Use Scheduled Ref2VA when a picture, video, or audio reference should apply to
selected scenes rather than every recursive iteration.

```text
Scheduled Picture Ref ─→ Scheduled Video Ref ─→ Scheduled Audio Ref
                                                    ↓
Current Shot ─ prompt, clip_index, clip_count ─→ Scheduled Ref2VA
Current Shot ─ width, height, length ───────────→ Scheduled Ref2VA
CLIP + video VAE + audio VAE ──────────────────→ Scheduled Ref2VA
```

## Scene selectors

| Value | Active scenes |
|---|---|
| blank, `all`, or `*` | every scene |
| `3` | scene 3 |
| `1:5` | scenes 1 through 5 |
| `1,3,5:8` | scenes 1, 3, and 5 through 8 |

Disjoint selectors are safe for references because they do not skip the loop's
motion dependency.

## Aliases and native labels

Aliases such as `@hero_face`, `@performance`, and `@voice` are optional
authoring conveniences. The wrapper replaces active aliases with the native H3
label assigned in that scene. It never inserts definitions or rewrites semantic
prompt text.

Native numbering is compact and independent by media type:

1. active pictures become `<Picture 1>`, `<Picture 2>`, and so on;
2. active videos receive independent `<Video N>` labels;
3. paired video soundtracks are presented immediately before their video and
   consume `<Audio N>` labels;
4. standalone audio continues the independent audio numbering.

If an earlier picture becomes inactive, a later `@hero` may compile to
`<Picture 1>`. This is why aliases are safer for changing schedules. Core
workflows may continue to use native labels directly.

Write the meaning of every reference in the Plan prompt itself:

```text
subject_definitions:
<Subject 1> uses @hero_face for facial identity and @performance for movement.
```

## Compliance policies

- **strict** compiles valid active aliases and stops on unresolved/inactive tags
  or invalid scheduled media.
- **soft** compiles valid aliases, leaves unresolved prompt tags intact, logs a
  warning, and continues.
- **disabled** passes the prompt and all `@tags` through unchanged. Scheduler
  validation becomes warning-only; unusable media is omitted and excess slots
  are capped to stock H3 limits.

Errors outside the scheduler remain real errors, including invalid model/VAE
wiring, sampling failures, continuation tensor incompatibility, and checkpoint
integrity failures.

## Preview and insertion

The Scene Prompt Editor's **@ Reference** tray shows only sources active for
the selected scene. Hover a loader-backed tag to preview image, video, or audio,
then click to insert it. Audio never autoplays.

## Tagged semantic picture anchors

The prompt-driven **Tagged** route also accepts `#picture[2.50s]`. This presents
the registered Tagged Picture to Qwen at an approximate scene-local timestamp
without adding another native VAE reference. It is useful for reinforcing a
replacement character's identity later in a shot:

```text
<Subject 1> is the replacement performer defined by @replacement.
#replacement[0.00s] #replacement[2.50s] #replacement[4.75s]
```

`@replacement` and `#replacement[...]` have distinct jobs and may be used
together. The `@` form is a native Ref2VA picture. The `#` form is Qwen-only
semantic reinforcement. A `#` anchor accepts a Tagged Picture only; its time
must fall inside the current scene. It is an approximate semantic checkpoint,
not an exact frame, pose, spatial mask, motion control, or continuation seam.
Start with two or three sparse anchors—too many repeated pictures can resist
the source video's changing pose.

### Picture storyboard mode

Set Tagged Ref2VA's `semantic_anchor_mode` to `picture_storyboard` to compile
the same `#picture[time]` syntax differently. Each distinct tagged image is
added once as a separate Qwen-only `<Picture N>`, and the compiler adds an
approximate scene-relative timing sentence for every requested time. No image
is VAE encoded, spatially fused, or inserted into a fixed generated frame.

This mode gives Qwen a high-detail visual shot plan while H3 remains free to
invent motion and transitions. `timestamped_video` remains the default and is
better for sparse temporal reinforcement. Storyboard mode is useful for a
sequence of compositions or appearances, but its textual timing is softer.

`semantic_anchor_size` accepts 384, 512, 768, 1024, 1280, or source. Higher
values preserve more face, wardrobe, prop, and environment detail at the cost
of longer Qwen conditioning and greater VRAM/runtime pressure. Prefer 512 or
768 generally, 1024 for important detailed anchors, and 1280 for a small number
of critical stills.

With core Ref2VA, the tray previews media and inserts native labels. With core
Image to Video it exposes first and last frames as `<Picture N>` according to
the active keyframes.

## Resume fingerprints

For static loaders, connect `schedule_fingerprint` to Plan's
`generation_fingerprint`. Changing media bytes, tags, or selectors then
invalidates incompatible checkpoints.

Do not create a fingerprint cycle when a scheduled entry consumes Current Shot,
such as `source_audio_slice`. Source-track mode already fingerprints the full
source waveform at Loop Start.

## Automatic deferred-upscale cache

Tagged and Scheduled Ref2VA enable `cache_for_upscale` by default. On the first
execution of each scene, the wrapper stores the native H3 picture/video/audio
reference blocks after VAE encoding, together with only the resized Qwen image
or 2 fps video presentation needed to tokenize the same compiled prompt later.
The cache is content-addressed by the registry fingerprint plus the scene's
prompt, frame contract, canvas, and reference sizing mode. Ref2VA first writes
to a reusable global staging store because it does not require a Plan or
`run_name` input. Segment Save then hard-links (or copies when linking is not
available) the verified tensors and publishes authoritative metadata inside
the corresponding run:

```text
output/h3_chains/<run-name>/reference_cache/
  scene_0001.<scene-contract>.safetensors
  scene_0001.<scene-contract>.json
```

The standalone deferred-upscale workflow reads `generation_fingerprint` from
the selected checkpoint branch and restores the matching scene automatically.
It does not need the source Plan or any original reference-media connection.
The checkpoint points only to the run-local descriptor, making the run folder
self-contained for copying, backup, and later upscale. The safetensors file is
SHA-256 verified before use. Disable
`cache_for_upscale` only when the extra reference encode and disk cache are not
wanted. Existing checkpoints made before this feature have no cache; the
upscale conditioning node can either fall back to text-only conditioning or
raise an explicit error.

Checkpoints made during the earlier global-cache-only implementation are
adopted automatically on their next complete-branch selection in Checkpoint
Manager. The verified tensor is hard-linked or copied into the run-local cache;
the original `output/h3_reference_cache/` object is deliberately left intact.
No source render or manual file move is required.

## Patch priority

If an older compatible H3 Motion Context copy wins process load order, insert
**MiniMax H3 Patch Priority** between Ref2VA/I2V conditioning and Contex Loop
Context. It passes conditioning unchanged while claiming only the recognized
shared patch family. Known H3-Multishot and SolAttn hooks remain active; unknown
wrappers produce a clear error rather than being overwritten.
