import {app} from "/scripts/app.js";

const STYLE_ID = "h3-master-simple-ui-style";

function injectMasterSimpleUiStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
        /* Normal master-facing Plan Studio hides plumbing audio overrides.
           Opening Advanced boundary controls reveals them again. */
        .h3studio-audio-overrides {
            display: none !important;
        }
        .h3studio-panel:has(> .h3studio-advanced[open]) > .h3studio-audio-overrides {
            display: grid !important;
        }

        /* The Scene Plan editor already has an Advanced toggle. Keep the
           three low-level audio-policy overrides behind that toggle. */
        .h3c-audio-fields {
            display: none !important;
        }
        .h3c-editor.h3c-show-advanced .h3c-audio-fields {
            display: grid !important;
        }
    `;
    document.head.appendChild(style);
}

app.registerExtension({
    name: "minimax_h3_context_loop.master_simple_ui_surface",
    setup() {
        injectMasterSimpleUiStyles();
    },
});
