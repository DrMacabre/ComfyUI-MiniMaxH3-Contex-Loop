"""H3 Motion Context.

Clip chaining for MiniMax H3: pin the tail of the previous clip (picture
and sound) so the next clip genuinely continues it.

Registers the nodes without changing ComfyUI's runtime behavior. The Motion
Context node activates both patches inline on first execution:

  patch_layout   lifts the first/last-only keyframe anchor restriction,
                 moves pinned audio onto the clip's own timeline, and
                 keeps anchor coordinates aligned when refs shift the
                 layout cursor
  patch_payload  stops the refs branch clobbering keyframe cond latents,
                 so pinned video and pinned audio can be used together

Both wrappers are marker-gated, so H3 workflows that do not pass through a
Motion Context node keep stock behavior even after an opted-in workflow has
run. If either self-test fails the nodes still load but refuse to run the
affected path, so an upstream ComfyUI change produces a clear message rather
than a silently wrong render.
"""

from .nodes import (
    NODE_CLASS_MAPPINGS as _CONTEXT_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _CONTEXT_NODE_DISPLAY_NAME_MAPPINGS,
)
from .chain_nodes import (
    CHAIN_NODE_CLASS_MAPPINGS,
    CHAIN_NODE_DISPLAY_NAME_MAPPINGS,
)

NODE_CLASS_MAPPINGS = dict(_CONTEXT_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(CHAIN_NODE_CLASS_MAPPINGS)

NODE_DISPLAY_NAME_MAPPINGS = dict(_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(CHAIN_NODE_DISPLAY_NAME_MAPPINGS)

WEB_DIRECTORY = "./web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
