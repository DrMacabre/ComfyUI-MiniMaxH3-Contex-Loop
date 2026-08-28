#!/usr/bin/env python3
"""Allow Tagged Audio source_timeline mode to validate the materialized AUDIO identity.

0.6.37 stores two legitimate audio identities on a typed Source Timeline:
- fingerprints.audio: descriptor/timeline identity;
- audio.content_sha256: decoded AUDIO content identity when the timeline came
  from a connected AUDIO tensor and was materialized path-backed.

Tagged Audio Reference is fed the full Load Audio tensor and therefore carries
_audio_fingerprint(AUDIO) as entry.content_hash.  Accept that exact content
identity when present, while retaining the existing descriptor-hash fallback.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "chain_nodes.py"
source = TARGET.read_text(encoding="utf-8")

old = '''    expected_hash = str(compatibility.get("source_audio_hash") or "")
    entry_hash = str(entry.get("content_hash") or "")
    if not expected_hash or expected_hash == "none":
        raise ValueError(
            "Tagged audio @%s source_timeline has no Loop Start source-audio "
            "fingerprint to validate." % entry.get("tag", "audio"))
    if not entry_hash or entry_hash != expected_hash:
        raise ValueError(
            "Tagged audio @%s source_timeline received a different full "
            "source track than H3 Chain Loop Start. Wire the same Load Audio "
            "output to both nodes." % entry.get("tag", "audio"))
'''

new = '''    expected_hash = str(compatibility.get("source_audio_hash") or "")
    entry_hash = str(entry.get("content_hash") or "")
    timeline_content_hash = ""
    source_timeline = state.get("source_timeline")
    if source_timeline is not None:
        source_timeline = _validate_source_timeline(
            source_timeline, require_runtime=True)
        timeline_content_hash = str(
            source_timeline["audio"].get("content_sha256") or "")
    if not expected_hash or expected_hash == "none":
        raise ValueError(
            "Tagged audio @%s source_timeline has no Loop Start source-audio "
            "fingerprint to validate." % entry.get("tag", "audio"))
    accepted_hashes = {expected_hash}
    if timeline_content_hash:
        accepted_hashes.add(timeline_content_hash)
    if not entry_hash or entry_hash not in accepted_hashes:
        raise ValueError(
            "Tagged audio @%s source_timeline received a different full "
            "source track than H3 Chain Loop Start. Wire the same Load Audio "
            "output to both nodes." % entry.get("tag", "audio"))
'''

count = source.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one tagged-audio identity block, found {count}")
source = source.replace(old, new, 1)
TARGET.write_text(source, encoding="utf-8")

# Focused source contract: content identity is additive, not a weakening of
# the existing Loop Start descriptor fingerprint check.
patched = TARGET.read_text(encoding="utf-8")
assert 'accepted_hashes = {expected_hash}' in patched
assert 'source_timeline["audio"].get("content_sha256")' in patched
assert 'entry_hash not in accepted_hashes' in patched
assert 'if not expected_hash or expected_hash == "none"' in patched
print("PASS tagged audio accepts materialized Source Timeline AUDIO identity")
