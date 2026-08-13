# Compatibility

## Runtime scope

Installing the pack does not globally alter ordinary ComfyUI workflows. Its H3
conditioning patches activate when a Contex Loop Context node executes and
self-check the live model/layout assumptions before use.

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
