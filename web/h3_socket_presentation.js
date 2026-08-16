import {app} from "/scripts/app.js";
import {
    AUDIO_POLICY_NODE,
    PLAN_NODE,
    TRANSITION_POLICY_NODE,
    applySocketPresentation,
    hasAdvancedPresentation,
    nodeType,
    presentationForNode,
} from "./h3_socket_presentation_core.mjs?v=0.5.0";

const EXTENSION = "minimax_h3_context_loop.socket_presentation";
const WATCHED_POLICY_NODES = new Set([
    AUDIO_POLICY_NODE, PLAN_NODE, TRANSITION_POLICY_NODE,
]);

function collapseWidget(widget) {
    if (!widget || widget.h3PresentationHidden) return;
    widget.h3PresentationHidden = true;
    widget.h3PresentationOriginal = {
        type: widget.type,
        hidden: widget.hidden,
        computeSize: widget.computeSize,
        draw: widget.draw,
    };
    widget.hidden = true;
    widget.type = "hidden";
    widget.computeSize = () => [0, -4];
    widget.draw = () => {};
    for (const item of new Set([widget.inputEl, widget.element])) {
        if (!item?.style) continue;
        item.style.setProperty("display", "none", "important");
        item.style.setProperty("pointer-events", "none", "important");
        item.setAttribute?.("aria-hidden", "true");
    }
}

function restoreWidget(widget) {
    if (!widget?.h3PresentationHidden) return;
    const original = widget.h3PresentationOriginal ?? {};
    widget.type = original.type;
    widget.hidden = original.hidden;
    widget.computeSize = original.computeSize;
    widget.draw = original.draw;
    widget.h3PresentationHidden = false;
    for (const item of new Set([widget.inputEl, widget.element])) {
        if (!item?.style) continue;
        item.style.removeProperty("display");
        item.style.removeProperty("pointer-events");
        item.removeAttribute?.("aria-hidden");
    }
}

function refreshNode(node) {
    if (!node) return;
    node.properties ??= {};
    const advanced = Boolean(node.properties.h3_show_advanced_sockets);
    const presentation = presentationForNode(node, advanced);
    applySocketPresentation(node, advanced);
    for (const widget of node.widgets ?? []) {
        if (presentation.hiddenWidgets.has(widget.name)) collapseWidget(widget);
        else restoreWidget(widget);
    }
    node.graph?.setDirtyCanvas?.(true, true);
}

function refreshGraph(graph) {
    for (const node of graph?._nodes ?? app.graph?._nodes ?? []) refreshNode(node);
}

function scheduleGraphRefresh(node) {
    if (node._h3PresentationRefreshPending) return;
    node._h3PresentationRefreshPending = true;
    queueMicrotask(() => {
        node._h3PresentationRefreshPending = false;
        refreshGraph(node.graph ?? app.graph);
    });
}

function watchWidgets(node) {
    for (const widget of node.widgets ?? []) {
        if (widget.h3PresentationCallbackWrapped) continue;
        widget.h3PresentationCallbackWrapped = true;
        const original = widget.callback;
        widget.callback = function () {
            const result = original?.apply(this, arguments);
            scheduleGraphRefresh(node);
            return result;
        };
    }
}

app.registerExtension({
    name: EXTENSION,
    async beforeRegisterNodeDef(nodeClass, nodeData) {
        const relevant = String(nodeData.name ?? "").startsWith("MiniMaxH3")
            || WATCHED_POLICY_NODES.has(nodeData.name);
        if (!relevant) return;

        const originalCreated = nodeClass.prototype.onNodeCreated;
        nodeClass.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            watchWidgets(this);
            refreshNode(this);
            return result;
        };

        const originalConfigure = nodeClass.prototype.onConfigure;
        nodeClass.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);
            watchWidgets(this);
            refreshNode(this);
            scheduleGraphRefresh(this);
            return result;
        };

        const originalConnectionsChange = nodeClass.prototype.onConnectionsChange;
        nodeClass.prototype.onConnectionsChange = function () {
            const result = originalConnectionsChange?.apply(this, arguments);
            scheduleGraphRefresh(this);
            return result;
        };

        const originalMenu = nodeClass.prototype.getExtraMenuOptions;
        nodeClass.prototype.getExtraMenuOptions = function (_, options) {
            const result = originalMenu?.apply(this, arguments);
            if (!hasAdvancedPresentation(this)) return result;
            const advanced = Boolean(this.properties?.h3_show_advanced_sockets);
            options.push({
                content: advanced
                    ? "Hide advanced H3 sockets"
                    : "Show advanced H3 sockets",
                callback: () => {
                    this.properties ??= {};
                    this.properties.h3_show_advanced_sockets = !advanced;
                    refreshNode(this);
                },
            });
            return result;
        };
    },
});
