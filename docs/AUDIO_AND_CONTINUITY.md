# Audio and continuity

## Choose an audio mode

| Mode | Timeline behavior | Final assembly |
|---|---|---|
| `source_track` | Current Shot provides the current source slice to Ref2VA; Motion Context carries picture history. | Uses the original source track. |
| `generated_audio` | Motion Context carries the previous H3 audio latent. | Concatenates checkpointed generated audio. |
| `source_plus_timeline` | Ref2VA receives the source slice and Motion Context carries generated-audio history. Experimental. | `audio_source: plan` selects the source track. |

For a complete prerecorded voice, song, or dialogue performance that must remain
exact, use `source_track`. For a short voice/timbre reference where H3 should
generate new words, use `generated_audio` and schedule that short clip as an
ordinary audio reference.

These descriptions are for the default `guide` continuation mode. In the
experimental `masked_av` and `feathered_av` modes, Chain Context places a
matching video and audio prefix inside the target latent, including when final
assembly uses `source_track`. `masked_av` protects the complete prefix;
`feathered_av` progressively denoises its final latent steps. For recursive
scenes it copies the previous sampler's audio latent directly. For scene 1
after Existing Video Context, source audio and the H3 audio VAE must both be
connected.

Prefer a 39-frame AV prefix. It maps exactly to 12 video latent steps and 65
audio steps; 22 frames maps to 36.666... audio steps and therefore requires
rounding at the AV boundary. At 39 frames, `feathered_av` fully protects the
first 8 video / 42 audio steps and ramps the final 4 video / 23 audio prefix
steps.

The Plan node mode is an inherited default and each scene may override it. The
override controls the transition into that scene: `guide` for a new shot with
interpretive continuity, `masked_av` for exact same-shot continuation, or
`feathered_av` for the same target-latent continuation with a softer boundary.
Mixed plans must still use global context/encode/anchor settings compatible
with every AV mask scene.

## Source-track wiring

Connect the same full ComfyUI AUDIO value to:

```text
Load Audio ─┬→ Loop Start
            ├→ Current Shot
            └→ Assemble

Current Shot source_audio_slice → Ref2VA / Scheduled Audio Ref
```

Current Shot cuts each raw scene window from the full track. Loop Start hashes
the waveform so a changed or incorrectly wired track cannot silently resume old
checkpoints. The track must cover the total delivered video; a truly silent
placeholder may be shorter and is padded safely.

When a long motion-reference video also contains the master soundtrack, use
**Lazy Motion AV Loader** instead of decoding the full video through a
component splitter:

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

### Tagged Ref2VA source timeline

Tagged references need a static media path because their fingerprint normally
returns to Plan. Connecting `Current Shot source_audio_slice` to Tagged Audio
Ref would close this cycle:

```text
Plan → Loop Start → Current Shot → Tagged Audio Ref → fingerprint → Plan
```

Use the Tagged Audio Ref `source_timeline` mode instead:

```text
Load Audio ─┬→ Loop Start
            ├→ Current Shot
            └→ Tagged Audio Ref ─┬→ Tagged Ref2VA
                                 └→ fingerprint → Plan

Current Shot state ─────────────────→ Tagged Ref2VA
```

The Tagged Audio Ref hashes the full source track. Tagged Ref2VA validates it
against Loop Start and derives the active scene's overlap-aware slice internally.
Its optional alignment switch changes only that derived reference slice.

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

## Continuation trimming

Use **MiniMax H3 Contex Loop Trim** after decoding. In head mode it removes the
repeated visual prefix. With `match_tail=true`, it also truncates or zero-pads
the decoded audio tail to the exact delivered-frame duration.

`retain_overlap_frames` exposes an additional visual stream containing part of
the repeated context for external stitchers. It does not alter the normal clean
images output or audio.

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
