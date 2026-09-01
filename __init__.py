"""DrMacabre MiniMax H3 MASTER companion nodepack.

This branch packages the current MASTER workflow/runtime as an independent
ComfyUI custom-node pack that can be installed beside Ethan's legacy
``ComfyUI-MiniMaxH3-Contex-Loop`` in the same ordinary ComfyUI process.

The implementation intentionally keeps its own copy of the H3 runtime, patches
only that local copy, exports collision-free public node ids, and serves a
private frontend/API namespace. It never imports or edits Ethan's installed
nodepack and it refuses legacy compatibility paths that would mutate shared
ComfyUI H3/tokenizer classes.
"""

from pathlib import Path

from .companion_namespace import (
    install_import_shims as _install_import_shims,
    namespace_display_mappings as _namespace_display_mappings,
    namespace_node_mappings as _namespace_node_mappings,
    prepare_companion_web_directory as _prepare_companion_web_directory,
    register_owned_node_ids as _register_owned_node_ids,
    restore_import_shims as _restore_import_shims,
    rewrite_package_node_id_literals as _rewrite_package_node_id_literals,
)
from .companion_runtime_policy import (
    install_native_only_guide_policy as _install_native_only_guide_policy,
    require_native_minimax_tokenizer as _require_native_minimax_tokenizer,
)

# During our own module imports only, expose package-local PromptServer and
# GraphBuilder facades. Modules capture those facades, then the real ComfyUI
# globals are restored before this package import returns.
_IMPORT_SHIM_STATE = _install_import_shims()
try:
    # Do not run tokenizer_compat.install_minimax_tokenizer_compat() here. That
    # compatibility path rewrites a shared ComfyUI module alias and would affect
    # Ethan's pack in the same process. The companion requires native core.
    _MINIMAX_TOKENIZER_STATUS = _require_native_minimax_tokenizer()

    # Import our local nodes module first, replace its legacy process-global H3
    # fallback entry points with native-only guards, THEN import chain_nodes so
    # it captures the isolated functions.
    from . import nodes as _companion_nodes_module

    _COMPANION_GUIDE_POLICY = _install_native_only_guide_policy(
        _companion_nodes_module)

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

    from . import masked_context as _master_masked_context
    from .disposable_audio_head_0637 import (
        activate_disposable_audio_head as _activate_disposable_audio_head,
    )

    _MASTER_DISPOSABLE_AUDIO_HEAD = _activate_disposable_audio_head(
        _master_masked_context)

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
finally:
    _restore_import_shims(_IMPORT_SHIM_STATE)


# Build the complete *original* id table first. Internal mapping keys retain
# these source ids, but ComfyUI never sees them from this companion package.
_ORIGINAL_NODE_CLASS_MAPPINGS = dict(_CONTEXT_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(CHAIN_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(UPSCALE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_PROBE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASKING_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_AUDIO_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_VIDEO_EXPORT_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_AUDIO_MODE_SWITCH_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_SIMPLE_UI_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_EXPORT_SIMPLE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_VIDEO_MODE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASTER_POLICY_ROUTER_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_MASKED_BRIDGE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_SOURCE_AV_TARGET_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_REFERENCE_VIDEO_FADE_NODE_CLASS_MAPPINGS)
_ORIGINAL_NODE_CLASS_MAPPINGS.update(_VISUAL_CONTEXT_SCHEDULE_NODE_CLASS_MAPPINGS)

_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS = dict(_CONTEXT_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(CHAIN_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(UPSCALE_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_PROBE_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASKING_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_AUDIO_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_VIDEO_EXPORT_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_AUDIO_MODE_SWITCH_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_SIMPLE_UI_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_EXPORT_SIMPLE_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_VIDEO_MODE_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASTER_POLICY_ROUTER_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_MASKED_BRIDGE_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_SOURCE_AV_TARGET_NODE_DISPLAY_NAME_MAPPINGS)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_REFERENCE_VIDEO_FADE_DISPLAY_NAMES)
_ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS.update(_VISUAL_CONTEXT_SCHEDULE_DISPLAY_NAMES)

# GraphBuilder facades captured above consult this exact set at execution time.
_register_owned_node_ids(_ORIGINAL_NODE_CLASS_MAPPINGS.keys())

# The inherited runtime contains a few exact class_type comparisons and explicit
# package-owned GraphBuilder class strings. Rewrite those *inside this loaded
# package only* so migrated MASTER workflows stay fully inside the companion id
# namespace. Generic ComfyUI node ids remain unchanged.
_RUNTIME_NODE_LITERAL_REWRITE_COUNT = _rewrite_package_node_id_literals(__name__)

# These are the only public machine ids exported to ComfyUI.
NODE_CLASS_MAPPINGS = _namespace_node_mappings(_ORIGINAL_NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS = _namespace_display_mappings(
    _ORIGINAL_NODE_CLASS_MAPPINGS,
    _ORIGINAL_NODE_DISPLAY_NAME_MAPPINGS,
)

# Generate a browser bundle that targets only the namespaced nodes and API.
WEB_DIRECTORY = _prepare_companion_web_directory(
    Path(__file__).resolve().parent,
    _ORIGINAL_NODE_CLASS_MAPPINGS.keys(),
)

COMPANION_NODE_ID_PREFIX = "DrMacabreH3Master_"
COMPANION_PACK_ID = "drmacabre-minimax-h3-master"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "COMPANION_NODE_ID_PREFIX",
    "COMPANION_PACK_ID",
]
