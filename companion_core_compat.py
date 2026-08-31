"""Companion-local compatibility for older MiniMax H3 ComfyUI cores.

The MASTER companion must coexist with Ethan's legacy nodepack in the same
ComfyUI process.  Therefore this module never assigns into ``comfy.*`` classes
or modules.  Compatibility is carried only by the MODEL/CLIP objects returned
from :class:`MiniMaxH3MasterCoreCompat`:

* tokenizer PR #15808 is emulated by a private CLIP tokenizer proxy;
* masked-AV PR #15375 is emulated by a cloned ModelPatcher whose object patches
  temporarily swap only that loaded model instance to private subclasses;
* the pre-PR sampler mask handoff is bridged with the clone-local
  ``denoise_mask_function`` hook instead of replacing KSamplerX0Inpaint.

ModelPatcher restores ``__class__`` after unloading the clone, so Ethan's model
instance is not left with companion method shadows.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


COMPAT_MARKER = "drmacabre_h3_master_scoped_core_compat_v1"

MINIMAX_EXTRA_SPECIAL_TOKENS = {
    "<d>": 151669,
    "</d>": 151670,
    "<|cutoff|>": 151671,
    "<|lyrics_start|>": 151672,
    "<|lyrics_end|>": 151673,
    "<|caption_start|>": 151674,
    "<|caption_end|>": 151675,
}
_SPECIAL_TOKEN_RE = re.compile(
    "(" + "|".join(
        re.escape(token)
        for token in sorted(MINIMAX_EXTRA_SPECIAL_TOKENS, key=len, reverse=True)
    ) + ")"
)


class _MiniMaxSpecialTokenProxy:
    """Add the seven #15808 token IDs without mutating the shared tokenizer."""

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def tokenize_with_weights(
            self, text: str, return_word_ids: bool = False, **kwargs):
        if not any(token in text for token in MINIMAX_EXTRA_SPECIAL_TOKENS):
            return self._inner.tokenize_with_weights(
                text, return_word_ids=return_word_ids, **kwargs)

        merged: list[tuple[Any, float, int]] = []
        word_offset = 0
        for piece in _SPECIAL_TOKEN_RE.split(text):
            if not piece:
                continue
            token_id = MINIMAX_EXTRA_SPECIAL_TOKENS.get(piece)
            if token_id is not None:
                # Added-special-token entries are structural, not prompt words.
                merged.append((int(token_id), 1.0, 0))
                continue

            batches = self._inner.tokenize_with_weights(
                piece, return_word_ids=True, **kwargs)
            if len(batches) != 1:
                raise ValueError(
                    "MASTER MiniMax tokenizer compatibility expected one Qwen "
                    "batch per prompt span, got %d." % len(batches))
            max_word = 0
            for item in batches[0]:
                if len(item) != 3:
                    raise ValueError(
                        "MASTER MiniMax tokenizer compatibility received an "
                        "unexpected token tuple: %r" % (item,))
                token, weight, word_id = item
                word_id = int(word_id)
                max_word = max(max_word, word_id)
                merged.append((
                    token,
                    float(weight),
                    word_id + word_offset if word_id else 0,
                ))
            word_offset += max_word

        if return_word_ids:
            return [merged]
        return [[(token, weight) for token, weight, _word in merged]]


def _native_tokenizer_available() -> bool:
    try:
        import comfy.text_encoders.minimax as minimax
    except Exception:
        return False
    return getattr(minimax, "MiniMaxQwenSDTokenizer", None) is not None


def _private_minimax_clip(clip: Any) -> tuple[Any, str]:
    if _native_tokenizer_available():
        return clip, "native tokenizer"
    if not callable(getattr(clip, "clone", None)):
        raise ValueError("MASTER Core Compat requires a ComfyUI CLIP object.")

    private = clip.clone()
    tokenizer = getattr(private, "tokenizer", None)
    if tokenizer is None:
        raise ValueError("MASTER Core Compat received a CLIP without tokenizer.")
    qwen = getattr(tokenizer, "qwen3vl_32b", None)
    if qwen is None:
        raise ValueError(
            "MASTER Core Compat requires the MiniMax H3 Qwen3-VL tokenizer. "
            "Load the CLIP with type=minimax.")

    private_tokenizer = copy.copy(tokenizer)
    private_tokenizer.qwen3vl_32b = _MiniMaxSpecialTokenProxy(qwen)
    private.tokenizer = private_tokenizer
    return private, "scoped tokenizer PR #15808"


@dataclass
class _MaskState:
    current: Any = None


def _mask_row_values(mask, latent_t: int, lat_h: int, lat_w: int):
    import torch

    m = torch.nn.functional.pad(
        mask,
        (0, lat_w - mask.shape[-1], 0, lat_h - mask.shape[-2]),
        mode="replicate",
    )
    m = m.reshape(
        latent_t, lat_h // 2, 2, lat_w // 2, 2).amax(dim=(2, 4))
    values = m.reshape(-1)
    if bool((values >= 1.0 - 1e-3).all()):
        return None
    return values


def _pool_masks_to_token_grid(owner, masks):
    import torch

    video_mask = masks[0]
    h, w = video_mask.shape[-2:]
    ph, pw = owner.diffusion_model.patch_size[1:]
    lead = video_mask.shape[:-2]
    video_mask = torch.nn.functional.pad(
        video_mask.reshape((-1,) + video_mask.shape[-3:]),
        (0, -w % pw, 0, -h % ph),
        mode="replicate",
    )
    video_mask = video_mask.reshape(lead + video_mask.shape[-2:])
    video_mask = video_mask.reshape(
        video_mask.shape[:-2]
        + (video_mask.shape[-2] // ph, ph,
           video_mask.shape[-1] // pw, pw)
    ).amax(dim=(-3, -1))
    pooled = [
        video_mask.repeat_interleave(ph, dim=-2)
        .repeat_interleave(pw, dim=-1)[..., :h, :w]
    ]
    if len(masks) > 1:
        audio_mask = masks[1].amax(dim=1, keepdim=True)
        pooled.append(audio_mask.expand_as(masks[1]).contiguous())
    return pooled


def _token_grid_masks(owner, denoise_mask, latent_shapes):
    import torch
    import comfy.utils as utils

    masks = utils.unpack_latents(denoise_mask, latent_shapes)
    return [
        torch.ceil(mask * 256.0) / 256.0
        for mask in _pool_masks_to_token_grid(owner, masks)
    ]


def _denoise_mask_values(owner, denoise_mask, latent_shapes):
    import torch

    if latent_shapes is None or len(latent_shapes) < 2:
        return {}
    masks = _token_grid_masks(owner, denoise_mask, latent_shapes)
    out = {}
    if torch.amin(masks[0]).item() < 1.0 - 1e-3:
        out["denoise_mask"] = masks[0][:1, :1].clone()
    if torch.amin(masks[1]).item() < 1.0 - 1e-3:
        out["audio_denoise_mask"] = masks[1][:1].amax(
            dim=1, keepdim=True)
    return out


def _scoped_h3_inner_forward(
        self, x, timestep, context, transformer_options={},
        minimax_payload=None, denoise_mask=None, audio_denoise_mask=None,
        **kwargs):
    """PR #15375 diffusion behavior, scoped to one ModelPatcher load."""
    import torch
    import comfy.ldm.common_dit
    import comfy.ldm.minimax.model as h3m
    import comfy.model_management
    import comfy.model_prefetch

    video_x, audio_x = x[0], x[1]
    orig_t, orig_h, orig_w = (
        video_x.shape[2], video_x.shape[3], video_x.shape[4])
    video_x = comfy.ldm.common_dit.pad_to_patch_size(
        video_x, self.patch_size)
    if video_x.shape[0] != 1:
        raise ValueError("MiniMax H3 supports batch size 1")
    payload = minimax_payload or {}
    device = video_x.device
    dtype = context.dtype

    latent_t, lat_h, lat_w = (
        video_x.shape[2], video_x.shape[3], video_x.shape[4])
    audio_t = audio_x.shape[-1]
    text_len = context.shape[1]
    layout = payload.get("layout")
    if (layout is None
            or layout.signature != (
                text_len, latent_t, lat_h, lat_w, audio_t)):
        layout = h3m.PackedLayout(
            text_len, latent_t, lat_h, lat_w, audio_t,
            keyframes=payload.get("keyframes"), refs=payload.get("refs"))

    shift_v = float(transformer_options.get(
        "minimax_h3_sigma_shift_video", self.sigma_shift_video))
    shift_a = float(transformer_options.get(
        "minimax_h3_sigma_shift_audio", self.sigma_shift_audio))
    sigma_v = (timestep.flatten()[0] / 1000.0).float().clamp(min=1e-6)
    t_v = float(1.0 - sigma_v)
    t_a = float(1.0 - h3m.time_shift_sigma(sigma_v, shift_v, shift_a))

    vis_aug = float(payload.get(
        "visual_cond_noise_aug", h3m.VISUAL_COND_TIMESTEP))
    aud_aug = float(payload.get(
        "audio_cond_noise_aug", h3m.AUDIO_COND_TIMESTEP))
    seg_t = {
        "text": t_v,
        "video": t_v,
        "audio": t_a,
        "cond": max(t_v, vis_aug),
        "ref_img": max(t_v, vis_aug),
        "cond_audio": max(t_a, aud_aug),
        "ref_audio": max(t_a, aud_aug),
    }

    t_pin_v = max(t_v, h3m.VISUAL_COND_TIMESTEP)
    t_pin_a = max(t_a, h3m.AUDIO_COND_TIMESTEP)
    video_rows_t = None
    audio_rows_t = None
    if denoise_mask is not None:
        m = _mask_row_values(
            denoise_mask[0, 0].to(torch.float32), latent_t, lat_h, lat_w)
        if m is not None:
            rows_t = (1.0 - m * sigma_v.to(m.device)).clamp(max=t_pin_v)
            if rows_t.unique().numel() == 1:
                seg_t["video"] = float(rows_t[0])
            else:
                video_rows_t = rows_t
    if audio_denoise_mask is not None:
        m = audio_denoise_mask[0, 0].to(torch.float32).reshape(-1)
        if not bool((m >= 1.0 - 1e-3).all()):
            sigma_a = 1.0 - t_a
            rows_t = (1.0 - m * sigma_a).clamp(max=t_pin_a)
            if rows_t.unique().numel() == 1:
                seg_t["audio"] = float(rows_t[0])
            else:
                audio_rows_t = rows_t

    unique_t = sorted(
        {t_v, t_a}
        | {seg_t[k] for _, _, k in layout.segments}
        | (set(video_rows_t.unique().tolist())
           if video_rows_t is not None else set())
        | (set(audio_rows_t.unique().tolist())
           if audio_rows_t is not None else set())
    )
    t_row = {value: index for index, value in enumerate(unique_t)}
    seg_tag = {
        "text": 1,
        "video": 0,
        "audio": 2,
        "cond": 0,
        "ref_img": 0,
        "cond_audio": 2,
        "ref_audio": 2,
    }

    def rows_to_mod_index(rows_t, tag):
        levels = rows_t.unique()
        base = torch.tensor(
            [t_row[value] * 3 + tag for value in levels.tolist()],
            dtype=torch.long,
            device=rows_t.device,
        )
        return base[torch.searchsorted(levels, rows_t)]

    text_tags = payload.get("text_token_tags")
    mod_segments = []
    for a, b, kind in layout.segments:
        row_base = t_row[seg_t[kind]] * 3
        if kind == "text" and text_tags is not None:
            tags = text_tags.view(-1).tolist()
            run_start = 0
            for i in range(1, b - a + 1):
                if i == b - a or tags[i] != tags[run_start]:
                    mod_segments.append((
                        a + run_start,
                        a + i,
                        row_base + int(tags[run_start]),
                    ))
                    run_start = i
        elif kind == "video" and video_rows_t is not None:
            mod_segments.append((
                a, b, rows_to_mod_index(video_rows_t, seg_tag[kind])))
        elif kind == "audio" and audio_rows_t is not None:
            mod_segments.append((
                a, b, rows_to_mod_index(audio_rows_t, seg_tag[kind])))
        else:
            mod_segments.append((a, b, row_base + seg_tag[kind]))

    img_update = layout.img_update.to(device)
    audio_update = layout.audio_update.to(device)
    video_rows = h3m.patchify_video(
        video_x.to(torch.float32), self.patch_size)
    audio_rows = h3m.pack_audio(audio_x.to(torch.float32))
    cond_video_rows = self._cond_video_rows(payload, device)
    cond_audio_rows = self._cond_audio_rows(payload, device)

    all_video_rows = video_rows
    if cond_video_rows is not None:
        all_video_rows = torch.empty(
            img_update.shape[0], video_rows.shape[1],
            dtype=torch.float32, device=device)
        all_video_rows[~img_update] = cond_video_rows
        all_video_rows[img_update] = video_rows
    all_audio_rows = audio_rows
    if cond_audio_rows is not None:
        all_audio_rows = torch.empty(
            audio_update.shape[0], audio_rows.shape[1],
            dtype=torch.float32, device=device)
        all_audio_rows[~audio_update] = cond_audio_rows
        all_audio_rows[audio_update] = audio_rows

    video_embed = self.video_patch_proj(all_video_rows).to(dtype)
    audio_embed = self.audio_patch_proj(all_audio_rows).to(dtype)
    text_states = context[0]
    if text_states.shape[-1] != self.hidden_size:
        text_states = self.token_refiner(
            self.condition_proj(text_states),
            transformer_options=transformer_options,
        )

    h = torch.empty(
        layout.seq_len, self.hidden_size, dtype=dtype, device=device)
    voff = aoff = 0
    for a, b, kind in layout.segments:
        count = b - a
        if kind == "text":
            h[a:b] = text_states
        elif kind in ("cond", "ref_img", "video"):
            h[a:b] = video_embed[voff:voff + count]
            voff += count
        else:
            h[a:b] = audio_embed[aoff:aoff + count]
            aoff += count

    t_vals = torch.tensor(unique_t, dtype=torch.float32, device=device)
    if self.use_adaln_curves:
        table = comfy.model_management.cast_to(
            self.adaln_t_table, device=device)
        pos = t_vals.clamp(0.0, 1.0) * (table.shape[0] - 1)
        i0 = pos.floor().long().clamp(max=table.shape[0] - 2)
        t_emb = torch.lerp(
            table[i0], table[i0 + 1], (pos - i0).unsqueeze(1))
    else:
        t_emb = self.time_embedder(t_vals).to(dtype)

    rope_freqs = h3m.rope_rotation_table(
        self.rope_freqs(layout.position_ids, device), dtype)

    patches_replace = transformer_options.get("patches_replace", {})
    blocks_replace = patches_replace.get("dit", {})
    prefetch_queue = comfy.model_prefetch.make_prefetch_queue(
        list(self.blocks), device, transformer_options)
    for index, block in enumerate(self.blocks):
        comfy.model_prefetch.prefetch_queue_pop(
            prefetch_queue, device, block)
        if ("double_block", index) in blocks_replace:
            def block_wrap(args):
                return {
                    "img": block(
                        args["img"], args["t_emb"], args["mod_segments"],
                        args["rope_freqs"],
                        transformer_options=args["transformer_options"])
                }

            h = blocks_replace[("double_block", index)](
                {
                    "img": h,
                    "t_emb": t_emb,
                    "mod_segments": mod_segments,
                    "rope_freqs": rope_freqs,
                    "transformer_options": transformer_options,
                },
                {"original_block": block_wrap},
            )["img"]
        else:
            h = block(
                h, t_emb, mod_segments, rope_freqs,
                transformer_options=transformer_options)
    if prefetch_queue is not None:
        comfy.model_prefetch.prefetch_queue_pop(prefetch_queue, device, None)

    va, vb, _ = next(
        segment for segment in layout.segments if segment[2] == "video")
    aa, ab, _ = next(
        segment for segment in layout.segments if segment[2] == "audio")
    if video_rows_t is not None:
        video_seg = (va, vb, rows_to_mod_index(video_rows_t, 0) // 3)
    else:
        video_seg = (va, vb, t_row[seg_t["video"]])
    if audio_rows_t is not None:
        audio_seg = (aa, ab, rows_to_mod_index(audio_rows_t, 0) // 3)
    else:
        audio_seg = (aa, ab, t_row[seg_t["audio"]])

    video_out, audio_out = self.final_layer(
        h, t_emb, video_seg, audio_seg)
    video_out = h3m.unpatchify_video(
        video_out,
        latent_t,
        lat_h // 2,
        lat_w // 2,
        self.latents_dim,
        self.patch_size,
    )
    video_out = video_out[:, :, :orig_t, :orig_h, :orig_w]
    audio_out = h3m.unpack_audio(audio_out)
    return [-video_out.to(video_x.dtype), -audio_out.to(audio_x.dtype)]


def _native_mask_available() -> bool:
    try:
        from .h3_mask_compat import capability_status as engine_status
        from .h3_mask_payload_compat import capability_status as payload_status
        engine = engine_status()
        payload = payload_status()
    except Exception:
        return False
    return bool(
        engine.get("scale_latent_inpaint_native")
        and engine.get("sampler_mask_blend_native")
        and engine.get("mask_engine_native")
        and engine.get("mask_helpers_native")
        and payload.get("native_av_mask_payload")
    )


def _scoped_mask_model(model: Any) -> tuple[Any, str]:
    if _native_mask_available():
        return model, "native AV mask"
    if not callable(getattr(model, "clone", None)):
        raise ValueError("MASTER Core Compat requires a ComfyUI MODEL object.")

    try:
        import comfy.conds
        import comfy.model_base
        import comfy.utils as utils
    except Exception as exc:
        raise RuntimeError(
            "MASTER Core Compat could not import ComfyUI H3 runtime.") from exc

    private = model.clone()
    owner = getattr(private, "model", None)
    h3_cls = getattr(comfy.model_base, "MiniMaxH3", None)
    if h3_cls is None or not isinstance(owner, h3_cls):
        raise ValueError(
            "MASTER Core Compat requires a MiniMax H3 MODEL after "
            "MiniMaxH3SigmaShift.")
    diffusion = getattr(owner, "diffusion_model", None)
    if diffusion is None:
        raise ValueError("MASTER Core Compat found no H3 diffusion model.")

    original_owner_class = owner.__class__
    original_diffusion_class = diffusion.__class__
    original_extra_conds = original_owner_class.extra_conds
    original_scale = original_owner_class.scale_latent_inpaint
    state = _MaskState()

    def extra_conds(self, **kwargs):
        out = original_extra_conds(self, **kwargs)
        denoise_mask = kwargs.get("denoise_mask")
        latent_shapes = kwargs.get("latent_shapes")
        if denoise_mask is not None:
            values = _denoise_mask_values(self, denoise_mask, latent_shapes)
            out.update({
                name: comfy.conds.CONDRegular(value)
                for name, value in values.items()
            })
        return out

    def scale_latent_inpaint(
            self, sigma, noise, latent_image, x=None,
            denoise_mask=None, **kwargs):
        shapes = getattr(self, "latent_shapes", None)
        if shapes is None or len(shapes) < 2:
            return original_scale(
                self,
                sigma=sigma,
                noise=noise,
                latent_image=latent_image,
                x=x,
                **kwargs,
            )

        cleans = utils.unpack_latents(latent_image, shapes)
        noises = utils.unpack_latents(noise, shapes)
        import torch
        import comfy.ldm.minimax.model as h3m

        aug = h3m.VISUAL_COND_TIMESTEP
        cleans[0] = aug * cleans[0] + (1.0 - aug) * noises[0]
        scale = self.audio_scale()
        if scale != 1.0:
            model_sampling = self.model_sampling
            sigma_v = sigma.clamp(min=1e-6)
            sigma_a = h3m.time_shift_sigma(
                sigma_v, model_sampling.shift, model_sampling.audio_shift)
            factor = (sigma_v / sigma_a) / scale
            cleans[1] = cleans[1] * factor.view(
                factor.shape[:1] + (1,) * (cleans[1].ndim - 1)
            ).to(cleans[1].dtype)
        injected = utils.pack_latents(cleans)[0]

        active_mask = denoise_mask if denoise_mask is not None else state.current
        if x is None or active_mask is None:
            return injected
        token_grid_mask = utils.pack_latents(
            _token_grid_masks(self, active_mask, shapes))[0]
        x_blend_weight = (
            (token_grid_mask - active_mask)
            / (1.0 - active_mask).clamp(min=1e-6)
        )
        x_blend_weight = torch.where(
            active_mask < 1.0,
            x_blend_weight.clamp(0.0, 1.0),
            torch.zeros_like(x_blend_weight),
        )
        return injected + x_blend_weight.to(injected.dtype) * (x - injected)

    owner_class = type(
        "DrMacabreH3MasterScopedMiniMaxH3",
        (original_owner_class,),
        {
            "__module__": __name__,
            "extra_conds": extra_conds,
            "scale_latent_inpaint": scale_latent_inpaint,
            COMPAT_MARKER: True,
        },
    )
    diffusion_class = type(
        "DrMacabreH3MasterScopedMiniMaxH3Model",
        (original_diffusion_class,),
        {
            "__module__": __name__,
            "_forward": _scoped_h3_inner_forward,
            COMPAT_MARKER: True,
        },
    )

    previous_mask_function = private.model_options.get("denoise_mask_function")

    def track_mask(sigma, denoise_mask, extra_options=None):
        value = denoise_mask
        if callable(previous_mask_function):
            try:
                value = previous_mask_function(
                    sigma, denoise_mask,
                    {} if extra_options is None else extra_options)
            except TypeError:
                value = previous_mask_function(sigma, denoise_mask)
        state.current = value
        return value

    private.set_model_denoise_mask_function(track_mask)
    # Patch only __class__ pointers. ModelPatcher restores the exact original
    # classes when this clone unloads, leaving no instance-method shadow behind.
    private.add_object_patch("__class__", owner_class)
    private.add_object_patch("diffusion_model.__class__", diffusion_class)
    private.model_options[COMPAT_MARKER] = {
        "mode": "scoped_pr15375",
        "owner_class": original_owner_class.__name__,
        "diffusion_class": original_diffusion_class.__name__,
    }
    return private, "scoped AV-mask PR #15375"


def has_scoped_mask_compat(model: Any) -> bool:
    options = getattr(model, "model_options", None)
    return bool(isinstance(options, dict) and options.get(COMPAT_MARKER))


class MiniMaxH3MasterCoreCompat:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "MiniMax H3 MODEL after core Sigma Shift."}),
                "clip": ("CLIP", {
                    "tooltip": "MiniMax H3 CLIP loaded with type=minimax."}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("model", "clip", "status")
    FUNCTION = "apply"
    CATEGORY = "conditioning/minimax/master/internal"
    DESCRIPTION = (
        "MASTER-only compatibility boundary. Uses native ComfyUI H3 features "
        "when present; otherwise carries tokenizer/masked-AV compatibility "
        "only on private MODEL/CLIP objects without patching shared core or "
        "Ethan's nodepack.")

    def apply(self, model, clip):
        private_model, model_status = _scoped_mask_model(model)
        private_clip, clip_status = _private_minimax_clip(clip)
        return (
            private_model,
            private_clip,
            "MASTER Core Compat: %s; %s" % (model_status, clip_status),
        )


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3MasterCoreCompat": MiniMaxH3MasterCoreCompat,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3MasterCoreCompat": "MASTER — Core Compatibility",
}


__all__ = [
    "COMPAT_MARKER",
    "MINIMAX_EXTRA_SPECIAL_TOKENS",
    "MiniMaxH3MasterCoreCompat",
    "has_scoped_mask_compat",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
