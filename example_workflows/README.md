# Example workflows

Examples are organized first by H3 generation mode, then by authoring level.
Each completed mode should contain the same two-workflow pair:

1. **Normal** — the standard Plan and scene-editor workflow.
2. **Studio** — the same generation graph and prompt plan with Plan Studio as
   the authoring interface.

```text
example_workflows/
├── assets/
│   └── jigen_market_garden_doom_opening.png
├── MiniMax H3 I2V - Normal.json
├── MiniMax H3 I2V - Studio.json
├── MiniMax H3 T2V - Normal.json
├── MiniMax H3 T2V - Studio.json
└── Archive/
    └── previous mixed and experimental examples
```

Active workflow JSON files remain directly in `example_workflows/` so ComfyUI
can discover them. Only retired examples are nested under `Archive/`. T2V and
I2V are the first reorganized pairs; FL2V, L2V, and Ref2V will be added at this
same top level when both their Normal and Studio variants are ready.

## T2V

Both files use ComfyUI's core `MiniMaxH3ImageToVideo` node with `first_frame`
and `last_frame` deliberately disconnected, which selects its T2VA path. They
share the same two-scene portrait plan, model graph, seeds, generated-audio
route, 22-frame motion context, checkpointing, Review Gate, recovery path, and
final assembly. The shared model stack uses ComfyUI's
core `ModelAttentionBackend` set to `comfy kitchen attention`, followed by
`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` at strength 1.0.
Both the Plan default and scheduler fallback use eight sampling steps with the
`lcm` sampler and `beta` scheduler.

- [`MiniMax H3 T2V - Normal.json`](<MiniMax H3 T2V - Normal.json>)
  uses the standard Scene Prompt Editor.
- [`MiniMax H3 T2V - Studio.json`](<MiniMax H3 T2V - Studio.json>)
  uses the optional timeline-oriented Plan Studio plus the separate Rich Scene
  Prompt Editor. Neither changes sampling or ComfyUI execution.

Each requested ten-second scene normalizes to 243 raw H3 frames. The second
scene reproduces and removes 22 context frames, so the assembled delivery is
464 frames, or 19.333 seconds at 24 fps. Normal demonstrates a hard trimmed
boundary (`video_blend_frames = 0`); Studio demonstrates a five-frame visual
blend. Audio remains frame-locked and is not crossfaded.

### Prompt source

Scene 1 is reproduced verbatim from a prompt shared by **🦙rishappi** in
Banodoco's `#minimax_h3_chatter` on August 11, 2026:
[original Discord message](https://discord.com/channels/1076117621407223829/1532625331960152124/1536689209761599608).
Scene 2 is a new repository-authored continuation using the same H3 T2VA
three-section structure. Each workflow also contains this attribution in a
visible note beside the graph.

## I2V

Both files use one opening image with ComfyUI's core
`MiniMaxH3ImageToVideo`. `MiniMaxH3ChainFirstSceneImage` sends the image only
to scene 1; scene 2 receives no image and continues exclusively from the
22-frame H3 Motion Context. Do not bypass this gate or the opening frame will
be reapplied on every scene.

- [`MiniMax H3 I2V - Normal.json`](<MiniMax H3 I2V - Normal.json>) uses the
  stable Scene Prompt Editor with rich token presentation but no active prompt
  optimizer UI.
- [`MiniMax H3 I2V - Studio.json`](<MiniMax H3 I2V - Studio.json>) uses Plan
  Studio plus the separate Rich Scene Prompt Editor and its optional optimizer.

The pair uses the same Comfy Kitchen attention, LightX2V eight-step LoRA,
`lcm` sampler, `beta` scheduler, generated-audio route, checkpoint/review path,
and final assembly as T2V. It renders at 896 × 672 to preserve the bundled
image's 4:3 composition. Each scene requests 362 raw frames; after removing 22
repeated frames from scene 2, delivery is 702 frames, or 29.25 seconds at 24
fps. Normal uses a hard boundary and Studio demonstrates a five-frame blend.

Copy [`assets/jigen_market_garden_doom_opening.png`](assets/jigen_market_garden_doom_opening.png)
to `ComfyUI/input/`, then select it in the workflow's Load Image node. The JSON
keeps the basename preselected, but ComfyUI does not load arbitrary files from
a custom-node repository.

### Prompt and image source

Scene 1 and the opening image were shared by **ᴊɪɢᴇɴ** in Banodoco's
`#minimax_h3_gens` on August 12, 2026:
[prompt and source image](https://discord.com/channels/1076117621407223829/1533677158067736777/1537180042210054226),
[generated result](https://discord.com/channels/1076117621407223829/1533677158067736777/1537178443358142555).
The workflow normalizes escaped line breaks and removes the surrounding
code-string quote while preserving the source wording. Scene 2 is a new
repository-authored continuation and intentionally contains no Picture label.

## Archive

[`Archive/`](Archive/) contains the previous mixed catalog unchanged for
compatibility, research, and migration. These workflows are not deleted, but
they are not the recommended type-based starting points for the 0.4 examples.
The archived catalog explains their historical purpose and extra dependencies.
