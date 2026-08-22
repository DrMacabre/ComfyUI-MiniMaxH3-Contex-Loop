#!/usr/bin/env python3

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "h3_tokenizer_compat", ROOT / "tokenizer_compat.py")
compat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compat)


class FakeTokenizerBackend:
    def __init__(self):
        self.vocab = {"base": 151668}
        self.calls = []

    def add_special_tokens(self, value):
        self.calls.append(value)
        for token in value["additional_special_tokens"]:
            if token not in self.vocab:
                self.vocab[token] = max(self.vocab.values()) + 1

    def get_vocab(self):
        return dict(self.vocab)


class FakeQwenTokenizer:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.tokenizer = FakeTokenizerBackend()
        self.inv_vocab = {151668: "base"}


class FakeMiniMaxH3Tokenizer:
    pass


legacy = SimpleNamespace(
    Qwen3VLSDTokenizer=FakeQwenTokenizer,
    MiniMaxH3Tokenizer=FakeMiniMaxH3Tokenizer,
)
installed = compat.install_minimax_tokenizer_compat(legacy)
assert installed["state"] == "compat"
assert legacy.Qwen3VLSDTokenizer is not FakeQwenTokenizer
assert issubclass(legacy.Qwen3VLSDTokenizer, FakeQwenTokenizer)

tokenizer = legacy.Qwen3VLSDTokenizer("path", option=True)
assert tokenizer.args == ("path",)
assert tokenizer.kwargs == {"option": True}
assert tokenizer.tokenizer.calls == [{
    "additional_special_tokens": list(compat.MINIMAX_EXTRA_TOKENS),
}]
for token, expected_id in compat.MINIMAX_EXTRA_TOKEN_IDS.items():
    assert tokenizer.tokenizer.get_vocab()[token] == expected_id
    assert tokenizer.inv_vocab[expected_id] == token

patched_class = legacy.Qwen3VLSDTokenizer
again = compat.install_minimax_tokenizer_compat(legacy)
assert again["state"] == "compat"
assert legacy.Qwen3VLSDTokenizer is patched_class

native_qwen = type("NativeMiniMaxQwen", (), {})
native = SimpleNamespace(
    Qwen3VLSDTokenizer=FakeQwenTokenizer,
    MiniMaxH3Tokenizer=FakeMiniMaxH3Tokenizer,
    MiniMaxQwenSDTokenizer=native_qwen,
)
native_status = compat.install_minimax_tokenizer_compat(native)
assert native_status["state"] == "native"
assert native.Qwen3VLSDTokenizer is FakeQwenTokenizer

incompatible = SimpleNamespace(Qwen3VLSDTokenizer=object)
assert compat.install_minimax_tokenizer_compat(incompatible)["state"] == "unavailable"

print("MiniMax H3 tokenizer: native detection and guarded PR #15808 backport pass")
