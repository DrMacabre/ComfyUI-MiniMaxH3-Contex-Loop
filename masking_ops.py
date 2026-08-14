"""Pure tensor/media helpers for general MiniMax H3 masked targets.

The 32-pixel grid mirrors H3's 16x video VAE scale followed by the DiT's 2x2
latent patching.  A mask value of one means generate and zero means preserve.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F


H3_FRAME_OFFSET = 5
H3_FRAME_STRIDE = 17
H3_VIDEO_FPS = 24
H3_VAE_SCALE = 16
H3_PIXEL_CELL = 32
GRID_MODES = (
    "runtime exact (latent max)",
    "any pixel coverage",
    "50% pixel coverage",
    "full pixel coverage",
)


def floor_h3_frame_count(frame_count: int) -> int:
    """Return the largest valid 17k+5 frame count not above ``frame_count``."""
    count = int(frame_count)
    if count < H3_FRAME_OFFSET:
        raise ValueError(
            "MiniMax H3 needs at least %d video frames; received %d." %
            (H3_FRAME_OFFSET, count)
        )
    return H3_FRAME_OFFSET + (
        (count - H3_FRAME_OFFSET) // H3_FRAME_STRIDE
    ) * H3_FRAME_STRIDE


def trim_audio_to_frames(
    audio: Any,
    frame_count: int,
    fps: int = H3_VIDEO_FPS,
):
    """Trim ComfyUI AUDIO to the exact video duration without padding."""
    if audio is None:
        return None, None
    if not isinstance(audio, dict):
        raise ValueError(
            "H3 source AV trim needs a ComfyUI AUDIO value when connected."
        )
    waveform = audio.get("waveform")
    sample_rate = audio.get("sample_rate")
    if waveform is None or not hasattr(waveform, "shape") or waveform.ndim < 2:
        raise ValueError("Connected AUDIO has no valid waveform tensor.")
    try:
        resolved_rate = int(sample_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("Connected AUDIO has no valid sample_rate.") from exc
    if resolved_rate < 1:
        raise ValueError("Connected AUDIO sample_rate must be positive.")

    target_samples = round(int(frame_count) * resolved_rate / int(fps))
    trimmed_samples = min(int(waveform.shape[-1]), target_samples)
    output = audio.copy()
    output["waveform"] = waveform[..., :trimmed_samples]
    return output, target_samples


def normalize_comfy_mask(mask: torch.Tensor) -> torch.Tensor:
    """Normalize common Comfy MASK spellings to float ``[frames,H,W]``."""
    if not isinstance(mask, torch.Tensor):
        raise ValueError("H3 masking expects a ComfyUI MASK tensor.")
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    elif mask.ndim == 4 and int(mask.shape[1]) == 1:
        mask = mask[:, 0]
    elif mask.ndim == 4 and int(mask.shape[-1]) == 1:
        mask = mask[..., 0]
    if mask.ndim != 3:
        raise ValueError(
            "Expected a ComfyUI MASK [frames,H,W], got %s." %
            (list(mask.shape),)
        )
    if not int(mask.shape[0]) or not int(mask.shape[1]) or not int(mask.shape[2]):
        raise ValueError("H3 masking received an empty mask tensor.")
    return mask.to(torch.float32).clamp(0.0, 1.0)


def resize_mask_to_canvas(
    mask: torch.Tensor,
    frames: int,
    height: int,
    width: int,
) -> torch.Tensor:
    """Resize a Comfy mask to ``[frames,1,height,width]``."""
    if frames < 1 or height < 1 or width < 1:
        raise ValueError("Mask canvas dimensions must be positive.")
    work = normalize_comfy_mask(mask)[None, None]
    work = F.interpolate(
        work,
        size=(int(frames), int(height), int(width)),
        mode="trilinear",
        align_corners=False,
    )
    return work[0].movedim(0, 1).contiguous()


def resize_mask_to_video_latent(
    mask: torch.Tensor,
    video: torch.Tensor,
) -> torch.Tensor:
    """Convert a generate mask to the target H3 video latent dimensions."""
    if video.ndim != 5:
        raise ValueError(
            "H3 target video latent must be [B,C,T,H,W], got %s." %
            (list(video.shape),)
        )
    if int(video.shape[0]) != 1:
        raise ValueError("H3 masked targets currently support batch size 1.")
    work = normalize_comfy_mask(mask).to(device=video.device)[None, None]
    work = F.interpolate(
        work,
        size=(int(video.shape[2]), int(video.shape[3]), int(video.shape[4])),
        mode="trilinear",
        align_corners=False,
    )
    return work.to(torch.float32).contiguous()


def temporal_audio_mask(
    mask: torch.Tensor,
    audio: torch.Tensor,
) -> torch.Tensor:
    """Reduce a video/custom mask to an H3 audio-latent timeline."""
    if audio.ndim != 4:
        raise ValueError(
            "H3 target audio latent must be [B,C,channels,T], got %s." %
            (list(audio.shape),)
        )
    if int(audio.shape[0]) != 1:
        raise ValueError("H3 masked targets currently support batch size 1.")
    source = normalize_comfy_mask(mask).to(device=audio.device)
    timeline = source.amax(dim=(-2, -1))[None, None]
    timeline = F.interpolate(
        timeline,
        size=int(audio.shape[-1]),
        mode="linear",
        align_corners=False,
    )
    return timeline[:, :, None].expand(
        int(audio.shape[0]), 1, int(audio.shape[2]), int(audio.shape[3])
    ).to(torch.float32).contiguous()


def _grow_or_shrink_cells(cells: torch.Tensor, amount: int) -> torch.Tensor:
    if amount == 0:
        return cells
    radius = abs(int(amount))
    kernel = radius * 2 + 1
    if amount > 0:
        return F.max_pool2d(
            cells, kernel_size=kernel, stride=1, padding=radius)
    inverse = 1.0 - cells
    inverse = F.pad(
        inverse,
        (radius, radius, radius, radius),
        mode="constant",
        value=1.0,
    )
    return 1.0 - F.max_pool2d(inverse, kernel_size=kernel, stride=1)


def quantize_h3_pixel_mask(
    mask: torch.Tensor,
    frames: int,
    height: int,
    width: int,
    mode: str = GRID_MODES[0],
    cell_adjust: int = 0,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Return resized raw mask, snapped pixel mask, and 32px cell map."""
    if mode not in GRID_MODES:
        raise ValueError("Unknown H3 mask grid mode: %s" % mode)
    if height % H3_PIXEL_CELL or width % H3_PIXEL_CELL:
        raise ValueError(
            "Accurate H3 grid preview requires width and height divisible by "
            "%d; received %dx%d." % (H3_PIXEL_CELL, width, height)
        )

    raw = resize_mask_to_canvas(mask, frames, height, width)
    grid_h = height // H3_PIXEL_CELL
    grid_w = width // H3_PIXEL_CELL

    if mode == "runtime exact (latent max)":
        latent = F.interpolate(
            raw,
            size=(height // H3_VAE_SCALE, width // H3_VAE_SCALE),
            mode="bilinear",
            align_corners=False,
        )
        cells = latent.reshape(
            frames,
            1,
            grid_h,
            H3_PIXEL_CELL // H3_VAE_SCALE,
            grid_w,
            H3_PIXEL_CELL // H3_VAE_SCALE,
        ).amax(dim=(-3, -1))
        cells = (cells >= 0.5).to(raw.dtype)
    else:
        pixels = raw.reshape(
            frames, 1, grid_h, H3_PIXEL_CELL, grid_w, H3_PIXEL_CELL)
        if mode == "any pixel coverage":
            cells = (pixels.amax(dim=(-3, -1)) >= 0.5).to(raw.dtype)
        elif mode == "50% pixel coverage":
            cells = (pixels.mean(dim=(-3, -1)) >= 0.5).to(raw.dtype)
        else:
            cells = (pixels.amin(dim=(-3, -1)) >= 0.5).to(raw.dtype)

    cells = _grow_or_shrink_cells(cells, int(cell_adjust))
    snapped = cells.repeat_interleave(
        H3_PIXEL_CELL, dim=-2).repeat_interleave(H3_PIXEL_CELL, dim=-1)
    return raw, snapped[:, 0].contiguous(), cells
