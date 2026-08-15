"""Capability-aware runtime compatibility for ComfyUI PR #15375.

This module contains the H3 AV-mask diffusion behavior and the narrow legacy
sampler bridge required by masked target-prefix continuation. It does not
touch ``MiniMaxH3.extra_conds``; payload extraction lives in
:mod:`h3_mask_payload_compat`.

Every capability is checked against the live ComfyUI implementation. Native
support wins; compatibility is installed only for missing pieces. Restarting
ComfyUI reverts all runtime modifications.

Originally adapted from seitanism/ComfyUI-H3-Motion-Context-MultiRef
(GPL-3.0). This compatibility snapshot now tracks ComfyUI PR #15375 through
commit 989e7a9, reviewed on 2026-08-15.
"""

from __future__ import annotations

import functools
import inspect
import logging
import types


_LOG = logging.getLogger("minimax_h3_context_loop.masked_prefix")
# Version 3 follows PR #15375's post-review mask-blend design. Version 2 used
# ``process_denoise_mask`` to replace the user's mask with its pooled token
# mask. The diffusion engine itself remains compatible, but the v2 model hooks
# must be replaced because they reintroduce the edge artifact fixed upstream.
_MARKER = "_h3_motion_context_pr15375_compat_v3"
_LEGACY_MARKER = "_h3_motion_context_pr15375_compat_v2"
_SAMPLER_MARKER = "_h3_motion_context_pr15375_sampler_blend_v3"
_ACTIVE_MASK_ATTR = "_h3_motion_context_active_denoise_mask_v3"


def _exec_into(module, source, name):
    namespace = module.__dict__
    exec(source, namespace)
    return namespace[name]


def _mark(fn, marker=_MARKER):
    try:
        setattr(fn, marker, True)
    except Exception:
        pass
    return fn


def _is_ours(fn):
    return bool(getattr(fn, _MARKER, False))


def _is_legacy_compat(fn):
    return bool(getattr(fn, _LEGACY_MARKER, False))


def _is_known_engine_compat(fn):
    return bool(_is_ours(fn) or _is_legacy_compat(fn))


def _is_sampler_compat(fn):
    return bool(getattr(fn, _SAMPLER_MARKER, False))


def _signature_has(fn, *names):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return all(name in params for name in names)


def _walk_code(value):
    if not isinstance(value, types.CodeType):
        return
    yield value
    for item in value.co_consts:
        if isinstance(item, types.CodeType):
            yield from _walk_code(item)


def _function_has_keyword_group(fn, *names):
    """Detect a Python call carrying a specific keyword-name tuple."""
    current = fn
    seen = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        for code in _walk_code(getattr(current, "__code__", None)) or ():
            for item in code.co_consts:
                if (isinstance(item, tuple)
                        and all(name in item for name in names)):
                    return True
        current = getattr(current, "__wrapped__", None)
    return False


def _sampler_call():
    try:
        import comfy.samplers as samplers
    except Exception:
        return None
    cls = getattr(samplers, "KSamplerX0Inpaint", None)
    return getattr(cls, "__call__", None) if cls is not None else None


def _sampler_passes_mask_to_scale(fn):
    return bool(
        callable(fn)
        and _function_has_keyword_group(
            fn, "sigma", "noise", "latent_image", "denoise_mask")
    )


def capability_status():
    import comfy.model_base as model_base
    import comfy.ldm.minimax.model as h3m

    cls = getattr(model_base, "MiniMaxH3", None)
    process = getattr(cls, "process_denoise_mask", None) if cls else None
    scale = getattr(cls, "scale_latent_inpaint", None) if cls else None

    process_native = bool(
        cls
        and "process_denoise_mask" in cls.__dict__
        and callable(process)
        and not _is_known_engine_compat(process)
    )
    scale_native = bool(
        cls
        and "scale_latent_inpaint" in cls.__dict__
        and callable(scale)
        and _signature_has(scale, "x", "denoise_mask")
        and not _is_known_engine_compat(scale)
    )
    sampler_call = _sampler_call()
    sampler_native = bool(
        _sampler_passes_mask_to_scale(sampler_call)
        and not _is_sampler_compat(sampler_call)
    )

    forward = getattr(getattr(h3m, "MiniMaxH3Model", None), "forward", None)
    inner = getattr(getattr(h3m, "MiniMaxH3Model", None), "_forward", None)
    final = getattr(getattr(h3m, "FinalLayer", None), "forward", None)
    engine_indicators = {
        "mask_row_values": callable(getattr(h3m, "mask_row_values", None)),
        "mod_row": callable(getattr(h3m, "_mod_row", None)),
        "forward_masks": callable(forward) and _signature_has(
            forward, "denoise_mask", "audio_denoise_mask"),
        "inner_masks": callable(inner) and _signature_has(
            inner, "denoise_mask", "audio_denoise_mask"),
        "final_layer": callable(final),
    }
    engine_complete = all(engine_indicators.values())
    engine_ours = bool(
        callable(forward)
        and callable(inner)
        and _is_known_engine_compat(forward)
        and _is_known_engine_compat(inner)
    )

    return {
        "process_denoise_mask_native": process_native,
        "process_denoise_mask_compat": bool(
            callable(process) and _is_ours(process)),
        "scale_latent_inpaint_native": scale_native,
        "scale_latent_inpaint_compat": bool(
            callable(scale) and _is_ours(scale)),
        "sampler_mask_blend_native": sampler_native,
        "sampler_mask_blend_compat": bool(
            callable(sampler_call) and _is_sampler_compat(sampler_call)),
        "mask_engine_complete": engine_complete,
        "mask_engine_native": bool(engine_complete and not engine_ours),
        "mask_engine_compat": engine_ours,
        "mask_engine_indicators": engine_indicators,
    }


def _install_engine_compat(h3m):
    """Install the coupled MiniMax-H3 diffusion-mask engine from #15375."""
    mask_row_values = _exec_into(
        h3m,
        '''def mask_row_values(mask, latent_t, lat_h, lat_w):
    # [T,H,W], 1=generate -> per-2x2-patch-row float; None when all generate
    m = torch.nn.functional.pad(mask, (0, lat_w - mask.shape[-1], 0, lat_h - mask.shape[-2]), mode="replicate")
    m = m.reshape(latent_t, lat_h // 2, 2, lat_w // 2, 2).amax(dim=(2, 4))
    values = m.reshape(-1)
    if bool((values >= 1.0 - 1e-3).all()):
        return None
    return values''',
        "mask_row_values",
    )
    mod_row = _exec_into(
        h3m,
        '''def _mod_row(vecs, row, dtype):
    return vecs[row].to(dtype)''',
        "_mod_row",
    )
    mod_scale_shift = _exec_into(
        h3m,
        '''def _mod_scale_shift(h, shift, scale, segments):
    for a, b, row in segments:
        h[a:b].mul_(1.0 + _mod_row(scale, row, h.dtype)).add_(_mod_row(shift, row, h.dtype))
    return h''',
        "_mod_scale_shift",
    )
    mod_gate = _exec_into(
        h3m,
        '''def _mod_gate(x, gate, other, segments):
    for a, b, row in segments:
        x[a:b].addcmul_(other[a:b], _mod_row(gate, row, x.dtype))
    return x''',
        "_mod_gate",
    )

    final_forward = _exec_into(
        h3m,
        '''def forward(self, x, t_emb, video_seg, audio_seg):
    shift, scale = self.adaln_proj(t_emb)

    def mod(seg):
        a, b, row = seg
        return (self.norm(x[a:b]) * (1.0 + _mod_row(scale, row, scale.dtype)) + _mod_row(shift, row, shift.dtype)).to(torch.float32)

    return self.video_out(mod(video_seg)), self.audio_out(mod(audio_seg))''',
        "forward",
    )
    h3m.FinalLayer.forward = final_forward

    h3_forward = _exec_into(
        h3m,
        '''def forward(self, x, timestep, context, transformer_options={}, minimax_payload=None, denoise_mask=None, audio_denoise_mask=None, **kwargs):
    # The sampler carries audio as (sigma_v / sigma_a) * x_audio; undo it
    # outside wrappers so both wrappers and network see its own latent/velocity.
    scale = float((minimax_payload or {}).get("audio_scale", 1.0))
    audio_src = x[1]
    if scale != 1.0:
        shift_v = float(transformer_options.get("minimax_h3_sigma_shift_video", self.sigma_shift_video))
        shift_a = float(transformer_options.get("minimax_h3_sigma_shift_audio", self.sigma_shift_audio))
        sigma_v = (timestep.flatten()[0] / 1000.0).float().clamp(min=1e-6)
        sigma_a = time_shift_sigma(sigma_v, shift_v, shift_a)
        carry = (sigma_a / sigma_v).to(audio_src.dtype)
        x = [x[0], audio_src * carry]

    out = comfy.patcher_extension.WrapperExecutor.new_class_executor(
        self._forward,
        self,
        comfy.patcher_extension.get_all_wrappers(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, transformer_options)
    ).execute(x, timestep, context, transformer_options, minimax_payload=minimax_payload,
              denoise_mask=denoise_mask, audio_denoise_mask=audio_denoise_mask, **kwargs)

    if scale != 1.0:
        out[1] = ((1.0 - scale) * (audio_src * carry)
                  + (1.0 + (scale - 1.0) * sigma_a).to(out[1].dtype) * out[1])
    return out''',
        "forward",
    )

    h3_inner_forward = _exec_into(
        h3m,
        '''def _forward(self, x, timestep, context, transformer_options={}, minimax_payload=None, denoise_mask=None, audio_denoise_mask=None, **kwargs):
    video_x, audio_x = x[0], x[1]
    orig_t, orig_h, orig_w = video_x.shape[2], video_x.shape[3], video_x.shape[4]
    video_x = comfy.ldm.common_dit.pad_to_patch_size(video_x, self.patch_size)
    if video_x.shape[0] != 1:
        raise ValueError("MiniMax H3 supports batch size 1")
    payload = minimax_payload or {}
    device = video_x.device
    dtype = context.dtype

    latent_t, lat_h, lat_w = video_x.shape[2], video_x.shape[3], video_x.shape[4]
    audio_t = audio_x.shape[-1]
    text_len = context.shape[1]
    layout = payload.get("layout")
    if layout is None or layout.signature != (text_len, latent_t, lat_h, lat_w, audio_t):
        layout = PackedLayout(text_len, latent_t, lat_h, lat_w, audio_t,
                              keyframes=payload.get("keyframes"),
                              refs=payload.get("refs"))

    # model_base passes model_sampling.timestep(sigma) = sigma * 1000
    shift_v = float(transformer_options.get("minimax_h3_sigma_shift_video", self.sigma_shift_video))
    shift_a = float(transformer_options.get("minimax_h3_sigma_shift_audio", self.sigma_shift_audio))
    sigma_v = (timestep.flatten()[0] / 1000.0).float().clamp(min=1e-6)
    t_v = float(1.0 - sigma_v)
    t_a = float(1.0 - time_shift_sigma(sigma_v, shift_v, shift_a))

    vis_aug = float(payload.get("visual_cond_noise_aug", VISUAL_COND_TIMESTEP))
    aud_aug = float(payload.get("audio_cond_noise_aug", AUDIO_COND_TIMESTEP))
    seg_t = {"text": t_v, "video": t_v, "audio": t_a,
             "cond": max(t_v, vis_aug), "ref_img": max(t_v, vis_aug),
             "cond_audio": max(t_a, aud_aug), "ref_audio": max(t_a, aud_aug)}

    # Mask m puts a row at sigma=m*sigma_stream; fully preserved rows clamp
    # at the stream's conditioning timestep.
    t_pin_v = max(t_v, VISUAL_COND_TIMESTEP)
    t_pin_a = max(t_a, AUDIO_COND_TIMESTEP)
    video_rows_t = None
    audio_rows_t = None
    if denoise_mask is not None:
        m = mask_row_values(denoise_mask[0, 0].to(torch.float32), latent_t, lat_h, lat_w)
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

    unique_t = sorted({t_v, t_a} | {seg_t[k] for _, _, k in layout.segments}
                      | (set(video_rows_t.unique().tolist()) if video_rows_t is not None else set())
                      | (set(audio_rows_t.unique().tolist()) if audio_rows_t is not None else set()))
    t_row = {t: i for i, t in enumerate(unique_t)}
    seg_tag = {"text": 1, "video": 0, "audio": 2, "cond": 0,
               "ref_img": 0, "cond_audio": 2, "ref_audio": 2}

    def rows_to_mod_index(rows_t, tag):
        levels = rows_t.unique()
        base = torch.tensor([t_row[v] * 3 + tag for v in levels.tolist()],
                            dtype=torch.long, device=rows_t.device)
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
                    mod_segments.append((a + run_start, a + i,
                                         row_base + int(tags[run_start])))
                    run_start = i
        elif kind == "video" and video_rows_t is not None:
            mod_segments.append((a, b, rows_to_mod_index(video_rows_t, seg_tag[kind])))
        elif kind == "audio" and audio_rows_t is not None:
            mod_segments.append((a, b, rows_to_mod_index(audio_rows_t, seg_tag[kind])))
        else:
            mod_segments.append((a, b, row_base + seg_tag[kind]))

    img_update = layout.img_update.to(device)
    audio_update = layout.audio_update.to(device)
    video_rows = patchify_video(video_x.to(torch.float32), self.patch_size)
    audio_rows = pack_audio(audio_x.to(torch.float32))
    cond_video_rows = self._cond_video_rows(payload, device)
    cond_audio_rows = self._cond_audio_rows(payload, device)

    all_video_rows = video_rows
    if cond_video_rows is not None:
        all_video_rows = torch.empty(img_update.shape[0], video_rows.shape[1], dtype=torch.float32, device=device)
        all_video_rows[~img_update] = cond_video_rows
        all_video_rows[img_update] = video_rows
    all_audio_rows = audio_rows
    if cond_audio_rows is not None:
        all_audio_rows = torch.empty(audio_update.shape[0], audio_rows.shape[1], dtype=torch.float32, device=device)
        all_audio_rows[~audio_update] = cond_audio_rows
        all_audio_rows[audio_update] = audio_rows

    video_embed = self.video_patch_proj(all_video_rows).to(dtype)
    audio_embed = self.audio_patch_proj(all_audio_rows).to(dtype)
    text_states = context[0]
    if text_states.shape[-1] != self.hidden_size:
        text_states = self.token_refiner(self.condition_proj(text_states),
                                         transformer_options=transformer_options)

    h = torch.empty(layout.seq_len, self.hidden_size, dtype=dtype, device=device)
    voff = aoff = 0
    for a, b, kind in layout.segments:
        n = b - a
        if kind == "text":
            h[a:b] = text_states
        elif kind in ("cond", "ref_img", "video"):
            h[a:b] = video_embed[voff:voff + n]
            voff += n
        else:
            h[a:b] = audio_embed[aoff:aoff + n]
            aoff += n

    t_vals = torch.tensor(unique_t, dtype=torch.float32, device=device)
    if self.use_adaln_curves:
        table = comfy.model_management.cast_to(self.adaln_t_table, device=device)
        pos = t_vals.clamp(0.0, 1.0) * (table.shape[0] - 1)
        i0 = pos.floor().long().clamp(max=table.shape[0] - 2)
        t_emb = torch.lerp(table[i0], table[i0 + 1], (pos - i0).unsqueeze(1))
    else:
        t_emb = self.time_embedder(t_vals).to(dtype)

    rope_freqs = rope_rotation_table(self.rope_freqs(layout.position_ids, device), dtype)

    patches_replace = transformer_options.get("patches_replace", {})
    blocks_replace = patches_replace.get("dit", {})
    prefetch_queue = comfy.model_prefetch.make_prefetch_queue(list(self.blocks), device, transformer_options)
    for i, block in enumerate(self.blocks):
        comfy.model_prefetch.prefetch_queue_pop(prefetch_queue, device, block)
        if ("double_block", i) in blocks_replace:
            def block_wrap(args):
                return {"img": block(args["img"], args["t_emb"], args["mod_segments"], args["rope_freqs"],
                                     transformer_options=args["transformer_options"])}
            h = blocks_replace[("double_block", i)](
                {"img": h, "t_emb": t_emb, "mod_segments": mod_segments,
                 "rope_freqs": rope_freqs,
                 "transformer_options": transformer_options},
                {"original_block": block_wrap})["img"]
        else:
            h = block(h, t_emb, mod_segments, rope_freqs,
                      transformer_options=transformer_options)
    if prefetch_queue is not None:
        comfy.model_prefetch.prefetch_queue_pop(prefetch_queue, device, None)

    va, vb, _ = next(s for s in layout.segments if s[2] == "video")
    aa, ab, _ = next(s for s in layout.segments if s[2] == "audio")
    if video_rows_t is not None:
        video_seg = (va, vb, rows_to_mod_index(video_rows_t, 0) // 3)
    else:
        video_seg = (va, vb, t_row[seg_t["video"]])
    if audio_rows_t is not None:
        audio_seg = (aa, ab, rows_to_mod_index(audio_rows_t, 0) // 3)
    else:
        audio_seg = (aa, ab, t_row[seg_t["audio"]])
    v, a = self.final_layer(h, t_emb, video_seg, audio_seg)

    video_out = unpatchify_video(v, latent_t, lat_h // 2, lat_w // 2,
                                self.latents_dim, self.patch_size)
    video_out = video_out[:, :, :orig_t, :orig_h, :orig_w]
    audio_out = unpack_audio(a)

    return [-video_out.to(video_x.dtype), -audio_out.to(audio_x.dtype)]''',
        "_forward",
    )
    h3m.MiniMaxH3Model.forward = h3_forward
    h3m.MiniMaxH3Model._forward = h3_inner_forward
    for fn in (
        mask_row_values,
        mod_row,
        mod_scale_shift,
        mod_gate,
        final_forward,
        h3_forward,
        h3_inner_forward,
    ):
        _mark(fn)


def _install_model_base_hooks(model_base):
    """Build the post-989e7a9 H3 model hooks.

    The identity preprocessing hook is only used on intermediate #15375
    builds whose sampler still calls it. Returning the original mask is
    essential: final pixel blending must retain the user's mask while H3's
    internal timestep labels use the pooled token grid.
    """
    process_denoise_mask = _exec_into(
        model_base,
        '''def process_denoise_mask(self, denoise_masks):
    return denoise_masks''',
        "process_denoise_mask",
    )
    pool_masks_to_token_grid = _exec_into(
        model_base,
        '''def _pool_masks_to_token_grid(self, masks):
    video_mask = masks[0]
    h, w = video_mask.shape[-2:]
    ph, pw = self.diffusion_model.patch_size[1:]
    lead = video_mask.shape[:-2]
    video_mask = torch.nn.functional.pad(video_mask.reshape((-1,) + video_mask.shape[-3:]), (0, -w % pw, 0, -h % ph), mode="replicate")
    video_mask = video_mask.reshape(lead + video_mask.shape[-2:])
    video_mask = video_mask.reshape(video_mask.shape[:-2] + (video_mask.shape[-2] // ph, ph, video_mask.shape[-1] // pw, pw)).amax(dim=(-3, -1))
    pooled = [video_mask.repeat_interleave(ph, dim=-2).repeat_interleave(pw, dim=-1)[..., :h, :w]]
    if len(masks) > 1:
        audio_mask = masks[1].amax(dim=1, keepdim=True)
        pooled.append(audio_mask.expand_as(masks[1]).contiguous())
    return pooled''',
        "_pool_masks_to_token_grid",
    )
    scale_latent_inpaint = _exec_into(
        model_base,
        '''def scale_latent_inpaint(self, sigma, noise, latent_image, x=None, denoise_mask=None, **kwargs):
    shapes = self.latent_shapes
    if shapes is None or len(shapes) < 2:
        return super(MiniMaxH3, self).scale_latent_inpaint(sigma=sigma, noise=noise, latent_image=latent_image, **kwargs)
    cleans = utils.unpack_latents(latent_image, shapes)
    noises = utils.unpack_latents(noise, shapes)
    aug = comfy.ldm.minimax.model.VISUAL_COND_TIMESTEP
    cleans[0] = aug * cleans[0] + (1.0 - aug) * noises[0]
    scale = self.audio_scale()
    if scale != 1.0:
        model_sampling = self.model_sampling
        sigma_v = sigma.clamp(min=1e-6)
        sigma_a = comfy.ldm.minimax.model.time_shift_sigma(sigma_v, model_sampling.shift, model_sampling.audio_shift)
        factor = (sigma_v / sigma_a) / scale
        cleans[1] = cleans[1] * factor.view(factor.shape[:1] + (1,) * (cleans[1].ndim - 1)).to(cleans[1].dtype)
    injected = utils.pack_latents(cleans)[0]
    if denoise_mask is None:
        denoise_mask = getattr(self, "_h3_motion_context_active_denoise_mask_v3", None)
    if x is None or denoise_mask is None:
        return injected
    masks = utils.unpack_latents(denoise_mask, shapes)
    pooled_token_grid = utils.pack_latents(self._pool_masks_to_token_grid(masks))[0]
    pooled_token_grid = torch.round(pooled_token_grid * 256.0) / 256.0
    x_blend_weight = (pooled_token_grid - denoise_mask) / (1.0 - denoise_mask).clamp(min=1e-6)
    x_blend_weight = torch.where(denoise_mask < 1.0, x_blend_weight.clamp(0.0, 1.0), torch.zeros_like(x_blend_weight))
    return injected + x_blend_weight.to(injected.dtype) * (x - injected)''',
        "scale_latent_inpaint",
    )
    for fn in (
        process_denoise_mask,
        pool_masks_to_token_grid,
        scale_latent_inpaint,
    ):
        _mark(fn)
    return process_denoise_mask, pool_masks_to_token_grid, scale_latent_inpaint


def _install_sampler_mask_bridge(model_base):
    """Give pre-989e7a9 samplers the mask argument added by that commit."""
    import comfy.samplers as samplers

    sampler_cls = getattr(samplers, "KSamplerX0Inpaint", None)
    if sampler_cls is None or not callable(getattr(sampler_cls, "__call__", None)):
        raise RuntimeError(
            "h3_masked_prefix: ComfyUI KSamplerX0Inpaint was not found.")
    current = sampler_cls.__call__
    if _sampler_passes_mask_to_scale(current) or _is_sampler_compat(current):
        return current

    @functools.wraps(current)
    def wrapper(self, x, sigma, denoise_mask, model_options=None, seed=None):
        target = getattr(getattr(self, "inner_model", None),
                         "inner_model", None)
        h3_cls = getattr(model_base, "MiniMaxH3", None)
        if h3_cls is None or not isinstance(target, h3_cls):
            return current(
                self, x, sigma, denoise_mask,
                model_options={} if model_options is None else model_options,
                seed=seed)

        missing = object()
        previous = getattr(target, _ACTIVE_MASK_ATTR, missing)
        setattr(target, _ACTIVE_MASK_ATTR, denoise_mask)
        options = {} if model_options is None else model_options
        mask_function = options.get("denoise_mask_function")
        if callable(mask_function):
            options = dict(options)

            @functools.wraps(mask_function)
            def track_mask(*args, **kwargs):
                result = mask_function(*args, **kwargs)
                setattr(target, _ACTIVE_MASK_ATTR, result)
                return result

            options["denoise_mask_function"] = track_mask
        try:
            return current(
                self, x, sigma, denoise_mask,
                model_options=options, seed=seed)
        finally:
            if previous is missing:
                try:
                    delattr(target, _ACTIVE_MASK_ATTR)
                except AttributeError:
                    pass
            else:
                setattr(target, _ACTIVE_MASK_ATTR, previous)

    _mark(wrapper, _SAMPLER_MARKER)
    sampler_cls.__call__ = wrapper
    return wrapper


def ensure_h3_mask_compat():
    """Install only current #15375 capabilities missing from the live build."""
    import comfy.model_base as model_base
    import comfy.ldm.minimax.model as h3m

    cls = getattr(model_base, "MiniMaxH3", None)
    if cls is None:
        raise RuntimeError("h3_masked_prefix: MiniMaxH3 model class not found.")

    before = capability_status()
    indicators = before["mask_engine_indicators"]
    characteristic = [
        indicators["mask_row_values"],
        indicators["mod_row"],
        indicators["forward_masks"],
        indicators["inner_masks"],
    ]
    partial_native = any(characteristic) and not all(characteristic)
    if partial_native and not before["mask_engine_compat"]:
        raise RuntimeError(
            "h3_masked_prefix: partial native H3 AV-mask engine detected. "
            "Refusing to combine this compatibility snapshot with a partially "
            "updated ComfyUI. Update this node pack or ComfyUI."
        )

    if not before["mask_engine_complete"]:
        _install_engine_compat(h3m)
        _LOG.info(
            "h3_masked_prefix: PR #15375 diffusion-mask compatibility enabled")

    # The current PR passes denoise_mask directly into scale_latent_inpaint.
    # Older cores need a narrow sampler wrapper which exposes the same value
    # through a temporary model attribute. This avoids copying ComfyUI's whole
    # sampler implementation and preserves custom denoise_mask_function hooks.
    sampler_ready = bool(
        before["sampler_mask_blend_native"]
        or before["sampler_mask_blend_compat"])
    if not sampler_ready:
        _install_sampler_mask_bridge(model_base)
        _LOG.info(
            "h3_masked_prefix: PR #15375 sampler mask-blend compatibility "
            "enabled")

    status = capability_status()
    need_scale = not (
        status["scale_latent_inpaint_native"]
        or status["scale_latent_inpaint_compat"])
    legacy_scale = _is_legacy_compat(
        getattr(cls, "scale_latent_inpaint", None))
    needs_attribute_bridge = not before["sampler_mask_blend_native"]
    # A v2 compatibility scale has the old preprocessing contract even though
    # it is callable, so replace it deliberately.
    if need_scale or legacy_scale or (
            needs_attribute_bridge
            and not status["scale_latent_inpaint_compat"]):
        process_fn, pool_fn, scale_fn = _install_model_base_hooks(model_base)
        cls._pool_masks_to_token_grid = pool_fn
        cls.scale_latent_inpaint = scale_fn
        _LOG.info(
            "h3_masked_prefix: PR #15375 token-aligned inpaint scaling "
            "enabled")
        # Intermediate PR builds still invoke this method. It must be an
        # identity under the new design so final pixel blending retains the
        # original user mask.
        if not capability_status()["sampler_mask_blend_native"]:
            cls.process_denoise_mask = process_fn
            _LOG.info(
                "h3_masked_prefix: legacy mask preprocessing neutralized")

    after = capability_status()
    ready = (
        after["mask_engine_complete"]
        and (
            after["scale_latent_inpaint_native"]
            or after["scale_latent_inpaint_compat"]
        )
        and (
            after["sampler_mask_blend_native"]
            or after["sampler_mask_blend_compat"]
        )
    )
    if not ready:
        raise RuntimeError(
            "h3_masked_prefix: H3 AV-mask compatibility is incomplete after "
            "patching."
        )
    return True


def is_ready():
    try:
        status = capability_status()
    except Exception:
        return False
    return bool(
        status["mask_engine_complete"]
        and (
            status["scale_latent_inpaint_native"]
            or status["scale_latent_inpaint_compat"]
        )
        and (
            status["sampler_mask_blend_native"]
            or status["sampler_mask_blend_compat"]
        )
    )
