"""ComfyUI MiniMax H3 Contex Loop 0.5.

Disk-backed recursive MiniMax H3 scene loops with frame-exact picture/audio
continuation, review gates, checkpoint resume, and final assembly.

This project continues the looping work that grew from NikoDemon80's original
ComfyUI-H3-Motion-Context. It intentionally uses distinct public node ids and
vendors upstream's shared runtime-patch ABI so both packs can be installed
together without wrapping ComfyUI twice. The
original Motion Context, Save Latent, and Load Latent ids remain exclusively
owned by Niko's upstream pack; this pack exports its stricter Loop Trim, a
distinctly named Seam Probe adaptation, and the specialized H3 Chain nodes.

Registers the loop nodes without changing ordinary ComfyUI or general Qwen
behavior. On older ComfyUI builds, startup adds the released H3-only tokenizer
tokens through a module-local alias, and Chain Context activates two internal
fallback patches inline on first execution:

  patch_layout   lifts the first/last-only keyframe anchor restriction,
                 moves pinned audio onto the clip's own timeline, and
                 keeps anchor coordinates aligned when refs shift the
                 layout cursor
  patch_payload  stops the refs branch clobbering keyframe cond latents,
                 so pinned video and pinned audio can be used together

Both wrappers are marker-gated. Niko's upstream copy and this vendored copy
recognize the same patch-ownership markers; whichever activates second stands
down. H3 workflows that use neither pack remain stock. If either self-test
fails the nodes still load but refuse the affected path, so an upstream
ComfyUI change produces a clear message rather than a silently wrong render.

When ComfyUI's native MiniMax H3 Add Guide API from merged PR #15439 is
available, core owns arbitrary-position video/audio guides, Ref2VA target
alignment, and keyframe/ref payload merging. This pack switches automatically
to native guide records and installs no H3 layout or payload wrapper. Version
0.5 emits a one-time update warning before using the legacy fallback.
"""

from .tokenizer_compat import (
    install_minimax_tokenizer_compat as _install_minimax_tokenizer_compat,
)

_MINIMAX_TOKENIZER_COMPAT_STATUS = _install_minimax_tokenizer_compat()

from .nodes import (
    NODE_CLASS_MAPPINGS as _CONTEXT_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _CONTEXT_NODE_DISPLAY_NAME_MAPPINGS,
)
from .chain_nodes import (
    CHAIN_NODE_CLASS_MAPPINGS,
    CHAIN_NODE_DISPLAY_NAME_MAPPINGS,
)
from .exact_final_timeline import install as _install_exact_final_timeline

_EXACT_FINAL_TIMELINE_BUILD = _install_exact_final_timeline()

# Fool for Love 0.6.37 continuation sanitation is intentionally activated only
# after the existing exact-final-timeline layer.  It wraps Loop End recursion
# and disk resume state only; the existing _context_apply_exact policy remains
# the sole owner of Masked AV / latent-guide / generated-audio fallback logic.
from . import chain_nodes as _exact_final_timeline_chain
from .exact_final_timeline_continuation_0637 import (
    activate_exact_continuation as _activate_exact_continuation,
)

_EXACT_FINAL_TIMELINE_CONTINUATION = _activate_exact_continuation(
    _exact_final_timeline_chain)

# Exact authored boundaries can coexist with generated-audio continuity even
# when H3 internally padded the predecessor.  Keep the RAW checkpoint immutable,
# rebuild picture context from delivered RGB, and slice generated audio so its
# endpoint is the authored cut rather than the disposable RAW tail.
from .exact_generated_audio_continuity_0637 import (
    activate_exact_generated_continuity as _activate_exact_generated_continuity,
)

_EXACT_GENERATED_AUDIO_CONTINUITY = _activate_exact_generated_continuity(
    _exact_final_timeline_chain)

# Final generated-audio assembly uses exact delivered checkpoint audio plus the
# private masked-AV overlap needed at joins.  Disposable RAW tail samples are
# excluded from the final write budget instead of forcing the V1 global block.
from . import exact_final_timeline as _exact_final_timeline_module
from .exact_generated_audio_tail_0637 import (
    activate_exact_generated_audio_tail as _activate_exact_generated_audio_tail,
)

_EXACT_GENERATED_AUDIO_TAIL = _activate_exact_generated_audio_tail(
    _exact_final_timeline_chain, _exact_final_timeline_module)

# Windows may transiently lock an older browser-facing Review MP4.  A sharing
# violation while deleting that disposable stale cache must not downgrade an
# already-successful synchronized Review mux to the silent fallback.  This guard
# wraps only _safe_unlink for final clip_*.review.mp4 cache paths; it does not
# alter _review_video or retain_previous behavior.
from .review_cleanup_win32_0637 import (
    activate_review_cleanup_win32_guard as _activate_review_cleanup_win32_guard,
)

_EXACT_FINAL_REVIEW_CLEANUP_WIN32 = _activate_review_cleanup_win32_guard(
    _exact_final_timeline_chain)

# Review Gate must receive the exact authored/delivered frame count as explicit
# metadata.  H3 raw 17k+5 length remains internal generation geometry; seed-only
# Reroll reads this public exact value and never falls back to raw H3 frames.
from .review_exact_frames_payload_0637 import (
    activate_review_exact_frames_payload as _activate_review_exact_frames_payload,
)

_EXACT_FINAL_REVIEW_FRAME_PAYLOAD = _activate_review_exact_frames_payload(
    _exact_final_timeline_chain)

# Resume preflight and recursive runtime can see the same Source Timeline audio
# through two representations: deferred AUDIO tensor first, then materialized
# path-backed state. Canonicalize deferred windows on absolute 24 fps sample
# boundaries so 44.1 kHz rounding cannot invalidate an unchanged predecessor.
from .resume_source_pcm_canonical_0637 import (
    activate_resume_source_pcm_canonical as _activate_resume_source_pcm_canonical,
)

_EXACT_FINAL_RESUME_SOURCE_PCM = _activate_resume_source_pcm_canonical(
    _exact_final_timeline_chain)

from .upscale_nodes import (
    UPSCALE_NODE_CLASS_MAPPINGS,
    UPSCALE_NODE_DISPLAY_NAME_MAPPINGS,
)
from .probe_node import (
    NODE_CLASS_MAPPINGS as _PROBE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _PROBE_NODE_DISPLAY_NAME_MAPPINGS,
)
from .masking_nodes import (
    NODE_CLASS_MAPPINGS as _MASKING_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASKING_NODE_DISPLAY_NAME_MAPPINGS,
)
from .master_audio_context import (
    NODE_CLASS_MAPPINGS as _MASTER_AUDIO_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_AUDIO_NODE_DISPLAY_NAME_MAPPINGS,
)
from .master_video_export_0637 import (
    NODE_CLASS_MAPPINGS as _MASTER_VIDEO_EXPORT_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_VIDEO_EXPORT_DISPLAY_NAMES,
)
from .audio_mode_switch_0637 import (
    NODE_CLASS_MAPPINGS as _AUDIO_MODE_SWITCH_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _AUDIO_MODE_SWITCH_DISPLAY_NAMES,
)
from .masked_bridge import (
    NODE_CLASS_MAPPINGS as _MASKED_BRIDGE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASKED_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS,
)
from .source_av_target import (
    NODE_CLASS_MAPPINGS as _SOURCE_AV_TARGET_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _SOURCE_AV_TARGET_NODE_DISPLAY_NAME_MAPPINGS,
)
from .reference_video_fade import (
    NODE_CLASS_MAPPINGS as _REFERENCE_VIDEO_FADE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _REFERENCE_VIDEO_FADE_DISPLAY_NAMES,
)
from .visual_context_schedule import (
    NODE_CLASS_MAPPINGS as _VISUAL_CONTEXT_SCHEDULE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _VISUAL_CONTEXT_SCHEDULE_DISPLAY_NAMES,
)

NODE_CLASS_MAPPINGS = dict(_CONTEXT_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(CHAIN_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(UPSCALE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_PROBE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASKING_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASTER_AUDIO_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASTER_VIDEO_EXPORT_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_AUDIO_MODE_SWITCH_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASKED_BRIDGE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_SOURCE_AV_TARGET_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_REFERENCE_VIDEO_FADE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_VISUAL_CONTEXT_SCHEDULE_NODE_CLASS_MAPPINGS)

NODE_DISPLAY_NAME_MAPPINGS = dict(_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(CHAIN_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(UPSCALE_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_PROBE_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASKING_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_AUDIO_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_VIDEO_EXPORT_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(_AUDIO_MODE_SWITCH_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASKED_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_SOURCE_AV_TARGET_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(
    _REFERENCE_VIDEO_FADE_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(
    _VISUAL_CONTEXT_SCHEDULE_DISPLAY_NAMES)

WEB_DIRECTORY = "./web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
