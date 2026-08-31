import {app} from "/scripts/app.js";

// The MASTER companion intentionally does not install the legacy pack's
// canvas-wide widget-width compatibility hooks. Ethan's installed nodepack
// remains the owner of that legacy compatibility surface; duplicating those
// global LiteGraph hooks from the companion would violate runtime isolation.
//
// Keep a tiny, namespaced no-op extension so the companion web bundle remains
// structurally complete without touching legacy nodes or global widget state.
app.registerExtension({
    name: "minimax_h3_context_loop.LegacyWidgetWidthFixDisabled",
});
