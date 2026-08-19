# Example assets

## `jigen_market_garden_doom_opening.png`

Opening image for the paired MiniMax H3 I2V example workflows. It was shared
by **ᴊɪɢᴇɴ** in Banodoco's `#minimax_h3_gens` on August 12, 2026 alongside the
I2V prompt used by scene 1:

- [Prompt and source image](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226)
- [Generated result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555)

SHA-256:
`7a9993055d71b1e174096f2a2533ae2a0b14a686fdacae0c7bab1faa738ef5f3`

Copy the PNG to `ComfyUI/input/` before loading either I2V workflow or any of
the Ref2V examples. ComfyUI's Load Image node resolves assets from its
configured input directories, not from this repository folder.

## `jigen_market_garden_doom_last.png`

Final frame extracted from ᴊɪɢᴇɴ's credited generated result above. The FL2V
Normal example uses it as Frame B, then alternates B and the original Frame A
as per-scene last-frame targets.

SHA-256:
`e07862c0d5160f06f015b8849dc4b7d2db0524de5ba490fd26c3dff33e196b34`

Copy this PNG and `jigen_market_garden_doom_opening.png` to `ComfyUI/input/`
before loading the FL2V workflow or any of the Ref2V examples.

## `soldier_crabs_bribie_island_cc0.webm`

Modern source video for the masked inpaint, AV extension, and bridge examples. It
shows light-blue soldier crabs (*Mictyris longicarpus*) on Bribie Island,
Queensland, Australia. The video was filmed in 2015 by **Watermark Resort
Caloundra** and is distributed under the
[CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

- [Wikimedia Commons source and license record](https://commons.wikimedia.org/wiki/File:Light-blue_soldier_crabs_on_Bribie_Island.webm)
- Original format: VP8/Vorbis WebM, 1280×720, 13.049 seconds, stereo audio

SHA-256:
`aacef1ac138445311eb61734f8ca92f8dc438b8d9ca3210fd8893aa5e925ee47`

Copy the WebM to `ComfyUI/input/` before loading any masked inpaint, AV
extension, or bridge workflow. The examples force decoder output to 24 fps and
resize it to their 960×544 H3 canvas.

## `soldier_crabs_inpaint_mask.png`

Static 960×544 black-and-white demonstration mask for the looped inpaint
workflow. White selects the lower-central beach region for regeneration;
black protects the source video. Grid Preview displays the exact effective H3
32px cells before sampling. Loop Mask Slice explicitly broadcasts this single
frame. Replace its input with a tracked MASK batch to follow a moving object;
the node slices matching frames for every loop scene and overlap.

SHA-256:
`95cf18228cd3559ad980339fe9d8fccdcef25799368719b8e044cd61c6691fe4`

## `soldier_crabs_reference_cc0.png`

Reference frame extracted at 9 seconds from the CC0 soldier-crab video above.
The multi-scene Ref2VA extension workflow uses it to stabilize species
appearance beneath the authoritative protected AV prefix. The Ref2V masked
inpaint demo uses it as `<Picture 1>` to define the appearance regenerated only
inside the spatial mask.

SHA-256:
`432dc2c9b0b9d0c33ed33217247fefcbe551d240959f6eefb7c04dfc99378047`

Copy it to `ComfyUI/input/` together with the WebM before loading either the
chained Ref2VA extension or Ref2V masked-inpaint example.
