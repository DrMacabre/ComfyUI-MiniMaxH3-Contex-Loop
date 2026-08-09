# MiniMax H3 Loop Plan Formatting Guide

This guide belongs to `ComfyUI-MiniMaxH3-Contex-Loop` and describes the JSON
accepted by `MiniMax H3 Contex Loop Plan` (`MiniMaxH3ChainPlan`), including
scene lengths, prompts, seeds, steps, audio timing, and resume-safe settings.

## Visual editor or raw JSON

`H3 Chain Plan` includes a scene-card editor. Write shared continuity text and
scene prompts as normal multiline text; the editor stores them as readable
JSON line arrays automatically. Drag scenes to reorder them, duplicate or
delete cards, and choose inherited duration, seconds, or exact H3 frames. The
timing label on every card shows raw and delivered frames, while the header
shows total delivered runtime. Scene cards receive distinct colors
automatically; use the small header swatch to customize one, or double-click
the swatch to restore its automatic color. Colors are UI-only and do not alter
the plan or checkpoint compatibility.

Inside a prompt, type `@` or click **@ Reference** to insert a MiniMax
`<Picture N>`, `<Video N>`, or `<Audio N>` tag. Select dialogue text and type
`#`, or click **# Dialogue**, to wrap it in `<d>...</d>`. These interactions
are authoring shortcuts only; they produce ordinary MiniMax prompt text.

Use the editor's **JSON** button when you need to inspect, paste, import, or
export the underlying plan. The JSON format below remains the runtime contract
and existing plans are backward compatible.

## Copy/paste workflow note

The following block is intentionally compact enough to paste into a ComfyUI
Note node:

```text
H3 LOOP PLAN — QUICK FORMAT

Use the built-in H3 Chain Plan scene editor, or open its JSON panel and paste
valid JSON. Use double quotes, no comments, and no trailing commas.

{
  "prompt_prefix": "Global subject, wardrobe, style and continuity rules.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "intro",
      "prompt": [
        "Use <Picture 1> for the subject's identity and physical features.",
        "Her wardrobe remains unchanged throughout the sequence.",
        "",
        "Begin with an opening tracking shot backstage.",
        "End while she is opening the corridor door."
      ],
      "seed": 123
    },
    {
      "id": "street",
      "prompt": [
        "Continue through the already-opening door without resetting her stride.",
        "Keep the incoming camera direction, lighting and subject pose.",
        "",
        "Move from the corridor into the street.",
        "End with the camera beginning a left orbit."
      ],
      "duration_seconds": 10,
      "steps": 24,
      "seed": 456
    },
    {
      "id": "outro",
      "prompt": [
        "Continue the unfinished left orbit from the previous scene.",
        "Resolve the performance and finish on a calm wide composition."
      ],
      "length": 124
    }
  ]
}

SCENE OVERRIDES
- prompt can be one string OR an array of readable lines. The node joins array
  entries with real line breaks. Use an empty string entry for a blank line.
- duration_seconds: requested generated duration; rounded UP to H3's 17k+5 grid.
- length or frames: exact raw frame count; must be 5, 22, 39, 56...3592.
- steps: sampler steps for this scene, 1–10000.
- seed: fixed uint64 seed. Omit it for a deterministic seed from base_seed.
- id: unique scene name used by checkpoints. Changing it can change an auto seed.
- prompt: scene-specific text. It may be blank or omitted when prompt_prefix
  (or global_prompt) is non-empty; otherwise a prompt is required.

LENGTH AT 24 FPS, context=22, anchor=head
- 5 seconds  -> raw 124 frames; clip 1 delivers 124, later clips deliver 102.
- 10 seconds -> raw 243 frames; clip 1 delivers 243, later clips deliver 221.
- 15 seconds -> raw 362 frames; clip 1 delivers 362, later clips deliver 340.
Later clips lose the 22 repeated context frames after Trim. Use length for
frame-exact control. Every non-final shot must deliver at least context_length.

PRECEDENCE
shot value > JSON defaults > H3 Chain Plan node defaults.

RECOMMENDED PLAN SETTINGS
- width/height: multiples of 32; 960x544 is a good starting point.
- context_length: 22
- encode_mode: video
- anchor_mode: head
- crop: disabled
- audio_mode: source_track for music videos
- audio_context_length: 0 in source_track; 22 for generated-audio continuity
- segment_crf: 18–20

RUN / RESUME
- New run: unique run_name and Loop Start start_clip=1.
- Resume at scene N: keep the same settings and run_name; set start_clip=N.
- The Review Gate can discover saved checkpoints and set start_clip for you:
  Refresh, select Resume scene N, then press Load checkpoint.
- Approve & stop can join all accepted scenes into a partial MP4. Checkpointed
  audio is the default; wire the full song to source_audio to use source audio.
- Optional model unloading releases VRAM while the gate waits. Continuing must
  reload models; stopping ends the execution without a reload.
- Changing a completed scene's prompt, seed, length, model settings, references,
  or source audio invalidates its checkpoint history.
- Change generation_fingerprint whenever model, VAE, LoRA, references, CFG,
  scheduler, or another generation dependency changes.

SOURCE-TRACK WIRING
Wire the same Load Audio output to Loop Start, Current Shot and Assemble.
The source song must cover the complete delivered video duration.
```

## Complete JSON shape

`plan_json` accepts either a plan object or a bare list of shots:

```text
Plan = {
  "prompt_prefix"?: string | string[],
  "global_prompt"?: string | string[], // alias of prompt_prefix
  "defaults"?: {
    "duration_seconds"?: number,
    "steps"?: integer
  },
  "shots": Shot[]
}

Shot = string | {
  "id"?: string,
  "prompt"?: string | string[],
  "duration_seconds"?: number,
  "length"?: integer,
  "frames"?: integer,             // alias of length
  "steps"?: integer,
  "seed"?: integer | digit string
}
```

The notation above explains the structure; it is not JSON because it contains
comments and `?` markers. Actual `plan_json` must be strict JSON:

- use double quotes around keys and strings;
- do not include comments;
- do not leave a trailing comma;
- encode line breaks inside prompts as `\n`;
- include between 1 and 128 shots.

## Top-level plan fields

| Field | Required | Meaning |
|---|---:|---|
| `shots` | Yes | Ordered list of scenes. Each entry can be an object or a prompt string. |
| `prompt_prefix` | No | String or array of lines prepended to every scene prompt, separated by one blank line. Use it for identity, wardrobe, style, camera, and continuity rules shared by all scenes. |
| `global_prompt` | No | Alias for `prompt_prefix`. `prompt_prefix` wins when both are present. |
| `defaults.duration_seconds` | No | JSON-level default scene duration. Overrides the node's `default_duration_seconds`. |
| `defaults.steps` | No | JSON-level default sampler steps. Overrides the node's `default_steps`. |

Precedence is always:

```text
per-shot value > JSON defaults > H3 Chain Plan node value
```

## Per-scene fields

| Field | Required | Rules and behavior |
|---|---:|---|
| `prompt` | Conditional | Scene-specific string or array of strings. It may be blank or omitted when `prompt_prefix`/`global_prompt` is non-empty. Array entries are joined with real newlines; use `""` for a blank line. The shared prefix is prepended automatically. |
| `id` | No | Unique checkpoint identifier. Defaults to `clip_0001`, `clip_0002`, etc. Unsupported filename characters become `_`; the result is limited to 96 characters. |
| `duration_seconds` | No | Positive requested raw generation duration. It is rounded up to a valid H3 frame count. Ignored when `length` or `frames` is present. |
| `length` | No | Exact raw frame count. Must be between 5 and 3592 and satisfy `length % 17 == 5`. |
| `frames` | No | Alias for `length`. `length` wins when both are present. |
| `steps` | No | Sampler steps for this scene, from 1 to 10000. |
| `seed` | No | Fixed unsigned 64-bit seed, from 0 to 18446744073709551615. A decimal digit string is also accepted and lets browsers preserve values above JavaScript's exact integer range. When omitted, the seed is derived deterministically from `base_seed`, scene index, and scene `id`. |

A shot can also be only a prompt string:

```json
{
  "shots": [
    "Opening scene.",
    "Continue through the doorway.",
    "Finish on a wide sunrise shot."
  ]
}
```

String shots use automatic IDs, the default duration and steps, and derived
seeds.

## Setting scene length

MiniMax H3 runs at 24 fps and accepts only raw lengths on this grid:

```text
5, 22, 39, 56, 73, ... 3592 frames
```

Equivalently:

```text
length % 17 == 5
```

### Use seconds for convenience

```json
{
  "id": "closeup",
  "prompt": "Continue into a close tracking shot.",
  "duration_seconds": 5
}
```

The node converts seconds using:

```text
requested_frames = ceil(duration_seconds × 24)
raw_frames = the next frame count where raw_frames % 17 == 5
```

It always rounds up. The generated duration can therefore be longer than the
number entered.

| Requested | Raw frames | Raw duration | Delivered by clip 1 | Delivered by later clip with 22-frame head context |
|---:|---:|---:|---:|---:|
| 0.2 s | 5 | 0.208 s | 5 frames / 0.208 s | Invalid: not longer than the overlap |
| 1 s | 39 | 1.625 s | 39 frames / 1.625 s | 17 frames / 0.708 s |
| 5 s | 124 | 5.167 s | 124 frames / 5.167 s | 102 frames / 4.250 s |
| 10 s | 243 | 10.125 s | 243 frames / 10.125 s | 221 frames / 9.208 s |
| 15 s | 362 | 15.083 s | 362 frames / 15.083 s | 340 frames / 14.167 s |
| 30 s | 736 | 30.667 s | 736 frames / 30.667 s | 714 frames / 29.750 s |

### Use frames for exact control

```json
{
  "id": "outro",
  "prompt": "Resolve the movement and end the performance.",
  "length": 124
}
```

Use `length` when exact H3 timing matters. Invalid examples include `120`,
`240`, and `360`; the nearby valid values are `124`, `243`, and `362`.

### Raw length versus delivered length

With the recommended `anchor_mode: head`, the beginning of every continuation
contains the previous scene's repeated context. `MiniMax H3 Contex Loop Trim`
removes that overlap:

```text
clip 1 delivered frames = raw_frames
later delivered frames  = raw_frames - context_length
```

For `context_length: 22`, a later scene with `length: 362` contributes 340 new
frames, or 14.167 seconds, to the final video. The source-audio window still
covers all 362 raw frames and begins 22 frames before the prior delivered end,
so its overlap matches the repeated picture context.

With `anchor_mode: before`, no repeated head is delivered, so every scene
delivers its complete raw length. This mode is retained for experimentation;
`head` is the tested and recommended mode.

Every non-final scene must deliver at least `context_length` frames so the next
scene has enough context. The plan rejects shorter predecessors before render.

## Prompt formatting

For human editing, use an array of lines instead of writing escaped `\n`
characters. The node joins entries with real newlines. Use an empty string
entry when you want a blank line:

```json
{
  "shots": [
    {
      "id": "arrival",
      "prompt": [
        "Use <Picture 1> for her facial identity, hairstyle, skin tone, age, body proportions, and distinctive physical features.",
        "Her wardrobe is the outfit defined here.",
        "",
        "Throughout every scene S1 wears the same fitted thigh-length dove-grey designer cocktail dress in opaque structured fabric with a deliberate low cleavage cutout, carries a small black designer handbag, and wears black high-heeled pumps.",
        "",
        "<Subject 2> (S2) enters from camera right."
      ]
    }
  ]
}
```

This reaches MiniMax as:

```text
Use <Picture 1> for her facial identity, hairstyle, skin tone, age, body proportions, and distinctive physical features.
Her wardrobe is the outfit defined here.

Throughout every scene S1 wears the same fitted thigh-length dove-grey designer cocktail dress in opaque structured fabric with a deliberate low cleavage cutout, carries a small black designer handbag, and wears black high-heeled pumps.

<Subject 2> (S2) enters from camera right.
```

Put stable information in `prompt_prefix` and only scene-specific changes in
each `prompt`; both fields accept the same readable array format:

```json
{
  "prompt_prefix": "<Subject 1> keeps the same face, yellow-and-pink hair, black cropped T-shirt, ripped jeans and silver chain. Photorealistic continuous music-video take with no cuts.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "backstage",
      "prompt": "Track backward as <Subject 1> walks through the backstage room. End with her opening the corridor door."
    },
    {
      "id": "corridor",
      "prompt": "Continue the same stride and camera movement through the already-opening door. End with the camera beginning a left orbit."
    }
  ]
}
```

When the same complete prompt should drive every scene, scene prompts can be
empty or omitted:

```json
{
  "prompt_prefix": "The complete shared MiniMax prompt used for every scene.",
  "shots": [
    {"id": "scene_01", "length": 362},
    {"id": "scene_02", "length": 362}
  ]
}
```

For seamless results, each continuation prompt should explicitly preserve the
incoming action, camera direction, subject pose, lighting, and unfinished
movement. End each scene with an action still in progress, then begin the next
prompt by continuing that exact action.

## Seeds and steps

Use fixed seeds when a plan must be exactly reproducible:

```json
{
  "shots": [
    {
      "id": "scene_01",
      "prompt": "Opening scene.",
      "seed": 983590410766495,
      "steps": 20
    }
  ]
}
```

When `seed` is absent, a deterministic seed is derived from:

```text
base_seed + scene index + scene id
```

The same plan and `base_seed` produce the same derived seeds. Changing a scene
ID or moving it to another position changes its derived seed.

## H3 Chain Plan node settings

| Setting | Accepted values | Recommended use |
|---|---|---|
| `run_name` | Filename-safe text; normalized to at most 96 characters | Give each independent render a unique name. Keep it unchanged only when resuming. |
| `generation_fingerprint` | Any stable version string | Include model, VAE, LoRA, global-reference, CFG, sampler, and scheduler versions. Change it when any external generation dependency changes. |
| `width`, `height` | Positive multiples of 32, UI range 32–4096 | `960 × 544` is the supplied long-form workflow setting. |
| `context_length` | `1`, `5`, `22`, or `39` | Use `22` for the tested balance of continuity and delivered footage. |
| `encode_mode` | `video` or `frames` | Use `video`. It preserves motion inside the VAE latent and is more efficient. |
| `anchor_mode` | `head` or `before` | Use `head`; wire `trim_frames` into MiniMax H3 Contex Loop Trim. |
| `crop` | `disabled` or `center` | Use `disabled` when references and output already share the intended framing. |
| `audio_mode` | `source_track`, `generated_audio`, or `source_plus_timeline` | Use `source_track` for music videos. |
| `audio_context_length` | `0`–`240` frames | In generated-audio modes, `0` follows the video context length; `22` is the tested explicit value. It is unused for video-only context in `source_track`. |
| `default_duration_seconds` | Positive seconds, up to 149.667 s | Used only when JSON defaults and the scene both omit a length. |
| `default_steps` | `1`–`10000` | Used only when JSON defaults and the scene both omit steps. |
| `base_seed` | Unsigned 64-bit integer | Source for deterministic seeds when a scene omits `seed`. |
| `segment_crf` | `0`–`51` | H.264 checkpoint-segment quality. Lower is higher quality and larger. Start around `18`–`20`. |

## Audio modes and formatting

### `source_track`

Recommended for a music video driven by one song.

- Wire the same full `AUDIO` value to Loop Start, Current Shot, and Assemble.
- Current Shot slices a frame-exact raw audio window for each Ref2VA scene.
- Motion Context carries picture context only.
- Assemble muxes the original source track over the stitched video.
- The song must be at least as long as the total delivered video.
- A genuinely silent placeholder may be shorter; Loop Start detects it and
  zero-pads scene slices and final assembly to the required duration.
- The waveform is hashed; changing or miswiring the song is rejected.

### `generated_audio`

- No source track is required.
- Chain Context carries the preceding H3 audio latent on the timeline.
- Wire trimmed decoded audio into Segment Save.
- Assemble concatenates the checkpointed generated audio.
- MiniMax H3 Contex Loop Trim must keep `match_tail` enabled for exact sample counts.

### `source_plus_timeline`

- Ref2VA receives the frame-exact source-song window.
- Chain Context also carries the preceding generated audio latent.
- This mode is experimental.
- Assemble selects the source track when `audio_source` is `plan`.

## Starting, resuming, and changing a plan

For a fresh render:

```text
run_name: choose a new name
start_clip: 1
```

To resume from scene N:

```text
run_name: keep the original name
start_clip: N
```

The Start node loads the checkpoint from scene `N - 1` and validates every
completed predecessor. You may edit scene N and later scenes. Changing any of
the following for an earlier completed scene invalidates resume:

- prompt, seed, steps, duration, or length;
- width, height, context, crop, anchor, encoding, or audio mode;
- source audio waveform;
- `generation_fingerprint`.

The checkpoint browser embedded in the Review Gate is a shortcut for this
setup. It lists saved predecessor slots under the current `run_name`, changes
Loop Start's `start_clip`, and leaves the same validation to the next queued
execution. Loading previews the joined partial through that checkpoint when
available, or the saved predecessor scene otherwise. **Approve & stop** also
writes a partial joined video through the accepted scene when
`assemble_partial_on_stop` is enabled.

Model, VAE, LoRA, references, CFG, sampler, and scheduler sit outside the Plan
node, so the chain cannot inspect them directly. Record them in
`generation_fingerprint` and change that string whenever they change.

## Complete music-video template

```json
{
  "prompt_prefix": "<Subject 1> is the same performer in every scene. Preserve facial identity, hair, wardrobe, proportions and accessories. Photorealistic high-energy music video shown as one uninterrupted moving-camera take. No cuts. Continue subject motion, camera momentum, lighting and geometry across every boundary.",
  "defaults": {
    "duration_seconds": 15,
    "steps": 20
  },
  "shots": [
    {
      "id": "clip_01",
      "prompt": "Begin in a backstage room. Track backward as <Subject 1> approaches a lit doorway. End while the door is opening.",
      "seed": 1001
    },
    {
      "id": "clip_02",
      "prompt": "Continue through the already-opening doorway without resetting her stride or the camera. Follow into a concrete corridor. End as the corridor begins transforming.",
      "seed": 1002
    },
    {
      "id": "clip_03",
      "prompt": "Continue the corridor transformation and the same forward motion. Move into a wide exterior. End with the camera starting to rise.",
      "duration_seconds": 10,
      "steps": 24,
      "seed": 1003
    },
    {
      "id": "clip_04",
      "prompt": "Complete the rising camera move, resolve the performance, and finish on a calm wide composition.",
      "length": 124,
      "seed": 1004
    }
  ]
}
```

## Common formatting errors

| Error | Fix |
|---|---|
| Invalid JSON | Use double quotes, remove comments, and remove trailing commas. |
| Empty prompt | Provide a non-empty scene `prompt`, or provide a non-empty `prompt_prefix`/`global_prompt` that the scene can use alone. |
| Duplicate ID | Give every scene a unique `id`. |
| Invalid exact length | Use a value from the `17k+5` grid, such as `124`, `243`, or `362`. |
| Continuation is too short | Make its raw length greater than `context_length`; every non-final scene must also deliver enough frames for the next context. |
| Unexpected scene duration | Remember that seconds round up and later `head` clips lose the repeated context after trimming. Inspect Current Shot's `raw` and `delivered` status. |
| Resume rejected | Restore the prior completed-scene settings and source track, or start a new run from clip 1 with a new `run_name`. |
| Source audio too short | Use a longer song, shorten the plan, or choose a non-source audio mode. Truly silent placeholder audio is padded automatically; non-silent audio is never padded. |
| Final audio/video drift | Wire both decoded streams through MiniMax H3 Contex Loop Trim and leave `match_tail` enabled. It truncates excess audio or zero-pads a fractional-step shortage. |
