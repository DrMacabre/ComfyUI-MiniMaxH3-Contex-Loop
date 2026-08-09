# Third-party notices

## ComfyUI-H3-Motion-Context

This repository grew from the original H3 Motion Context implementation by
**NikoDemon80**:

https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context

The shared initial implementation and research remain under this repository's
GPL-3.0 license and are preserved in its Git history. Niko's project owns the
original `MiniMaxH3MotionContext*` public node ids. This specialized loop pack
uses separate registrations while vendoring upstream's shared marker and
patch-ownership ABI, allowing both projects to be installed without registering
the same nodes or double-wrapping ComfyUI.

`patch_layout.py` and `patch_payload.py` are synchronized byte-for-byte with
upstream revision `c140ae99b8c3` (`0.2.0`, 2026-08-09). Keeping these two files
on upstream's ABI is required for safe co-installation.

## ComfyUI-MiniMaxH3-Easy

The H3 Chain Plan scene editor's quick `@` reference-tag and `#` dialogue-tag
interactions were inspired by
[ComfyUI-MiniMaxH3-Easy](https://github.com/nkxx188/ComfyUI-MiniMaxH3-Easy)
by **nkxx188**. The scene-card editor, plan serializer, timing calculations,
and chain integration in this repository are an original implementation.

ComfyUI-MiniMaxH3-Easy is distributed under the MIT License:

```text
MIT License

Copyright (c) 2026 nkxx188

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
