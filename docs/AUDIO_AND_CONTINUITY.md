# Audio and continuity

## Choose an audio policy

Version 0.5 separates three independent decisions:

| Axis | Values | Meaning |
|---|---|---|
| Final audio | `generated`, `source`, `none` | What Assemble places in the final MP4 |
| Source reference | `on`, `off` | Whether the exact active source window guides H3 |
| Generated continuity | `on`, `off` | Whether the previous sampled audio latent continues into the next scene |

For a prerecorded song or dialogue performance that must remain exact, choose
Source final audio and enable Source reference. For a short voice/timbre
reference where H3 should generate new words, choose Generated final audio and
schedule that clip as an ordinary tagged audio reference.

Saved 0.4 modes migrate without changing behavior:

| Legacy `audio_mode` | Final | Source reference | Generated continuity |
|---|---|---|---|
| `generated_audio` | generated | off | on |
| `source_track` | source | on | off |
| `source_plus_timeline` | source | on | on |

These descriptions apply to `guide`, `tone_carry_guide`, `latent_guide`, and
`tapered_guide`.
Tone Carry Guide uses the RGB/VAE route and applies the predecessor's saved,
direct boundary-tone curve before encoding its context. It falls back to clean
Guide when no coherent curve was detected and never silently takes the direct
video-latent path.
When an older checkpoint predates this curve metadata, resume recovers it from
the two existing scene videos. The saved checkpoint and sampled AV latent are
reused unchanged; diffusion is not rerun.
Latent Guide reuses the generated predecessor's sampled video-latent tail
directly, while imported or incompatible context falls back to the normal
RGB/VAE Guide route. Tapered Guide changes only the disposable video context
passed to the Guide VAE. In the
experimental `masked_av`, `tapered_av`, and `feathered_av` modes, Chain Context always places
a video prefix inside the target latent. With Generated continuity on it also
places the matching audio prefix; `masked_av` protects that complete prefix and
`tapered_av` protects a disposable video-only latent-noise copy of that prefix;
`feathered_av` progressively denoises its final latent steps. With Generated
continuity off, the audio mask remains fully open even when final assembly uses
`source_track`. For recursive scenes, enabled audio carry copies the previous
sampler's audio latent directly. For scene 1 after Existing Video Context,
carrying imported audio requires source audio and the H3 audio VAE.

The 0.5 **Soft AV** preset selects `audio_feathered_av`: all picture-prefix
steps remain exact. With Generated continuity on, only the final eight carried
audio ticks are released with a half-cosine ramp. With Generated continuity
off, the target audio stays fully denoisable and paired source audio spans the
complete raw scene window instead of inheriting the delivered-video window.
This is the tested upstream AV extension recipe. The older
dual-stream `feathered_av` remains an Expert override for compatibility.

AV prefixes must end on both native clocks: 39, 90, 141, 192, or 243 frames.
The normal 39-frame prefix maps exactly to 12 video latent steps and 65 audio
steps; 22 frames maps to 36.666... audio steps and is rejected before model
loading. At 39 frames, expert `feathered_av` fully protects the first 8 video /
42 audio steps and ramps the final 4 video / 23 audio prefix steps.

Transition Policy controls the incoming boundary: Cut carries no picture,
Guide uses 22 clean RGB/VAE guide frames, Tone Carry Guide uses the same RGB
span with the predecessor's detected tone correction, Latent Guide uses the
same span from the saved sampled video latent, Detail Guide uses the same span with an
eight-frame chroma-noise exit taper, Detail AV uses a protected disposable
39-frame video-latent copy with matched-variance Gaussian noise tapering from
0.30 to a completely clean boundary while leaving audio exact, Hard AV uses a
protected 39-frame prefix,
and Soft AV keeps the picture exact while feathering only a carried-audio exit.
With Generated continuity off, both AV presets carry picture only.
Detail AV v2 is fixed to 39 frames. Its seed and complete recipe enter the
incoming-boundary dependency fingerprint, its predecessor checkpoint is never
mutated, and the entire treated prefix is trimmed before delivery. Advanced
mode may pair either experimental Guide with another Guide context length; 22
is the published baseline. Mixed plans must still use
encode/anchor settings compatible with every AV-mask scene.

### Scheduled boundary spatial proxy

`context_spatial_proxy` is an optional **per-scene incoming-boundary** setting.
It is off when absent, so it can be scheduled only where a long chain begins
to burn in or needs a controlled spatial reset:

```json
{
  "id": "scene_4",
  "continuation_mode": "masked_av",
  "context_length": 39,
  "context_spatial_proxy": "latent_5_6"
}
```

`rgb_5_6` is available for Guide, Tone Carry Guide, and Detail Guide. It
downscales only the copied RGB context (1376×768 becomes 1152×640); Motion
Context restores that copy to the target geometry before VAE encoding.
`latent_5_6` is available for AV modes. It downscales and restores only the
copied video-prefix latent (86×48 becomes 72×40 and returns to 86×48). It does
not filter the paired audio prefix. Neither mode resizes generated frames,
saved checkpoints, predecessor state, or assembly output. The fixed recipe is
stored in the incoming-scene dependency, so enabling it for scene 4 leaves
scenes 2 and 3 valid but requires scene 4 and its successors to be regenerated.

## Source Timeline wiring

Register picture and sound once. New workflows pass a typed descriptor instead
of repeating a decoded full-track AUDIO wire:

```text
Load Video ─┐
            ├→ Source Timeline ─┬→ Preflight / Plan Studio
Load Audio ─┘                   └→ Loop Start → Current Shot
                                                   └→ scene-local source slice

Loop End manifest → Assemble (recovers the timeline descriptor)
```

Current Shot requests each overlap-aware scene window from the descriptor.
Loop Start fingerprints the source so changed media cannot silently resume old
checkpoints. Path-backed video and audio remain lazy; only the active scene is
decoded. A tensor-only AUDIO input is normalized once into a run-owned file.
The source must cover the required delivered timeline; Preflight reports the
exact shortfall and last complete scene before model loading.

The 0.4 Lazy Motion AV Loader fan-out remains accepted as a compatibility route:

```text
Lazy Motion AV Loader source_video ─┬→ Tagged Motion Ref source_video
                                    └→ Run Manager asset
Lazy Motion AV Loader source_audio ─┬→ Loop Start
                                    ├→ Current Shot
                                    ├→ Tagged Audio Ref
                                    └→ Assemble
Lazy Motion AV Loader skip frames ───→ Tagged Motion Ref skip frames
```

The native VIDEO remains disk-backed. The loader decodes only the complete
post-skip audio track, which is still required: Loop Start establishes its
fingerprint and Current Shot maps exact Plan frame windows onto its sample
clock for H3 audio-latent alignment. Scene-local paired audio from the tagged
motion reference does not replace this master track.

For new workflows, Source Timeline performs that registration without decoding
the complete audio track or requiring the downstream fan-out.

### Tagged Ref2VA source timeline

Current Shot's source slice may feed a standalone Tagged Audio Ref. Keep the
registry fingerprint that returns to Plan independent of that downstream slice:

```text
Plan → Loop Start → Current Shot → Tagged Audio Ref → Tagged Ref2VA
  ↑                                                     │
  └──────── picture/reference registry fingerprint ─────┘
```

The canonical topology is:

```text
Load Audio → Source Timeline → Loop Start → Current Shot
                                             ├→ source_audio_slice → Tagged Audio Ref
                                             └→ state ─────────────→ Tagged Ref2VA
```

The structured scene dependency records the canonical PCM window, so that
scene—not unrelated future audio—is invalidated when the source changes. Do not
return the slice-derived audio fingerprint to Plan, because that would create a
real graph cycle. Current Shot's optional alignment switch changes only the
reference slice.

## Experimental reference-grid alignment

For 362 video frames, the exact picture duration is 15.083333 seconds. Stock H3
creates 603 target audio steps, while an exact-duration audio reference reaches
604 steps after audio-VAE padding.

Current Shot's `align_audio_reference` switch shortens only its Ref2VA output:

```text
362-frame source window: 15.083333 s
aligned reference slice: 15.070000 s
reference audio latents: 603, with a 5 ms padded tail in the final step
```

The exact 15.075-second latent boundary still reproduced visual duplication in
testing; 15.070 seconds did not. The switch therefore uses a 5 ms safety
undercut. It computes the equivalent sample boundary for the connected sample
rate, passes shorter audio through unchanged, and never changes the full source
used by Assemble.

This remains experimental model-behavior guidance rather than a proven H3
architecture requirement. Leave the switch off when comparing against stock
frame-exact behavior.

## Generated audio is always retained

When decoded audio is connected to Segment + Checkpoint, every scene receives
an uncompressed WAV under:

```text
output/h3_chains/<run_name>/generated_audio/
```

Completed assembly also writes `<final-name>.generated.wav` beside the MP4,
even when the final video uses `source_track`. This keeps H3's ambience, effects,
and regenerated performance available for post-production.

Generated WAV assembly budgets samples from cumulative delivered-video frame
boundaries, preventing per-scene rounding from accumulating into drift. This
approach was inspired by **seitanism's**
[MultiRef implementation](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef).
For masked AV, Loop Trim also carries the complete decoded overlap privately
inside its normal AUDIO output. Segment Save checkpoints it, and the later
scene owns that interval during combined generated-audio assembly. This keeps
Soft AV's half-cosine audio release instead of throwing it away at the trim.
The same ownership rule applies when scene 1 continues an Existing Video
Context prelude. Legacy checkpoints without the extra tensor keep
delivered-only assembly.

## Continuation trimming

Use **MiniMax H3 Contex Loop Trim** after decoding. In head mode it removes the
repeated visual prefix. With `match_tail=true`, it time-conforms the small H3
grid mismatch to the exact delivered-frame duration and carries the
full AV overlap privately to Segment Save. Connect Trim's AUDIO output directly;
there is no second overlap-audio socket.

`images_with_overlap` exposes an additional visual stream containing the
retained repeated context selected by `retain_overlap_frames`. In 0.5 chains,
wire **Current Shot → video_blend_frames** into that input. A scene-level
`video_blend_frames` value controls the boundary entering that scene; blank
inherits the Plan default and explicit `0` keeps a hard cut. This assembly-only
setting does not alter diffusion, the normal clean images output, or audio.

All continuation modes return the prefix length as `trim_frames`. In AV mask
modes those leading frames come from target-latent rows rather than persistent
guide-conditioning rows. They still overlap the preceding scene and must be
removed from delivered duration, including the feathered portion.

## Measure a join

Place **MiniMax H3 Contex Loop Seam Probe** between the current clip's untrimmed
audio decode and Loop Trim. Connect the preceding sampler AV latent, H3 audio
VAE, and the same `trim_frames` value.

The AUDIO output is unchanged. The report measures:

- correlation across the join;
- estimated timing offset;
- broadband level step;
- low-frequency ambience-floor step.

Strongly periodic music can alias by one complete cycle; the report marks that
as a known limitation. `tests/seam_probe.py` provides the file-based equivalent.
