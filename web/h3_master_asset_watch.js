import {app} from "/scripts/app.js";
import {
    collectAssetBindings,
    collectDetachedAssetNodes,
    nodeType,
} from "./h3_run_assets_core.mjs?v=master-smoke-02";

const RUN_MANAGER = "MiniMaxH3ChainRunManager";

function widgetByName(node, name) {
    return node?.widgets?.find((item) => item.name === name) ?? null;
}

function isMasterManager(node) {
    return nodeType(node) === RUN_MANAGER
        && Array.isArray(node?.properties?.h3_detached_asset_templates);
}

function writeActiveBindings(manager) {
    if (!isMasterManager(manager)) return;
    const widget = widgetByName(manager, "asset_bindings_json");
    if (!widget) return;
    const value = JSON.stringify(collectAssetBindings(manager));
    if (widget.value === value) return;
    widget.value = value;
    widget.callback?.(value);
    manager.graph?.setDirtyCanvas?.(true, true);
}

function sourceChangedFactory(manager) {
    manager._h3MasterAssetSourceChanged ??= () => {
        const defer = window.queueMicrotask
            ?? ((callback) => window.setTimeout(callback, 0));
        defer(() => {
            writeActiveBindings(manager);
            manager._h3RunManagerRefresh?.();
            attach(manager);
        });
    };
    return manager._h3MasterAssetSourceChanged;
}

function attach(manager) {
    if (!isMasterManager(manager)) return;
    const callback = sourceChangedFactory(manager);
    const next = new Set(collectDetachedAssetNodes(manager));
    manager._h3MasterAssetWatched ??= new Set();

    for (const source of next) {
        source._h3AssetWatchers ??= new Set();
        if (!source._h3AssetWatchWrapped) {
            source._h3AssetWatchWrapped = true;
            const changed = source.onWidgetChanged;
            source.onWidgetChanged = function () {
                const result = changed?.apply(this, arguments);
                for (const listener of this._h3AssetWatchers ?? []) listener();
                return result;
            };
        }
        source._h3AssetWatchers.add(callback);
    }
    for (const source of manager._h3MasterAssetWatched) {
        if (!next.has(source)) source._h3AssetWatchers?.delete(callback);
    }
    manager._h3MasterAssetWatched = next;
    writeActiveBindings(manager);
}

function schedule(manager) {
    window.setTimeout(() => attach(manager), 0);
    window.setTimeout(() => attach(manager), 150);
}

app.registerExtension({
    name: "minimax_h3_context_loop.master_asset_watch",
    async beforeRegisterNodeDef(nodeTypeClass, nodeData) {
        if (nodeData.name !== RUN_MANAGER) return;
        const configured = nodeTypeClass.prototype.onConfigure;
        nodeTypeClass.prototype.onConfigure = function () {
            const result = configured?.apply(this, arguments);
            schedule(this);
            return result;
        };
        const graphConfigured = nodeTypeClass.prototype.onGraphConfigured;
        nodeTypeClass.prototype.onGraphConfigured = function () {
            const result = graphConfigured?.apply(this, arguments);
            schedule(this);
            return result;
        };
    },
    async nodeCreated(node) {
        if (isMasterManager(node)) schedule(node);
    },
});
