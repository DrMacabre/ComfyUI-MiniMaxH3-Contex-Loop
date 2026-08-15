import assert from "node:assert/strict";
import fs from "node:fs";
import {
    SCHEDULED_REF2VA_TYPE,
    VIDEO_REF_TYPE,
    migrateLegacyVideoScheduleWidgets,
    migrateReferenceComplianceWidget,
} from "../web/h3_reference_autoconnect_core.mjs";

class FakeNode {
    constructor(type, widgets = []) {
        this.comfyClass = type;
        this.widgets = widgets.map(([name, value]) => ({name, value}));
    }
}

function scheduledVideo() {
    return new FakeNode(VIDEO_REF_TYPE, [
        ["tag", "performance"],
        ["scenes", ""],
        ["audio_tag", ""],
        ["timeline_mode", "restart_each_scene"],
    ]);
}

const migratedVideo = scheduledVideo();
assert.equal(migrateLegacyVideoScheduleWidgets(migratedVideo, {
    widgets_values: [
        "performance", "4:6", "old declaration", "performance_audio",
        "old audio declaration",
    ],
}), true);
assert.equal(migratedVideo.widgets.find(
    (item) => item.name === "audio_tag").value, "performance_audio");
assert.equal(migratedVideo.widgets.find(
    (item) => item.name === "timeline_mode").value, "restart_each_scene");

const modernVideo = scheduledVideo();
assert.equal(migrateLegacyVideoScheduleWidgets(modernVideo, {
    widgets_values: [
        "performance", "4:6", "performance_audio", "sequential",
    ],
}), false);
assert.equal(modernVideo.widgets.find(
    (item) => item.name === "audio_tag").value, "");

const migratedCompliance = new FakeNode(SCHEDULED_REF2VA_TYPE, [
    ["prompt_compliance", false],
]);
assert.equal(migrateReferenceComplianceWidget(migratedCompliance), true);
assert.equal(migratedCompliance.widgets.find(
    (item) => item.name === "prompt_compliance").value, "soft");
assert.equal(migrateReferenceComplianceWidget(migratedCompliance), false);

const extensionSource = fs.readFileSync(
    new URL("../web/h3_reference_autoconnect.js", import.meta.url), "utf8");
assert.doesNotMatch(extensionSource, /Convert to MiniMax H3 Scheduled Ref2VA/);
assert.doesNotMatch(extensionSource, /convertCoreRef2VA|getExtraMenuOptions/);
assert.match(extensionSource, /beforeRegisterNodeDef/);
assert.match(extensionSource, /migrateLegacyVideoScheduleWidgets/);
assert.match(extensionSource, /migrateReferenceComplianceWidget/);

console.log("H3 reference migrations: legacy schedule and compliance widgets pass");
