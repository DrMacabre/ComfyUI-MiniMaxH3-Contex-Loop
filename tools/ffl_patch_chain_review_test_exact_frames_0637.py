from pathlib import Path

path = Path("tests/_chain_review_js_test.mjs")
text = path.read_text(encoding="utf-8")

# The old test suite deliberately asserted the pre-Exact-Timeline Review UI.
# Change only those assertions that encode the obsolete duration authority.
old_duration = r'''assert.match(reviewSource, /Duration \(s\)/);'''
new_duration = r'''assert.match(reviewSource, /Final frames/);'''
if old_duration in text:
    text = text.replace(old_duration, new_duration, 1)
elif new_duration not in text:
    raise SystemExit("Review duration-label assertion not found in expected old/new form")

old_generic_length = r'''assert.match(reviewSource, /body\.length/);'''
new_generic_length = r'''assert.match(reviewSource, /length: normalizedLength/);'''
if old_generic_length in text:
    text = text.replace(old_generic_length, new_generic_length, 1)
elif new_generic_length not in text:
    raise SystemExit("Review generic body.length assertion not found in expected old/new form")

# The retry Plan write must no longer trust the ambiguous response body.length.
body_needle = r"acceptedPrompt, body\.seed, body\.length"
body_pos = text.find(body_needle)
if body_pos < 0:
    raise SystemExit("Review body.length regression assertion needle not found")
body_start_match = text.rfind("assert.match(", 0, body_pos)
body_start_no = text.rfind("assert.doesNotMatch(", 0, body_pos)
if body_start_no > body_start_match:
    pass
elif body_start_match >= 0:
    text = text[:body_start_match] + "assert.doesNotMatch(" + text[body_start_match + len("assert.match("):]
else:
    raise SystemExit("Review body.length assertion wrapper not found")

# The Review editor must not initialize its authored exact duration from raw H3.
raw_needle = r"reviewDurationText\(data\.raw_frames\)"
raw_pos = text.find(raw_needle)
if raw_pos < 0:
    raise SystemExit("Review raw_frames opening assertion needle not found")
raw_line_start = text.rfind("\n", 0, raw_pos) + 1
raw_line_end = text.find("\n", raw_pos)
if raw_line_end < 0:
    raw_line_end = len(text)
raw_line = text[raw_line_start:raw_line_end]
if "assert.match(" in raw_line:
    raw_line = raw_line.replace("assert.match(", "assert.doesNotMatch(", 1)
    text = text[:raw_line_start] + raw_line + text[raw_line_end:]
elif "assert.doesNotMatch(" not in raw_line:
    raise SystemExit("Review raw_frames assertion wrapper not found")

extra = '''assert.match(reviewSource, /durationField\\.append\\(\"Final frames\"\\)/);\nassert.match(reviewSource, /exactResponseLength/);'''
if extra not in text:
    raw_pos = text.find(raw_needle)
    raw_line_end = text.find("\n", raw_pos)
    if raw_line_end < 0:
        raw_line_end = len(text)
    text = text[:raw_line_end] + "\n" + extra + text[raw_line_end:]

path.write_text(text, encoding="utf-8")
print("PATCH_CHAIN_REVIEW_TEST_EXACT_FRAMES_0637_PASS")
