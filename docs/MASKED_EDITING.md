# Masked editing

MiniMax H3 can edit a real source AV latent instead of treating the source as
an ordinary reference. A nested denoise mask controls every target stream:

```text
0 = preserve the source latent
1 = regenerate this row
```

This is the general form of the chain's `masked_av` continuation. The chain
builds a temporal prefix mask automatically; the public masking nodes accept
arbitrary static or tracked spatial masks.

Start with
[`MiniMax H3 - Masked Video Inpaint.json`](<../example_workflows/MiniMax H3 - Masked Video Inpaint.json>).

## Nodes

### Masking · Trim Source AV

**MiniMax H3 Masking · Trim Source AV** drops only trailing video frames until
the source has a valid H3 `17k+5` length. Optional source audio is trimmed to
the same duration at H3's fixed 24 fps. It never resizes frames, changes fps,
or pads short audio.

Use the returned `h3_length` for the core H3 conditioning node. Resize the
returned frames once to the final H3 canvas, then feed that exact batch to the
video VAE, mask preview, and any tracking path.

### Masking · Grid Preview

H3's video VAE reduces each spatial axis by 16 and the DiT groups the result
into 2×2 latent patches. One independently masked H3 row therefore covers
roughly **32×32 source pixels**.

**MiniMax H3 Masking · Grid Preview** shows those cells and returns a snapped
MASK suitable for Apply Target Mask. Its canvas must match the encoded source
and be divisible by 32.

- `runtime exact (latent max)` reproduces the spatial reduction used by H3;
- `any pixel coverage` selects a whole cell for any marked source pixel;
- `50% pixel coverage` selects cells at least half covered;
- `full pixel coverage` selects only completely covered cells;
- `cell_adjust` grows or shrinks by complete cells.

The `grid_preview` IMAGE contains only the selected `preview_frame` to avoid
duplicating an entire video for display. The `snapped_mask` output retains the
complete static or tracked mask batch.

### Masking · Apply Target Mask

**MiniMax H3 Masking · Apply Target Mask** expects the source media as the
sampler's real joint video/audio target latent. Encode source frames and audio
with their H3 VAEs, combine the two latent streams, apply the mask, and connect
`masked_target` to `SamplerCustomAdvanced.latent_image`.

Do not also add the same source as `<Video>` merely to make masking work. A
reference influences generation; it does not provide the clean latent values
that the mask protects.

The main mask may use either convention:

- `white = generate` for conventional inpainting;
- `white = preserve` when the supplied artwork describes protected content.

The node resizes static or per-frame masks to the target video latent. H3 then
snaps spatial values to its patch rows. Batch size is currently one.

## Audio modes

| Mode | Behavior |
|---|---|
| `preserve source audio` | Protect the complete encoded source-audio latent. This is the default for visual edits. |
| `generate all audio` | Regenerate the complete H3 audio stream. |
| `follow video mask` | Generate audio during times where any video region is selected. |
| `custom audio mask` | Reduce the optional MASK to a time envelope; white generates and black preserves. |

Audio is not spatial, so a visual object mask has no unique audio equivalent.
Use preserve mode unless the edit deliberately needs new sound.

## Exact master-audio timelines

**Masking · Master Audio + Video Prefix** is the asymmetric timeline-audio
form of target masking. It takes the empty joint target produced by stock H3
conditioning, VAE-encodes the exact master-audio interval beginning at
`clip_start_seconds`, replaces the complete target audio stream, and assigns
audio mask `0` for the full raw clip. The master may be music, dialogue,
narration, or another finished soundtrack.

When `source_frames` is connected, the node also converts the previous clip to
24 fps, selects the final native H3 context run, VAE-encodes it into the target
video prefix, and protects only those video rows. Future video rows remain `1`
and are generated normally. The returned `trim_frames` is authoritative for
the Loop Trim node and visual overlap assembly.

The master audio is target content, not a Ref2VA audio reference. Keep every
`ref_audio_*` input disconnected, and mux the untouched full master audio onto
the assembled picture for final delivery.

## Composition with chain continuation

If the target already contains a nested H3 noise mask, Apply Target Mask
intersects the two masks. **Preservation wins.** This allows an arbitrary
spatial edit to compose safely with the exact protected prefix produced by
`masked_av`:

```text
chain prefix mask × spatial edit mask = final generation mask
```

The same rule holds whether Apply Target Mask sits before or after Chain
Context, because both nodes emit latent-sized nested AV masks.

## Inpaint, outpaint, and clip bridging

The bundled workflow implements video inpainting. The same mask contract also
supports the other operations once their source target is prepared:

- **Outpaint:** place the source on a larger H3 canvas, encode that canvas,
  preserve the original rectangle, and generate the exposed border.
- **Object removal/replacement:** provide a static or tracked object mask and
  describe only the intended replacement while asking H3 to retain the rest.
- **Temporal repair:** use a mask batch that is black on retained frames and
  white during the interval to regenerate.
- **Two-clip bridge:** construct a target containing the end of clip A and the
  beginning of clip B, protect both ends, and generate the middle interval.

This first integration supplies the general mask and inpaint workflow. It does
not yet bundle the expanded-canvas or two-ended latent compositors; those can
be added without changing the H3 mask/runtime layer.

## Runtime compatibility

The masking nodes prefer native ComfyUI support equivalent to PR #15375. On a
supported post-PR-#15439 H3 baseline, they lazily install only the missing mask
engine, payload extraction, preprocessing, or inpaint scaling. No MODEL patch
node is needed, and importing the pack does not modify stock H3 behavior.

A partially updated native implementation is rejected rather than combined
with the compatibility snapshot. Restart ComfyUI fully after updating core or
an H3 optimization extension.

Per-row mask support guarantees the sampling mechanics, not that H3 was trained
equally strongly for every edit topology. Feathered source preparation and a
short test render remain advisable for outpainting and complex tracked masks.
