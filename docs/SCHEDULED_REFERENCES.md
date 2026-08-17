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

## Patch priority

If an older compatible H3 Motion Context copy wins process load order, insert
**MiniMax H3 Patch Priority** between Ref2VA/I2V conditioning and Contex Loop
Context. It passes conditioning unchanged while claiming only the recognized
shared patch family. Known H3-Multishot and SolAttn hooks remain active; unknown
wrappers produce a clear error rather than being overwritten.
