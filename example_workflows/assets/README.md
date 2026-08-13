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
