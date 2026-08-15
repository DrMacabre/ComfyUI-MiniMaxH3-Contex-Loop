# Compatibility

## Runtime scope

Installing the pack does not globally alter ordinary ComfyUI workflows. Its H3
conditioning patches activate when a Contex Loop Context node executes and
self-check the live model/layout assumptions before use.

The two continuation engines and public masking path are capability-gated:

- `guide` prefers native Add Guide / MultiRef behavior from ComfyUI PR #15439
  and uses the existing guarded guide fallback only on older builds;
- `masked_av` and `feathered_av` prefer native per-token H3 AV masks from PR
  #15375 and lazily install only missing mask-engine, payload, token-aligned
  inpaint-scale, and legacy sampler-bridge behavior when the masked path
  executes. It follows
  PR #15375 commit `989e7a9`: pixel masks stay intact for final sampler
  blending while internal H3 timesteps use pooled token-grid values. It still
  requires the native #15439 Add Guide / MultiRef core baseline; masked mode
  is not enabled on the older guide-fallback architecture.
- `MiniMaxH3ContexMaskedTarget` uses the same native-first per-token AV mask
  layer for arbitrary manual targets. It activates compatibility only when the
  node executes and does not require a separate MODEL patch node.

Importing the node pack or running a guide-only workflow does not activate the
masked runtime compatibility. A partially updated native mask engine is
rejected rather than mixed with the vendored snapshot.

The general masking IDs are deliberately different from
`ComfyUI-MiniMaxH3-PerRowMasking`, so both folders may be installed during
migration without one pack replacing the other's registered nodes.

After updating ComfyUI or H3 optimization packs, restart the process fully so
patch ownership is rebuilt cleanly.

## H3 Motion Context copies

This pack and NikoDemon80's upstream pack use distinct node IDs and may coexist.
Compatible patch copies share ownership markers; the second copy normally
stands down.

If an older compatible copy owns the process first, wire **MiniMax H3 Patch
Priority** before Contex Loop Context. It can replace only a recognized sibling
implementation. Unknown wrappers fail with an ownership explanation rather
than being overwritten.

## Native MiniMax H3 Add Guide

When ComfyUI provides native **MiniMax H3 Add Guide**, core owns arbitrary
video/audio guide records and payload merging. This pack retains only the
marker-gated target-alignment behavior needed for Ref2VA continuation.

Place official Add Guide nodes after Loop Context so they append scene-local
anchors to the already constructed continuation guides.

## H3-Multishot and SolAttn

- H3-Multishot's recognized AV-bank payload is reused rather than wrapped a
  second time.
- Kijai's SolAttn H3 Morton observer composes safely in either activation order.
  Recognition is independent of the custom-node folder name: the upstream
  module, path-loaded PR helpers such as `sol_attn_minimax_v2`, renamed copies,
  and nested observer copies are identified by their audited `original_init`
  closure plus read-only `_video_span`/`_SPANS` registration behavior. Merely
  having a similar name or constructor closure is insufficient, so unknown
  layout-mutating wrappers remain rejected.
- Ref2VA media remains intact when continuation guides are merged.
- Changed layout assumptions and unknown wrappers fail loudly.

Keep Spectrum and other step-skipping systems disabled for baseline continuity
tests. KJ preview bridging is scoped to the active loop.

## Legacy widget widths

While any Contex Loop node is present on a legacy LiteGraph canvas, the pack
works around
[ComfyUI frontend issue #12443](https://github.com/Comfy-Org/ComfyUI_frontend/issues/12443)
for all visible nodes. A separate Legacy Widget Width Fix node is unnecessary
but remains compatible.

Disable the embedded workaround under **Settings → MiniMax H3 Contex Loop →
Compatibility → Widget widths** if another frontend or extension handles it.

## Platform notes

- Review and Assemble prefer `ffmpeg` but fall back to bundled PyAV.
- The Plan's Output action opens paths on the ComfyUI host. On headless or
  remote servers it copies the host path; the browser cannot open an arbitrary
  remote filesystem path on the client machine.
- Run Manager operates against the ComfyUI host's input/output folders and is
  therefore suitable for Docker and remote deployments.
