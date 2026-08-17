# Version 0.5 workflow architecture

This document freezes the contracts and migration boundaries for the 0.5
workflow-UX release. Implementations may evolve behind these contracts, but a
later step must not silently change their meaning.

## Release invariant

A normal workflow selects source media once, chooses its audio intent once,
chooses an incoming transition preset per scene, and can validate or resume
without wiring the same full media value to several nodes.

Version 0.5 remains compatible with saved 0.4 workflow JSON and checkpoint
metadata. Existing node class ids and positional output slots are not removed
or reordered during this release.

## Source Timeline contract

`H3_SOURCE_TIMELINE` is the single source-media contract. Its serialized
version is `h3_source_timeline_v1`.

It records:

- a file-backed video descriptor when picture is present;
- embedded, external-path, deferred-tensor, or absent audio;
- native FPS, stream PTS origin, duration, and the derived 24-fps extent;
- a native-frame skip offset and its exact time origin;
- independent video, audio, and combined timeline fingerprints;
- original, archived, and run-owned recovery locations.

The descriptor never requires a decoded full-video IMAGE batch. Scene consumers
request one overlap-aware 24-fps window. Path-backed audio is also decoded only
for the requested scene. If the only available audio is a ComfyUI tensor, Loop
Start materializes one normalized run-owned file and places only its descriptor
in recursive state and manifests.

Primary consumers are Loop Start and Tagged Motion Ref. Current Shot obtains
scene slices from chain state; Review, Manifest Load, and Assemble obtain the
descriptor from the saved manifest. Legacy VIDEO/AUDIO sockets remain adapters.

## Audio intent contract

Audio intent uses `h3_audio_policy_v1` and three independent axes:

| Axis | Values | Meaning |
|---|---|---|
| Final audio | `generated`, `source`, `none` | What Assemble places in the final MP4 |
| Source reference | `on`, `off` | Whether the active source window guides H3 generation |
| Generated continuity | `on`, `off` | Whether the prior sampled audio latent continues into the next scene |

Paired audio on a tagged motion reference is a fourth, reference-local decision:
`embedded` or `off`. It never selects the final soundtrack implicitly.

Legacy Plan modes migrate exactly:

| 0.4 `audio_mode` | Final | Source reference | Generated continuity |
|---|---|---|---|
| `source_track` | source | on | off |
| `generated_audio` | generated | off | on |
| `source_plus_timeline` | source | on | on |

New Plan nodes default to generated final audio, no source reference, and
generated continuity. Saved 0.4 widget values retain their old behavior.

## Incoming transition contract

Transitions use `h3_transition_policy_v1`. A scene setting always describes
how that scene consumes its predecessor; it does not retroactively redefine
the completed predecessor.

| Preset | Continuation implementation | Context |
|---|---|---:|
| `cut` | guide with no carried picture | 0 frames |
| `guide` | guide rows | 22 frames |
| `detail_guide` | tapered chroma-noise guide rows | 22 frames |
| `hard_av` | protected AV prefix | 39 frames |
| `soft_av` | temporally feathered AV prefix | 39 frames |

Advanced mode may override the implementation and context count explicitly.
`tapered_guide` accepts the listed Guide context lengths; only the 22-frame
preset has published validation, so other lengths remain experimental. The
resolved values, not merely the preset name, enter scene metadata.

## Scene dependency contract

Each accepted scene stores `h3_scene_dependency_v1`. Dependencies have four
scopes:

1. `global_generation`: model, VAE, LoRA, sampler, scheduler, CFG, and other
   generation-body configuration.
2. `scene_generation`: prompt, seed, raw length, steps, active references, and
   scene-local media windows.
3. `incoming_boundary`: the transition and context used to enter that scene.
4. `assembly_only`: final mux media that did not guide generation.

Resume through scene N compares scopes 1–3 only for accepted scenes 1..N.
Changing scene N+1 or its incoming boundary cannot invalidate scene N. Changing
an assembly-only source track does not invalidate sampled video. If source
audio guided a scene, only that scene's canonical PCM window is a generation
dependency; unrelated future audio is not.

Every mismatch report identifies its scope, scene, field, saved value, current
value, and whether regeneration is required.

## Compatibility rules

- Existing node ids remain registered.
- Existing outputs retain their positional indices.
- Existing required widget order remains readable.
- Plan's retired `audio_mode`, `continuation_mode`, and `context_length`
  widgets remain serialized for 0.4 compatibility but are hidden in the normal
  0.5 presentation. Legacy 0.4 Policy Adapter exposes those choices as an
  explicit compatibility route and emits the two typed 0.5 policies.
- New policy fields are appended or introduced through frontend-backed
  migration rather than inserted into old positional layouts.
- Legacy `audio_mode`, full AUDIO fan-out, direct media paths, and manual
  generation fingerprints remain accepted for 0.5.
- Existing checkpoint formats retain their current generic hash fallback when
  structured dependency records are unavailable.
- Diagnostic and legacy sockets may be visually hidden, but the backend slots
  remain until a later breaking release.

## Preflight contract

The same pure preflight implementation serves Loop Start and Plan Studio. It
runs before model-dependent sampling and reports:

- resolved scene frame counts, durations, source windows, and overlap trims;
- native-FPS/PTS to 24-fps mapping and skip origin;
- source duration, required duration, exact shortfall, and last complete scene;
- active/unresolved reference tags and their scene windows;
- source and archive availability;
- runtime guide, mask, and known attention-wrapper compatibility;
- automatic generation-body fingerprint coverage;
- resume eligibility plus structured mismatches.

Errors include a user action. Sample counts and latent-grid details may appear
under diagnostics, not as the primary explanation.

Plan Studio also consumes those same reference-window results for its motion
comparison track. It does not decode the full reference into IMAGE tensors.
The server seeks and transcodes only the selected scene window to a cached
low-resolution MP4; the comparison player offsets Guide windows past the
incoming context that is removed from the delivered scene.

## Socket presentation rules

The primary graph displays only generation-bearing connections. Status,
manifest JSON, booleans used only for inspection, legacy passthroughs, and
conditional audio sockets are Advanced. Conditional inputs appear when their
policy needs them. The three superseded Plan policy widgets are also hidden;
the node menu can reveal them for diagnosis. Hiding a socket or widget must not
change its backend index or serialized position.

## Delivery order

1. Freeze contracts and 0.4 fixtures.
2. Implement Source Timeline and legacy adapters.
3. Introduce independent audio policies.
4. Add transition presets.
5. Migrate all consumers to the timeline.
6. Add preflight.
7. Store and compare structured scene dependencies.
8. Hide redundant sockets without changing positions.
9. Clarify Run Manager and prompt-history state.
10. Run migration, integration, and release validation.

## Release validation

All ten delivery stages are implemented. The maintained workflow catalog uses
explicit audio and transition policies, Source Timeline, and model-free
preflight. The migration tool is idempotent, the frozen 0.4 positional contract
is covered by regression tests, and backend/frontend release checks enforce a
single package version. Archived 0.4 workflows remain unchanged examples of the
supported compatibility route.
