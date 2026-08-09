import assert from "node:assert/strict";
import {
    fallbackDisplayIds,
    isRecursiveExecutionId,
    recursiveRootId,
} from "../web/h3_kj_preview_bridge_core.mjs";

assert.equal(isRecursiveExecutionId("1705"), false);
assert.equal(isRecursiveExecutionId("1705.0.0.27"), true);
assert.equal(recursiveRootId("1705.0.0.27"), "1705");
assert.deepEqual(fallbackDisplayIds("1705.0.0.27"), ["27"]);
assert.deepEqual(
    fallbackDisplayIds("1705.0.0.Recurse.0.0.27"),
    ["27"],
);
assert.deepEqual(
    fallbackDisplayIds("1705.0.0.Recurse.0.0.12:27"),
    ["12:27"],
);

console.log("H3/KJ preview bridge helpers: ok");
