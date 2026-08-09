# Example workflows

## Looping MiniMax H3 Seamless Chain Global Refs Example

Disk-backed recursive Ref2VA chain using the visual H3 Chain Plan editor,
global character references, a frame-exact source-song timeline, per-segment
checkpointing, interruption resume, and final assembly. The recovery branch is
muted by default and can assemble an already completed chain without sampling
the last scene again.

Replace the supplied image/audio filenames and model selections with files
available in your ComfyUI installation. Scene-count and duration labels are
intentionally generic because both are controlled by the editable plan.

## MiniMax H3 with Motion Context

The original compact FL2VA motion-and-audio continuation workflow included
with this node pack.

## MiniMax H3 Seamless Chain Global Refs 6 Clips

Six-clip Ref2VA chain with global character-reference images, 39-frame video
and timeline-audio context, optional full previous-clip audio references, and
sequential clip bypass controls.

Workflow and the underlying Ref2VA multi-reference/audio compatibility patch
were contributed by **seitanism** in the Banodoco MiniMax H3
seamless-extension thread: [original patch](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771676158206032)
and [original workflow](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771814452793474),
shared on 2026-08-08. The compatibility behavior is now activated inline by
the `H3 Motion Context` node and is marker-gated so unrelated H3 workflows keep
stock behavior; do not run the separately posted patch script on this version.

Extra custom nodes used by the demo:

- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) for group controls
  and `Any Switch`.
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
  for preview/final video combining.

The workflow's optional full-audio-reference section is off by default. Keep
it off for the baseline test because a full Ref2VA audio reference can make
music restart or replay; Motion Context's 39-frame timeline-audio path remains
enabled independently.
