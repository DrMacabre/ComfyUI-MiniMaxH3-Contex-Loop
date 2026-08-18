# Migrating workflows to version 0.5

Version 0.5 is backward compatible. Existing 0.4 node ids, positional outputs,
widget order, manifests, and checkpoints remain supported. Migration is
recommended for clearer graphs and model-free validation, but it is not
required merely to open or resume an older workflow.

## What changes

Version 0.5 replaces combined low-level choices with two explicit policies:

| 0.4 audio mode | Final audio | Source reference | Generated continuity |
|---|---|---|---|
| `generated_audio` | generated | off | on |
| `source_track` | source | on | off |
| `source_plus_timeline` | source | on | on |

| 0.4 continuation | 0.5 transition | Default context |
|---|---|---:|
| guide with zero context | Cut | 0 frames |
| `guide` | Guide | 22 frames |
| new `tone_carry_guide` | Tone Carry Guide | 22 frames |
| new `latent_guide` | Latent Guide | 22 frames |
| new `tapered_guide` | Detail Guide | 22 frames |
| `masked_av` | Hard AV | 39 frames |
| `audio_feathered_av` | Soft AV | 39 frames |
| `feathered_av` | Expert override (experimental compatibility mode) | custom |

Advanced mode retains the old implementation and context fields for custom
values. Tone Carry Guide, Latent Guide, and Detail Guide are opt-in and do not
alter migrated workflows. The semantic choice always describes the boundary
entering a scene.

## Automatic migration

Back up a custom workflow, then run:

```bash
python tools/migrate_v05_workflows.py /path/to/workflow.json
```

Pass several paths to migrate them together. Use `--check` to report files that
would change without writing them:

```bash
python tools/migrate_v05_workflows.py --check /path/to/workflow.json
```

With no paths, the tool checks or migrates the maintained active examples. It
is idempotent: running it again does not add duplicate policy, preflight, or
timeline nodes.

## Source-media rewiring

The old source-track graph repeated one full decoded AUDIO value:

```text
Load Audio ─┬→ Loop Start
            ├→ Current Shot
            ├→ Tagged Audio Ref
            └→ Assemble
```

The 0.5 graph registers media once:

```text
Load Video ─┐
            ├→ Source Timeline ─┬→ Preflight / Plan Studio
Load Audio ─┘                   └→ Loop Start → Current Shot
                                                   └→ scene slice → Tagged Audio Ref

Loop End manifest → Assemble
```

Path-backed media remains lazy. Current Shot requests only its active window,
and manifests carry the descriptor to recovery and assembly. If the only audio
input is a tensor, Loop Start materializes one normalized run-owned copy.

Do not return a Tagged Audio fingerprint derived from Current Shot to Plan;
that would create a graph cycle. Keep static picture/reference fingerprints on
Plan. Structured scene dependencies record the exact source PCM window used by
generation automatically.

## Preflight and resume

Normal workflows insert Chain Preflight before Loop Start. Studio workflows use
the same backend through Plan Studio. It validates duration, source windows,
references, compatibility, and resume eligibility without loading H3.

Version 0.5 stores structured per-scene dependencies. A change to the next
scene, its incoming transition, or assembly-only media does not invalidate an
already accepted predecessor. Old checkpoints without structured records keep
their generic hash fallback.

## Compatibility guarantee

The migration tool adds nodes and links but does not renumber existing nodes or
change existing node types. Loop Start's original optional socket order is
preserved so numerical 0.4 workflow slots still deserialize correctly. Legacy
full-AUDIO fan-out, direct media paths, Plan widgets, and archived examples
remain accepted throughout the 0.5 release.
