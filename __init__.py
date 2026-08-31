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

from . import chain_nodes as _exact_final_timeline_chain
from . import exact_final_timeline as _exact_final_timeline_module
from .exact_final_timeline_continuation_0637 import (
    activate_exact_continuation as _activate_exact_continuation,
)

_EXACT_FINAL_TIMELINE_CONTINUATION = _activate_exact_continuation(
    _exact_final_timeline_chain)

from .exact_generated_audio_tail_0637 import (
    activate_exact_generated_audio_tail as _activate_exact_generated_audio_tail,
)

_EXACT_FINAL_GENERATED_AUDIO_TAIL = _activate_exact_generated_audio_tail(
    _exact_final_timeline_chain, _exact_final_timeline_module)

from .exact_generated_audio_boundary_0637 import (
    activate_exact_generated_audio_boundary as _activate_exact_generated_audio_boundary,
)

_EXACT_FINAL_GENERATED_AUDIO_BOUNDARY = _activate_exact_generated_audio_boundary(
    _exact_final_timeline_chain)

from .review_cleanup_win32_0637 import (
    activate_review_cleanup_win32_guard as _activate_review_cleanup_win32_guard,
)

_EXACT_FINAL_REVIEW_CLEANUP_WIN32 = _activate_review_cleanup_win32_guard(
    _exact_final_timeline_chain)

from .review_exact_frames_payload_0637 import (
    activate_review_exact_frames_payload as _activate_review_exact_frames_payload,
)

_EXACT_FINAL_REVIEW_FRAME_PAYLOAD = _activate_review_exact_frames_payload(
    _exact_final_timeline_chain)

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
from . import master_video_export_0637 as _master_video_export_module
from .master_export_audio_verify_0637 import (
    activate_master_export_audio_verify as _activate_master_export_audio_verify,
)

_MASTER_EXPORT_AUDIO_VERIFY = _activate_master_export_audio_verify(
    _master_video_export_module, _exact_final_timeline_chain)

from .audio_mode_switch_0637 import (
    NODE_CLASS_MAPPINGS as _AUDIO_MODE_SWITCH_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _AUDIO_MODE_SWITCH_DISPLAY_NAMES,
)
from .master_simple_ui import (
    NODE_CLASS_MAPPINGS as _MASTER_SIMPLE_UI_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_SIMPLE_UI_DISPLAY_NAMES,
)
from .master_export_simple import (
    NODE_CLASS_MAPPINGS as _MASTER_EXPORT_SIMPLE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_EXPORT_SIMPLE_DISPLAY_NAMES,
)
from .master_video_mode import (
    NODE_CLASS_MAPPINGS as _MASTER_VIDEO_MODE_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_VIDEO_MODE_DISPLAY_NAMES,
)
from .master_policy_router import (
    NODE_CLASS_MAPPINGS as _MASTER_POLICY_ROUTER_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _MASTER_POLICY_ROUTER_DISPLAY_NAMES,
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
NODE_CLASS_MAPPINGS.update(_MASTER_SIMPLE_UI_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASTER_EXPORT_SIMPLE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASTER_VIDEO_MODE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_MASTER_POLICY_ROUTER_NODE_CLASS_MAPPINGS)
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
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_SIMPLE_UI_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_EXPORT_SIMPLE_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_VIDEO_MODE_DISPLAY_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_POLICY_ROUTER_DISPLAY_NAMES)
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
