"""Backport MiniMax H3's released additional special tokens.

ComfyUI PR #15808 teaches the MiniMax-specific Qwen tokenizer about seven
tokens declared only by the released ``tokenizer_config.json``.  Older core
builds instantiate the generic Qwen tokenizer directly and therefore split
those markers into ordinary sub-tokens.

The compatibility hook below replaces only the module-local tokenizer alias
used by ``comfy.text_encoders.minimax.MiniMaxH3Tokenizer``.  It leaves the
shared Qwen tokenizer class untouched, chains any existing module-local
subclass, and stands down when core already exposes the native implementation.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any


_LOG = logging.getLogger(__name__)

MINIMAX_EXTRA_TOKENS = (
    "<d>",
    "</d>",
    "<|cutoff|>",
    "<|lyrics_start|>",
    "<|lyrics_end|>",
    "<|caption_start|>",
    "<|caption_end|>",
)
MINIMAX_EXTRA_TOKEN_IDS = dict(zip(
    MINIMAX_EXTRA_TOKENS,
    range(151669, 151676),
))

_PATCH_MARKER = "_h3_minimax_extra_tokens_compat"


def _status(state: str, message: str) -> dict[str, str]:
    return {"state": state, "message": message}


def install_minimax_tokenizer_compat(
        minimax_module: Any | None = None) -> dict[str, str]:
    """Install PR #15808 behavior on pre-PR MiniMax tokenizer modules.

    The optional module argument keeps capability detection independently
    testable without importing ComfyUI.  Startup callers normally omit it.
    """

    if minimax_module is None:
        try:
            minimax_module = importlib.import_module(
                "comfy.text_encoders.minimax")
        except Exception as exc:  # ComfyUI may not include H3 yet.
            return _status("unavailable", "MiniMax tokenizer unavailable: %s" % exc)

    native = getattr(minimax_module, "MiniMaxQwenSDTokenizer", None)
    if native is not None:
        return _status(
            "native",
            "ComfyUI owns MiniMax H3 additional special tokens",
        )

    base = getattr(minimax_module, "Qwen3VLSDTokenizer", None)
    h3_tokenizer = getattr(minimax_module, "MiniMaxH3Tokenizer", None)
    if not isinstance(base, type) or h3_tokenizer is None:
        return _status(
            "unavailable",
            "MiniMax tokenizer API is not compatible with the guarded backport",
        )
    if getattr(base, _PATCH_MARKER, False):
        return _status(
            "compat",
            "MiniMax H3 additional special-token backport is already active",
        )

    class MiniMaxQwenSDTokenizerCompat(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            tokenizer = getattr(self, "tokenizer", None)
            add_special_tokens = getattr(tokenizer, "add_special_tokens", None)
            get_vocab = getattr(tokenizer, "get_vocab", None)
            if not callable(add_special_tokens) or not callable(get_vocab):
                raise RuntimeError(
                    "MiniMax H3 tokenizer compatibility requires a tokenizer "
                    "with add_special_tokens() and get_vocab().")

            add_special_tokens({
                "additional_special_tokens": list(MINIMAX_EXTRA_TOKENS),
            })
            vocab = get_vocab()
            self.inv_vocab = {token_id: token for token, token_id in vocab.items()}

            mismatched = {
                token: (vocab.get(token), expected)
                for token, expected in MINIMAX_EXTRA_TOKEN_IDS.items()
                if vocab.get(token) != expected
            }
            if mismatched:
                _LOG.warning(
                    "MiniMax H3 additional special-token ids differ from the "
                    "released tokenizer: %s", mismatched)

    MiniMaxQwenSDTokenizerCompat.__name__ = "MiniMaxQwenSDTokenizer"
    MiniMaxQwenSDTokenizerCompat.__qualname__ = "MiniMaxQwenSDTokenizer"
    setattr(MiniMaxQwenSDTokenizerCompat, _PATCH_MARKER, True)
    setattr(
        MiniMaxQwenSDTokenizerCompat,
        "_h3_minimax_extra_tokens",
        MINIMAX_EXTRA_TOKENS,
    )

    # MiniMaxH3Tokenizer's factory resolves this module global at runtime.
    # Replacing the alias avoids modifying the shared Qwen tokenizer class.
    minimax_module.Qwen3VLSDTokenizer = MiniMaxQwenSDTokenizerCompat
    if not hasattr(minimax_module, "MINIMAX_EXTRA_TOKENS"):
        minimax_module.MINIMAX_EXTRA_TOKENS = list(MINIMAX_EXTRA_TOKENS)
    _LOG.info(
        "MiniMax H3 tokenizer: enabled PR #15808 special-token compatibility")
    return _status(
        "compat",
        "Installed MiniMax H3 additional special-token backport",
    )
