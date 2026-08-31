#!/usr/bin/env python3
"""Dependency-free checks for companion-local tokenizer/model isolation helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "companion_core_compat.py"
spec = importlib.util.spec_from_file_location("companion_core_compat_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class FakeInnerTokenizer:
    def __init__(self):
        self.calls = []

    def tokenize_with_weights(self, text, return_word_ids=False, **kwargs):
        self.calls.append((text, return_word_ids))
        # Stable fake word ids let the proxy prove it offsets separate spans.
        values = [(100 + index, 1.0, index + 1)
                  for index, _char in enumerate(text)]
        if return_word_ids:
            return [values]
        return [[(token, weight) for token, weight, _word in values]]


inner = FakeInnerTokenizer()
proxy = module._MiniMaxSpecialTokenProxy(inner)
text = "ab<d>cd<|caption_start|>e"
result = proxy.tokenize_with_weights(text, return_word_ids=True)
assert len(result) == 1
values = result[0]
ids = [item[0] for item in values]
assert 151669 in ids
assert 151674 in ids
assert ids.count(151669) == 1
assert ids.count(151674) == 1
# Structural special tokens are explicitly non-word entries.
for token_id in (151669, 151674):
    item = next(item for item in values if item[0] == token_id)
    assert item[1:] == (1.0, 0)
# Normal spans still delegate to the existing tokenizer implementation.
assert [call[0] for call in inner.calls] == ["ab", "cd", "e"]
# Word ids from later spans must not collide with earlier spans.
word_ids = [word for token, _weight, word in values
            if token not in (151669, 151674) and word]
assert word_ids == sorted(word_ids)
assert len(word_ids) == len(set(word_ids))

# A prompt without the MiniMax additions must remain byte-for-byte delegated.
plain_inner = FakeInnerTokenizer()
plain_proxy = module._MiniMaxSpecialTokenProxy(plain_inner)
plain = plain_proxy.tokenize_with_weights("plain", return_word_ids=False)
direct = FakeInnerTokenizer().tokenize_with_weights(
    "plain", return_word_ids=False)
assert plain == direct

# The implementation must use Python-compatible class swapping rather than
# permanent monkeypatches. This small stand-in proves subclass -> original
# __class__ restoration leaves no instance method shadow.
class Base:
    def value(self):
        return "base"


class Scoped(Base):
    def value(self):
        return "scoped"


instance = Base()
assert "value" not in instance.__dict__
instance.__class__ = Scoped
assert instance.value() == "scoped"
instance.__class__ = Base
assert instance.value() == "base"
assert "value" not in instance.__dict__

print("MASTER COMPANION SCOPED CORE COMPAT CHECKS: OK")
