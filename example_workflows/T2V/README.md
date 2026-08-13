# MiniMax H3 T2V workflows

Choose one authoring interface; the generation graph is otherwise equivalent.

| Workflow | Prompt interface | Best for |
|---|---|---|
| `MiniMax H3 T2V - Normal.json` | Scene Prompt Editor | Familiar compact node-level editing |
| `MiniMax H3 T2V - Studio.json` | Plan Studio | Timeline navigation, revisions, saved-scene status, and playback |

Both workflows are true T2VA: the core `MiniMaxH3ImageToVideo` node has no
first- or last-frame connection. They demonstrate two chained scenes with
generated audio, 22 motion-context frames, and a smaller independent
five-frame visual blend.

The in-canvas **PROMPT SOURCE / ATTRIBUTION** note identifies which scene was
reproduced from Banodoco and which continuation was written specifically for
this example.
