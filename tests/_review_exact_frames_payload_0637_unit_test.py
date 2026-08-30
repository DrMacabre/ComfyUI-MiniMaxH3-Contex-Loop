from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "review_exact_frames_payload_0637.py"
spec = importlib.util.spec_from_file_location("review_exact_frames_payload_0637", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

chain = SimpleNamespace(_PENDING_REVIEWS={})
assert module.activate_review_exact_frames_payload(chain) == module.BUILD

payload = {"raw_frames": 124}
entry = {
    "public": payload,
    "current_length": 124,
    "current_requested_frames": 120,
}
chain._PENDING_REVIEWS["token"] = entry

assert payload["requested_frames"] == 120
assert payload["raw_frames"] == 124
assert entry["current_length"] == 124
assert module.activate_review_exact_frames_payload(chain) == module.BUILD

print("PASS Review payload exposes exact requested frames without changing H3 raw frames")
