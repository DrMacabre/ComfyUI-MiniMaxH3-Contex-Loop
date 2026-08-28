from pathlib import Path

path = Path("tests/_chain_review_js_test.mjs")
text = path.read_text(encoding="utf-8")

old_body = r'''assert.match(
    reviewSource,
    /updatePlan\(\s*node, submittedIndex, acceptedPrompt, body\.seed, body\.length\)/,
);'''
new_body = r'''assert.doesNotMatch(
    reviewSource,
    /updatePlan\(\s*node, submittedIndex, acceptedPrompt, body\.seed, body\.length\)/,
);'''
old_open = r'''assert.match(reviewSource, /reviewDurationText\(data\.raw_frames\)/);'''
new_open = r'''assert.doesNotMatch(reviewSource, /reviewDurationText\(data\.raw_frames\)/);
assert.match(reviewSource, /durationField\.append\("Final frames"\)/);
assert.match(reviewSource, /exactResponseLength/);'''

if old_body not in text and new_body not in text:
    raise SystemExit("stale Review body.length assertion not found in expected old/new form")
if old_open not in text and new_open not in text:
    raise SystemExit("stale Review raw_frames assertion not found in expected old/new form")

text = text.replace(old_body, new_body, 1)
text = text.replace(old_open, new_open, 1)
path.write_text(text, encoding="utf-8")
print("PATCH_CHAIN_REVIEW_TEST_EXACT_FRAMES_0637_PASS")
