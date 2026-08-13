# Example workflows

Examples are organized first by H3 generation mode, then by authoring level.
Each completed mode should contain the same two-workflow pair:

1. **Normal** — the standard Plan and scene-editor workflow.
2. **Studio** — the same generation graph and prompt plan with Plan Studio as
   the authoring interface.

```text
example_workflows/
├── T2V/
│   ├── MiniMax H3 T2V - Normal.json
│   └── MiniMax H3 T2V - Studio.json
└── Archive/
    └── previous mixed and experimental examples
```

Only T2V has been reorganized into the new pair so far. I2V, FL2V, L2V, and
Ref2V folders will be added when both their Normal and Studio workflows are
ready, rather than exposing half-finished categories.

## T2V

Both files use ComfyUI's core `MiniMaxH3ImageToVideo` node with `first_frame`
and `last_frame` deliberately disconnected, which selects its T2VA path. They
share the same two-scene portrait plan, model graph, seeds, generated-audio
route, 22-frame motion context, five-frame visual blend, checkpointing, Review
Gate, recovery path, and final assembly.

- [`T2V/MiniMax H3 T2V - Normal.json`](<T2V/MiniMax H3 T2V - Normal.json>)
  uses the standard Scene Prompt Editor.
- [`T2V/MiniMax H3 T2V - Studio.json`](<T2V/MiniMax H3 T2V - Studio.json>)
  replaces that editor with the optional timeline-oriented Plan Studio. It does
  not change sampling or ComfyUI execution.

Each requested ten-second scene normalizes to 243 raw H3 frames. The second
scene reproduces and removes 22 context frames, so the assembled delivery is
464 frames, or 19.333 seconds at 24 fps. Five of those repeated frames are
retained separately for cumulative visual blending; audio remains frame-locked
and is not crossfaded.

### Prompt source

Scene 1 is reproduced verbatim from a prompt shared by **🦙rishappi** in
Banodoco's `#minimax_h3_chatter` on August 11, 2026:
[original Discord message](https://discord.com/channels/1076117621407223829/1532625331960152124/1536689209761599608).
Scene 2 is a new repository-authored continuation using the same H3 T2VA
three-section structure. Each workflow also contains this attribution in a
visible note beside the graph.

## Archive

[`Archive/`](Archive/) contains the previous mixed catalog unchanged for
compatibility, research, and migration. These workflows are not deleted, but
they are not the recommended type-based starting points for the 0.4 examples.
The archived catalog explains their historical purpose and extra dependencies.
