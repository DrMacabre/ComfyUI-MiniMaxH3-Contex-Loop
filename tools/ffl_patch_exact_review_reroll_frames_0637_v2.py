from pathlib import Path

# The first strict patcher correctly failed closed because current 0.6.37 names
# the Review payload identity field `shot_id`, while the historical patch source
# used `scene_id`. Reuse the already-reviewed patch logic with only that exact
# source-identity correction; do not loosen any other source assertions.
path = Path(__file__).with_name("ffl_patch_exact_review_reroll_frames_0637.py")
source = path.read_text(encoding="utf-8")
old = "review?.scene_id,"
new = "review?.shot_id,"
count = source.count(old)
if count != 2:
    raise SystemExit(f"v2 shot_id correction: expected 2 patch-source occurrences, got {count}")
source = source.replace(old, new)
exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})
