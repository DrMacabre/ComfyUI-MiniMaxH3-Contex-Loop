#!/usr/bin/env python3
"""Type-based example catalog and paired T2VA workflow regression."""

import collections
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "example_workflows"
ARCHIVE = EXAMPLES / "Archive"
T2V = EXAMPLES / "T2V"
SOURCE_URL = (
    "https://discord.com/channels/1076117621407223829/"
    "1532625331960152124/1536689209761599608"
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


def validate_t2v(path, editor_type):
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
    assert plan_node["widgets_values"][15] == 5
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

    trim = node(workflow, "MiniMaxH3LoopTrim")
    saver = node(workflow, "MiniMaxH3ChainSegmentSave")
    assert socket(trim["inputs"], "retain_overlap_frames")["link"] is not None
    assert socket(trim["outputs"], "images_with_overlap")["links"]
    assert socket(saver["inputs"], "images_with_overlap")["link"] is not None

    notes = "\n".join(
        str(item.get("widgets_values", [""])[0])
        for item in workflow["nodes"] if item.get("type") == "Note")
    assert "🦙rishappi" in notes and SOURCE_URL in notes
    assert "Scene 2 is a new continuation" in notes
    return workflow, plan


def main():
    assert EXAMPLES.joinpath("README.md").is_file()
    assert ARCHIVE.joinpath("README.md").is_file()
    assert T2V.joinpath("README.md").is_file()
    assert len(list(ARCHIVE.glob("*.json"))) == 7
    for path in ARCHIVE.glob("*.json"):
        validate_links(load(path))

    normal_path = T2V / "MiniMax H3 T2V - Normal.json"
    studio_path = T2V / "MiniMax H3 T2V - Studio.json"
    assert set(path.name for path in T2V.glob("*.json")) == {
        normal_path.name, studio_path.name,
    }
    normal, normal_plan = validate_t2v(
        normal_path, "MiniMaxH3ChainScenePromptEditor")
    studio, studio_plan = validate_t2v(
        studio_path, "MiniMaxH3ChainPlanStudio")
    assert normal_plan == studio_plan

    def generation_types(workflow):
        return collections.Counter(
            "PROMPT_INTERFACE" if item.get("type") in {
                "MiniMaxH3ChainScenePromptEditor",
                "MiniMaxH3ChainPlanStudio",
            } else item.get("type")
            for item in workflow["nodes"])

    assert generation_types(normal) == generation_types(studio)
    assert normal["extra"]["comfyui_mcp"]["workflow_uuid"] != (
        studio["extra"]["comfyui_mcp"]["workflow_uuid"])

    print("H3 workflow catalog: Archive plus equivalent Normal/Studio T2VA "
          "pairs, valid links, proper prompt sections, and visible source "
          "attribution pass")


if __name__ == "__main__":
    main()
