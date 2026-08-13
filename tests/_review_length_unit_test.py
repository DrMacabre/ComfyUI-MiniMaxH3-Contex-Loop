#!/usr/bin/env python3
"""Review retry duration updates the complete prepared Plan timeline."""

import asyncio
import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_review_length_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

server = types.ModuleType("server")
server.PromptServer = type("PromptServer", (), {"instance": None})
sys.modules["server"] = server

package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

shared_nodes = types.ModuleType(PACKAGE + ".nodes")
shared_nodes.MiniMaxH3MotionContext = object
shared_nodes._claim_inline_patch_ownership = lambda: "test patch owner"
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def shot(index, raw_frames, delivered_frames, start):
    prompt = "Scene %d." % index
    return {
        "index": index,
        "id": "scene_%d" % index,
        "scene_prompt": prompt,
        "prompt": prompt,
        "prompt_hash": "prompt-%d" % index,
        "seed": index,
        "steps": 20,
        "raw_frames": raw_frames,
        "delivered_frames": delivered_frames,
        "generation_start_frame": start,
        "audio_start_seconds": start / 24,
        "audio_duration_seconds": raw_frames / 24,
    }


plan = {
    "version": 1,
    "run_name": "review_length",
    "prompt_prefix": "",
    "shots": [shot(1, 39, 39, 0), shot(2, 56, 34, 17),
              shot(3, 39, 17, 51)],
    "compatibility": {
        "fps": 24,
        "width": 960,
        "height": 544,
        "context_length": 22,
        "anchor_mode": "head",
        "audio_mode": "generated_audio",
        "source_audio_hash": "none",
    },
    "total_delivered_frames": 90,
    "plan_hash": "prepared-hash",
    "base_plan_hash": "base-hash",
}

revised = chain._plan_with_review_revision(
    plan, 2, "Longer second scene.", 999, 73)

assert revised["shots"][0]["raw_frames"] == 39
assert revised["shots"][1]["raw_frames"] == 73
assert revised["shots"][1]["delivered_frames"] == 51
assert revised["shots"][1]["generation_start_frame"] == 17
assert revised["shots"][2]["generation_start_frame"] == 68
assert revised["shots"][2]["audio_start_seconds"] == 68 / 24
assert revised["total_delivered_frames"] == 107
assert revised["review_overrides"]["2"]["raw_frames"] == 73
assert revised["base_plan_hash"] == plan["base_plan_hash"]
assert chain._history_hash(revised, 1) == chain._history_hash(plan, 1)
assert chain._history_hash(revised, 2) != chain._history_hash(plan, 2)

external = {
    **plan,
    "shots": [shot(1, 56, 34, -22), shot(2, 39, 17, 12)],
    "compatibility": {
        **plan["compatibility"],
        "external_context_frames": 22,
        "external_context_hash": "external-hash",
    },
    "total_delivered_frames": 51,
}
external["shots"][0]["external_context_frames"] = 22
external_revision = chain._plan_with_review_revision(
    external, 1, "Longer imported-video continuation.", 777, 73)
assert external_revision["shots"][0]["generation_start_frame"] == -22
assert external_revision["shots"][0]["delivered_frames"] == 51
assert external_revision["shots"][1]["generation_start_frame"] == 29
assert external_revision["total_delivered_frames"] == 68

try:
    chain._plan_with_review_revision(plan, 2, "Too short.", 999, 22)
except ValueError as exc:
    assert "17k+5" in str(exc) or "continuation overlap" in str(exc)
else:
    raise AssertionError("Review retry accepted an invalid H3 length")


class RetryRequest:
    def __init__(self, token, length):
        self.token = token
        self.length = length

    async def json(self):
        return {
            "token": self.token,
            "action": "retry",
            "scene_prompt": "Route retry.",
            "seed": "123",
            "length": self.length,
        }


async def check_route_validation():
    token = "review-length-test"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    chain._PENDING_REVIEWS[token] = {
        "future": future,
        "loop": loop,
        "plan": plan,
        "public": {"clip_index": 2, "prompt_prefix": ""},
        "current_seed": 2,
        "current_length": 56,
    }
    try:
        rejected = await chain._submit_review_decision(
            RetryRequest(token, 39))
        assert rejected.status == 400
        assert "next clip requires" in json.loads(rejected.text)["error"]
        assert not future.done()

        accepted = await chain._submit_review_decision(
            RetryRequest(token, 73))
        assert accepted.status == 200
        assert json.loads(accepted.text)["length"] == 73
        await asyncio.sleep(0)
        assert future.result()["raw_frames"] == 73
    finally:
        chain._PENDING_REVIEWS.pop(token, None)


asyncio.run(check_route_validation())


class FakePromptServerInstance:
    def __init__(self):
        self.client_id = "current-client"
        self.sent = []

    def send_sync(self, event, payload, client_id=None):
        self.sent.append((event, payload, client_id))


fake_prompt_server = FakePromptServerInstance()
chain.PromptServer.instance = fake_prompt_server
final_manifest = {
    "format": "h3_chain_manifest_v3",
    "run_name": "review_length",
    "plan_hash": "prepared-hash",
}
final_key = chain._final_review_preview_key(final_manifest)
chain._PENDING_FINAL_REVIEW_PREVIEWS[final_key] = {
    "token": "final-token",
    "node_id": "review-node",
    "client_id": "originating-client",
}
chain._publish_final_review_preview(
    final_manifest, str(ROOT / "final.mp4"), "assembled final")
assert final_key not in chain._PENDING_FINAL_REVIEW_PREVIEWS
assert fake_prompt_server.sent == [(
    "minimax_h3_context_loop_review_resolved",
    {
        "token": "final-token",
        "node_id": "review-node",
        "action": "final",
        "status": "assembled final",
        "final_video": {
            "filename": "final.mp4",
            "subfolder": "",
            "type": "output",
        },
    },
    "originating-client",
)]

print("H3 Review length and final preview handoff: pass")
