#!/usr/bin/env python3
"""Type-based example catalog and paired T2VA/I2VA workflow regression."""

import collections
import hashlib
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
ARCHIVE = EXAMPLES / "Archive"
SOURCE_URL = (
    "https://discord.com/channels/1076117621407223829/"
    "1532625331960152124/1536689209761599608"
)
I2V_SOURCE_URL = (
    "https://discord.com/channels/1076117621407223829/"
    "1533677158067736777/1537180042210054226"
)
I2V_ASSET_SHA256 = (
    "7a9993055d71b1e174096f2a2533ae2a0b14a686fdacae0c7bab1faa738ef5f3"
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def node(workflow, node_type):
    matches = [item for item in workflow["nodes"]
               if item.get("type") == node_type]
    assert len(matches) == 1, (node_type, len(matches))
    return matches[0]


def socket(items, name):
    return next(item for item in items if item.get("name") == name)


def validate_links(workflow):
    nodes = {item["id"]: item for item in workflow["nodes"]}
    links = {item[0]: item for item in workflow["links"]}
    assert len(nodes) == len(workflow["nodes"])
    assert len(links) == len(workflow["links"])
    assert workflow["last_link_id"] >= max(links)
    for link_id, link in links.items():
        _, origin_id, origin_slot, target_id, target_slot, link_type = link
        assert origin_id in nodes and target_id in nodes
        origin = nodes[origin_id]["outputs"][origin_slot]
        target = nodes[target_id]["inputs"][target_slot]
        assert link_id in (origin.get("links") or [])
        assert target.get("link") == link_id
        # Reroutes and several legacy Comfy workflows serialize the concrete
        # resolved type on the link while retaining "*" or a stale socket type
        # on one endpoint. Structural ownership is the portable invariant.
        assert isinstance(link_type, str) and link_type
    for item in nodes.values():
        for input_value in item.get("inputs") or []:
            link_id = input_value.get("link")
            if link_id is not None:
                assert link_id in links
        for output in item.get("outputs") or []:
            for link_id in output.get("links") or []:
                assert link_id in links


def validate_t2v(path, editor_type, expected_blend):
    workflow = load(path)
    validate_links(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert "LoadImage" not in node_types
    assert not node_types.intersection({
        "PathchSageAttentionKJ",
        "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "SolAttnPatch",
    })

    attention = node(workflow, "ModelAttentionBackend")
    assert attention["widgets_values"] == ["comfy kitchen attention"]
    lora = node(workflow, "LoraLoaderModelOnly")
    assert lora["widgets_values"] == [
        "MiniMax H3/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        1.0,
    ]
    assert socket(attention["inputs"], "model")["link"] is not None
    assert socket(lora["inputs"], "model")["link"] is not None

    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert socket(conditioner["inputs"], "first_frame")["link"] is None
    assert socket(conditioner["inputs"], "last_frame")["link"] is None
    assert conditioner["widgets_values"][1:4] == [544, 960, 243]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert plan_node["widgets_values"][3:6] == [544, 960, 22]
    assert plan_node["widgets_values"][9] == "generated_audio"
    assert plan_node["widgets_values"][12] == 8
    assert plan_node["widgets_values"][15] == expected_blend
    assert plan["defaults"]["steps"] == 8
    assert node(workflow, "KSamplerSelect")["widgets_values"] == ["lcm"]
    scheduler = node(workflow, "BasicScheduler")
    assert scheduler["widgets_values"][0:2] == ["beta", 8]
    assert len(plan["shots"]) == 2
    assert [shot["length"] for shot in plan["shots"]] == [243, 243]
    for shot in plan["shots"]:
        prompt = "\n".join(shot["prompt"])
        first = prompt.index("integrated_multimodal_description:")
        sound = prompt.index("overall_soundscape:")
        music = prompt.index("non_diegetic_music:")
        assert first == 0 and first < sound < music
        assert "<Picture" not in prompt and "<Video" not in prompt
    assert "I have to be honest with you. I left Wan." in "\n".join(
        plan["shots"][0]["prompt"])

    editor = node(workflow, editor_type)
    assert socket(editor["inputs"], "plan")["link"] is not None
    assert ("MiniMaxH3ChainPlanStudio" in {
        item.get("type") for item in workflow["nodes"]}) == (
            editor_type == "MiniMaxH3ChainPlanStudio")
    rich_editors = [item for item in workflow["nodes"]
                    if item.get("type") ==
                    "MiniMaxH3ChainRichScenePromptEditor"]
    if editor_type == "MiniMaxH3ChainPlanStudio":
        assert len(rich_editors) == 1
        assert socket(rich_editors[0]["inputs"], "plan")["link"] is not None
    else:
        assert not rich_editors

    trim = node(workflow, "MiniMaxH3LoopTrim")
    saver = node(workflow, "MiniMaxH3ChainSegmentSave")
    assert socket(trim["inputs"], "retain_overlap_frames")["link"] is not None
    assert socket(trim["outputs"], "images_with_overlap")["links"]
    assert socket(saver["inputs"], "images_with_overlap")["link"] is not None

    review = node(workflow, "MiniMaxH3ChainReview")
    assert socket(review["inputs"], "source_audio")["link"] is None
    assert review["size"][1] >= 650

    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "🦙rishappi" in notes and SOURCE_URL in notes
    assert "Scene 2 is a new continuation" in notes
    if expected_blend:
        assert "blends only 5 frames" in notes
    else:
        assert "video_blend_frames = 0" in notes
    return workflow, plan


def validate_i2v(path, editor_type, expected_blend):
    workflow = load(path)
    validate_links(workflow)
    node_types = {item.get("type") for item in workflow["nodes"]}
    assert not node_types.intersection({
        "PathchSageAttentionKJ",
        "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "SolAttnPatch",
    })

    assert node(workflow, "ModelAttentionBackend")["widgets_values"] == [
        "comfy kitchen attention"]
    assert node(workflow, "LoraLoaderModelOnly")["widgets_values"] == [
        "MiniMax H3/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        1.0,
    ]
    assert node(workflow, "KSamplerSelect")["widgets_values"] == ["lcm"]
    assert node(workflow, "BasicScheduler")["widgets_values"][0:2] == [
        "beta", 8]

    loader = node(workflow, "LoadImage")
    assert loader["widgets_values"][0] == (
        "jigen_market_garden_doom_opening.png")
    gate = node(workflow, "MiniMaxH3ChainFirstSceneImage")
    assert socket(gate["inputs"], "state")["link"] is not None
    assert socket(gate["inputs"], "image")["link"] is not None
    conditioner = node(workflow, "MiniMaxH3ImageToVideo")
    assert socket(conditioner["inputs"], "first_frame")["link"] is not None
    assert socket(conditioner["inputs"], "last_frame")["link"] is None
    assert conditioner["widgets_values"][1:4] == [896, 672, 362]
    assert socket(gate["outputs"], "first_frame")["links"] == [
        socket(conditioner["inputs"], "first_frame")["link"]]

    plan_node = node(workflow, "MiniMaxH3ChainPlan")
    plan = json.loads(plan_node["widgets_values"][0])
    assert plan_node["widgets_values"][3:6] == [896, 672, 22]
    assert plan_node["widgets_values"][9] == "generated_audio"
    assert plan_node["widgets_values"][10:13] == [22, 15, 8]
    assert plan_node["widgets_values"][15] == expected_blend
    assert plan["defaults"] == {"duration_seconds": 15, "steps": 8}
    assert [shot["length"] for shot in plan["shots"]] == [362, 362]
    opening = "\n".join(plan["shots"][0]["prompt"])
    continuation = "\n".join(plan["shots"][1]["prompt"])
    assert opening.startswith(
        "For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.")
    assert opening.index("integrated_multimodal_description:") < (
        opening.index("overall_soundscape:")) < opening.index(
            "non_diegetic_music:")
    assert "Classic Doom 1993" in opening and "Market Garden" in opening
    assert continuation.startswith("integrated_multimodal_description:")
    assert "incoming H3 Motion Context" in continuation
    assert "<Picture" not in continuation and "<Video" not in continuation
    assert continuation.index("overall_soundscape:") < continuation.index(
        "non_diegetic_music:")

    editor = node(workflow, editor_type)
    assert socket(editor["inputs"], "plan")["link"] is not None
    rich_editors = [item for item in workflow["nodes"]
                    if item.get("type") ==
                    "MiniMaxH3ChainRichScenePromptEditor"]
    if editor_type == "MiniMaxH3ChainPlanStudio":
        assert len(rich_editors) == 1
        assert socket(rich_editors[0]["inputs"], "plan")["link"] is not None
    else:
        assert not rich_editors

    trim = node(workflow, "MiniMaxH3LoopTrim")
    saver = node(workflow, "MiniMaxH3ChainSegmentSave")
    assert socket(trim["inputs"], "retain_overlap_frames")["link"] is not None
    assert socket(saver["inputs"], "images_with_overlap")["link"] is not None
    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "ᴊɪɢᴇɴ" in notes and I2V_SOURCE_URL in notes
    assert "Scene 2 is a new continuation" in notes
    assert ("video_blend_frames = 5" if expected_blend
            else "video_blend_frames = 0") in notes
    return workflow, plan


def main():
    assert EXAMPLES.joinpath("README.md").is_file()
    assert ARCHIVE.joinpath("README.md").is_file()
    assert len(list(ARCHIVE.glob("*.json"))) == 7
    for path in ARCHIVE.glob("*.json"):
        validate_links(load(path))

    t2v_normal_path = EXAMPLES / "MiniMax H3 T2V - Normal.json"
    t2v_studio_path = EXAMPLES / "MiniMax H3 T2V - Studio.json"
    i2v_normal_path = EXAMPLES / "MiniMax H3 I2V - Normal.json"
    i2v_studio_path = EXAMPLES / "MiniMax H3 I2V - Studio.json"
    assert set(path.name for path in EXAMPLES.glob("*.json")) == {
        t2v_normal_path.name, t2v_studio_path.name,
        i2v_normal_path.name, i2v_studio_path.name,
    }
    t2v_normal, t2v_normal_plan = validate_t2v(
        t2v_normal_path, "MiniMaxH3ChainScenePromptEditor", 0)
    t2v_studio, t2v_studio_plan = validate_t2v(
        t2v_studio_path, "MiniMaxH3ChainPlanStudio", 5)
    assert t2v_normal_plan == t2v_studio_plan
    i2v_normal, i2v_normal_plan = validate_i2v(
        i2v_normal_path, "MiniMaxH3ChainScenePromptEditor", 0)
    i2v_studio, i2v_studio_plan = validate_i2v(
        i2v_studio_path, "MiniMaxH3ChainPlanStudio", 5)
    assert i2v_normal_plan == i2v_studio_plan

    def generation_types(workflow):
        return collections.Counter(
            item.get("type")
            for item in workflow["nodes"]
            if item.get("type") not in {
                "MiniMaxH3ChainScenePromptEditor",
                "MiniMaxH3ChainPlanStudio",
                "MiniMaxH3ChainRichScenePromptEditor",
            })

    assert generation_types(t2v_normal) == generation_types(t2v_studio)
    assert generation_types(i2v_normal) == generation_types(i2v_studio)
    uuids = {
        workflow["extra"]["comfyui_mcp"]["workflow_uuid"]
        for workflow in (t2v_normal, t2v_studio, i2v_normal, i2v_studio)
    }
    assert len(uuids) == 4

    asset = EXAMPLES / "assets" / "jigen_market_garden_doom_opening.png"
    assert asset.is_file()
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == I2V_ASSET_SHA256

    print("H3 workflow catalog: Archive plus paired Normal/Studio T2VA and "
          "I2VA workflows, valid links, bundled asset integrity, proper "
          "prompt sections, and visible source attribution pass")


if __name__ == "__main__":
    main()
