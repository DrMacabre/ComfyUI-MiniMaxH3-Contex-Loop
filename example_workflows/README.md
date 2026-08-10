# Example workflows

## Experimental: MiniMax H3 Extend Existing Video Model Workflow

A compact two-scene model for extending an existing MP4. Core **Load Video**
connects its native `VIDEO` directly to **MiniMax H3 Existing Video Context**.
VHS and other loaders can instead use the adapter's separate `IMAGE`, `AUDIO`,
and `source_fps` inputs. Scene 1 continues from the imported tail, generated
audio can inherit its ending, and `prepend_original` places the normalized
source before the generated extension.

The Review Gate is fully wired between **Segment Save** and **Loop End**, with
frame-locked preview audio from Loop Trim. Its recovery branch is muted by
default. Select your own source video and model files before queueing. This is a
new standalone example; none of the earlier workflow JSON files were changed.
Treat it as experimental until the imported video/audio continuation path has
received broader testing across source codecs, frame rates, and H3 setups.

## Looping MiniMax H3 Seamless Chain Global Refs Example

Disk-backed recursive Ref2VA chain using the visual H3 Chain Plan editor,
global character references, a frame-exact source-song timeline, per-segment
checkpointing, interruption resume, and final assembly. The recovery branch is
muted by default and can assemble an already completed chain without sampling
the last scene again. This is the primary workflow for
`ComfyUI-MiniMaxH3-Contex-Loop` and uses the uniquely named
`MiniMaxH3LoopTrim`, so it can run while NikoDemon80's upstream Motion Context
pack is installed.

Replace the supplied image/audio filenames and model selections with files
available in your ComfyUI installation. Scene-count and duration labels are
intentionally generic because both are controlled by the editable plan.

## Legacy manual Motion Context workflows

`MiniMax H3 with Motion Context.json` is NikoDemon80's original compact FL2VA
motion-and-audio continuation workflow. It is retained for attribution and
history; its original `MiniMaxH3MotionContext*` ids now belong exclusively to
[ComfyUI-H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context).
Install that upstream pack to use or modernize the manual workflow.

## MiniMax H3 Seamless Chain Global Refs 6 Clips

This is also a historical manual workflow rather than the recursive loop demo.
It is a six-clip Ref2VA chain with global character-reference images, 39-frame video
and timeline-audio context, optional full previous-clip audio references, and
sequential clip bypass controls.

Workflow and the underlying Ref2VA multi-reference/audio compatibility patch
were contributed by **seitanism** in the Banodoco MiniMax H3
seamless-extension thread: [original patch](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771676158206032)
and [original workflow](https://discord.com/channels/1076117621407223829/1535700117452226560/1535771814452793474),
shared on 2026-08-08. Its original Motion Context node ids resolve through
NikoDemon80's upstream pack. Do not run the separately posted global patch
script alongside either marker-gated custom-node implementation.

Extra custom nodes used by the demo:

- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) for group controls
  and `Any Switch`.
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)
  for preview/final video combining.

The workflow's optional full-audio-reference section is off by default. Keep
it off for the baseline test because a full Ref2VA audio reference can make
music restart or replay; Motion Context's 39-frame timeline-audio path remains
enabled independently.
