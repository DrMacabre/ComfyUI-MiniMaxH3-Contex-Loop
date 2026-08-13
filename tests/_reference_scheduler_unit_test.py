#!/usr/bin/env python3
"""Standalone scheduler compiler test without importing a ComfyUI checkout."""

import importlib.util
import json
import math
import pathlib
import sys
import tempfile
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_reference_scheduler_unit"

folder_paths = types.ModuleType("folder_paths")
folder_paths.get_output_directory = lambda: str(ROOT)
folder_paths.get_temp_directory = lambda: str(ROOT)
folder_paths.get_input_directory = lambda: str(ROOT)
folder_paths.get_annotated_filepath = lambda value: str(value)
sys.modules["folder_paths"] = folder_paths

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


exact_362_audio = {
    "waveform": chain.torch.ones((1, 2, 482667)),
    "sample_rate": 32000,
}
aligned_362_audio, aligned_362_status = (
    chain._align_audio_reference_to_h3_grid(exact_362_audio, 362))
assert int(aligned_362_audio["waveform"].shape[-1]) == 482240
assert "target 603 steps, safe 15.070000s" in aligned_362_status

exact_362_audio_44k = {
    "waveform": chain.torch.ones((1, 2, round(362 / 24 * 44100))),
    "sample_rate": 44100,
}
aligned_362_audio_44k, _ = chain._align_audio_reference_to_h3_grid(
    exact_362_audio_44k, 362)
aligned_44k_samples = int(aligned_362_audio_44k["waveform"].shape[-1])
assert aligned_44k_samples == 664587
assert math.ceil(aligned_44k_samples * 32000 / 44100) == 482240

short_audio = {
    "waveform": chain.torch.ones((1, 2, 480000)),
    "sample_rate": 32000,
}
unchanged_audio, unchanged_status = (
    chain._align_audio_reference_to_h3_grid(short_audio, 362))
assert unchanged_audio is short_audio
assert "unchanged" in unchanged_status


class LazyAudio:
    """Minimal non-dict ComfyUI AUDIO proxy for compatibility testing."""

    def __init__(self, value):
        self.value = value
        self.reads = 0

    def __getitem__(self, key):
        self.reads += 1
        return self.value[key]


class FakeDynamicPrompt:
    def __init__(self, nodes):
        self.nodes = nodes

    def all_node_ids(self):
        return set(self.nodes)

    def get_node(self, node_id):
        return self.nodes[node_id]

def schedule():
    return chain._make_reference_schedule([
        {
            "kind": "picture", "tag": "hero_face", "scenes": "1:7",
            "ranges": ((1, 7),), "value": object(), "content_hash": "face",
            "declaration": "THIS LEGACY TEXT MUST NEVER BE INSERTED",
        },
        {
            "kind": "picture", "tag": "hero_look", "scenes": "all",
            "ranges": (), "value": object(), "content_hash": "look",
        },
        {
            "kind": "video", "tag": "performance", "scenes": "4:6",
            "ranges": ((4, 6),), "value": object(), "audio": object(),
            "audio_tag": "performance_audio", "content_hash": "video",
            "audio_hash": "paired-audio",
            "audio_declaration": "NOR THIS LEGACY TEXT",
        },
        {
            "kind": "audio", "tag": "song", "scenes": "all",
            "ranges": (), "value": object(), "content_hash": "song",
        },
    ])


workflow = json.loads((
    ROOT / "example_workflows" / "Archive" /
    "Looping MiniMax H3 Seamless Chain V2 - Scheduled Refs.json"
).read_text(encoding="utf-8"))
plan_node = next(node for node in workflow["nodes"]
                 if node.get("type") == "MiniMaxH3ChainPlan")
plan = json.loads(plan_node["widgets_values"][0])

for scene in (1, 4, 8):
    source = "\n".join(plan["shots"][scene - 1]["prompt"])
    compiled, mapping, _bindings = chain._compile_scheduled_reference_prompt(
        schedule(), scene, 14, source)
    assert "@hero" not in compiled
    assert "@performance" not in compiled
    assert "@song" not in compiled
    assert "LEGACY TEXT" not in compiled
    assert "{ref}" not in compiled
    assert compiled.startswith("subject_definitions:\n<Subject 1>")
    if scene == 1:
        assert "<Picture 1>" in compiled and "<Picture 2>" in compiled
        assert "<Audio 1> is the current frame-exact" in compiled
    elif scene == 4:
        assert "<Video 1> provides a weak reference" in compiled
        assert "<Audio 1> is the synchronized soundtrack" in compiled
        assert "<Audio 2> is the current frame-exact" in compiled
    else:
        assert "defined by <Picture 1>" in compiled
        assert "<Picture 2>" not in compiled
        assert "<Audio 1> is the current frame-exact" in compiled
    assert mapping.startswith("scene %d/14:" % scene)

warning_prompt, warning_summary, warning_bindings = (
    chain._compile_scheduled_reference_prompt(
        schedule(), 1, 14,
        "Resolve @hero_face; preserve @missing and @missing.",
        compliance_mode="soft"))
assert warning_prompt == (
    "Resolve <Picture 1>; preserve @missing and @missing.")
assert len(warning_bindings["compliance_warnings"]) == 1
assert "unknown scheduled reference tag @missing" in warning_summary
compliance_options = (
    chain.MiniMaxH3ScheduledReferenceToVideo.INPUT_TYPES()["optional"]
    ["prompt_compliance"])
assert compliance_options[0] == ["strict", "soft", "disabled"]
assert compliance_options[1]["default"] == "strict"
disabled_prompt, disabled_summary, disabled_bindings = (
    chain._compile_scheduled_reference_prompt(
        schedule(), 1, 14,
        "Leave @hero_face and @missing entirely to the user.",
        compliance_mode="disabled"))
assert disabled_prompt == "Leave @hero_face and @missing entirely to the user."
assert disabled_bindings["compliance_warnings"] == []
assert disabled_bindings["compliance_mode"] == "disabled"
assert "@tags passed unchanged" in disabled_summary
assert chain._reference_compliance_mode(True) == "strict"
assert chain._reference_compliance_mode(False) == "soft"
assert chain.MiniMaxH3ScheduledReferenceToVideo.VALIDATE_INPUTS(True) is True
assert chain.MiniMaxH3ScheduledReferenceToVideo.VALIDATE_INPUTS(False) is True
assert "must be strict, soft, or disabled" in (
    chain.MiniMaxH3ScheduledReferenceToVideo.VALIDATE_INPUTS("unknown"))

disabled_graph = FakeDynamicPrompt({
    "audio": {
        "class_type": "MiniMaxH3ScheduledAudioReference", "inputs": {}},
    "wrapper": {
        "class_type": "MiniMaxH3ScheduledReferenceToVideo",
        "inputs": {
            "reference_schedule": ["audio", 0],
            "prompt_compliance": "disabled",
        },
    },
})
skipped_schedule, skipped_fingerprint, skipped_status = (
    chain.MiniMaxH3ScheduledAudioReference().add(
        None, "song", "all", dynprompt=disabled_graph, unique_id="audio"))
assert skipped_schedule["entries"] == []
assert skipped_schedule["fingerprint"] == skipped_fingerprint
assert "skipped because compliance is disabled" in skipped_status

disabled_picture_graph = FakeDynamicPrompt({
    "picture": {
        "class_type": "MiniMaxH3ScheduledPictureReference", "inputs": {}},
    "wrapper": disabled_graph.nodes["wrapper"] | {
        "inputs": {
            "reference_schedule": ["picture", 0],
            "prompt_compliance": "disabled",
        },
    },
})
unchecked_picture = chain.MiniMaxH3ScheduledPictureReference().add(
    chain.torch.zeros((1, 4, 4, 3)), "!!!", "not-a-selector",
    dynprompt=disabled_picture_graph, unique_id="picture")[0]
assert len(unchecked_picture["entries"]) == 1
assert unchecked_picture["entries"][0]["tag"].startswith("reference_")
assert unchecked_picture["entries"][0]["scenes"] == "all"

too_many_audio = chain._make_reference_schedule([
    {
        "kind": "audio", "tag": "audio_%d" % index, "scenes": "all",
        "ranges": (), "value": object(), "content_hash": str(index),
    }
    for index in range(4)
])
capacity_prompt, capacity_summary, capacity_bindings = (
    chain._compile_scheduled_reference_prompt(
        too_many_audio, 1, 1, "User-managed <Audio 1>.",
        compliance_mode="disabled"))
assert capacity_prompt == "User-managed <Audio 1>."
assert len(capacity_bindings["audios"]) == 3
assert "only the first 3 were kept" in capacity_summary

malformed_prompt, malformed_summary, malformed_bindings = (
    chain._compile_scheduled_reference_prompt(
        {"version": -1, "entries": "broken"}, 99, 0,
        "Entirely user-managed prompt.", compliance_mode="disabled"))
assert malformed_prompt == "Entirely user-managed prompt."
assert malformed_bindings["pictures"] == []
assert "Reference schedule ignored" in malformed_summary

soft_graph = FakeDynamicPrompt({
    "audio": disabled_graph.nodes["audio"],
    "wrapper": {
        "class_type": "MiniMaxH3ScheduledReferenceToVideo",
        "inputs": {
            "reference_schedule": ["audio", 0],
            "prompt_compliance": "soft",
        },
    },
})
try:
    chain.MiniMaxH3ScheduledAudioReference().add(
        None, "song", "all", dynprompt=soft_graph, unique_id="audio")
except ValueError as exc:
    assert "received no audio (None)" in str(exc)
else:
    raise AssertionError("soft compliance accepted missing scheduled audio")

picture_inputs = chain.MiniMaxH3ScheduledPictureReference.INPUT_TYPES()[
    "required"]
video_inputs = chain.MiniMaxH3ScheduledVideoReference.INPUT_TYPES()["required"]
audio_inputs = chain.MiniMaxH3ScheduledAudioReference.INPUT_TYPES()["required"]
assert "declaration" not in picture_inputs
assert "declaration" not in video_inputs
assert "audio_declaration" not in video_inputs
assert "declaration" not in audio_inputs

lazy_audio = LazyAudio({
    "waveform": chain.torch.zeros((1, 2, 8000), dtype=chain.torch.float32),
    "sample_rate": 8000,
})
lazy_schedule, lazy_fingerprint, lazy_status = (
    chain.MiniMaxH3ScheduledAudioReference().add(
        lazy_audio, "lazy_voice", "1:2"))
assert lazy_audio.reads > 0
assert lazy_schedule["entries"][0]["value"] is lazy_audio
assert len(lazy_schedule["entries"][0]["content_hash"]) == 64
assert lazy_schedule["fingerprint"] == lazy_fingerprint
assert "@lazy_voice audio on 1:2" in lazy_status
try:
    chain.MiniMaxH3ScheduledAudioReference().add(
        None, "missing_voice", "1")
except ValueError as exc:
    message = str(exc)
    assert "received no audio (None)" in message
    assert "source_audio_slice" in message
    assert "generated_audio" in message
    assert "connect Load Audio directly" in message
    assert "source_plus_timeline" in message
    assert "muted or bypassed" in message
    assert "playable browser preview" in message
else:
    raise AssertionError("missing scheduled audio was accepted")
try:
    chain.MiniMaxH3ScheduledAudioReference().add(
        lambda: b"legacy VHS_AUDIO", "legacy", "1")
except ValueError as exc:
    assert "ComfyUI AUDIO" in str(exc)
else:
    raise AssertionError("legacy callable VHS_AUDIO was accepted")

plan_inputs = chain.MiniMaxH3ChainPlan.INPUT_TYPES()["required"]
audio_mode_help = plan_inputs["audio_mode"][1]["tooltip"]
assert "does NOT enable or disable @voice/<Audio N> references" in audio_mode_help
assert "finished prerecorded voice" in audio_mode_help
assert "short @voice identity/timbre reference" in audio_mode_help
assert "generated_audio" in audio_mode_help
assert "experimental" in audio_mode_help
assert "output/h3_chains" in plan_inputs["run_name"][1]["tooltip"]
base_seed_help = plan_inputs["base_seed"][1]["tooltip"]
assert "Reroll seed does NOT change base_seed" in base_seed_help
assert "always-visible Scene seed" in base_seed_help
assert "audio_tag" in video_inputs
assert video_inputs["timeline_mode"][0] == [
    "restart_each_scene", "sequential"]
assert "state" in chain.MiniMaxH3ScheduledReferenceToVideo.INPUT_TYPES()[
    "optional"]
apply_arguments = (
    chain.MiniMaxH3ScheduledReferenceToVideo.apply.__code__.co_varnames[
        :chain.MiniMaxH3ScheduledReferenceToVideo.apply.__code__.co_argcount])
assert "state" in apply_arguments and "prompt_compliance" in apply_arguments
assert "timeline_mode" not in chain._reference_entry_contract({
    "kind": "video", "tag": "motion", "scenes": "all",
    "content_hash": "video", "timeline_mode": "restart_each_scene",
})
assert chain._reference_entry_contract({
    "kind": "video", "tag": "motion", "scenes": "all",
    "content_hash": "video", "timeline_mode": "sequential",
})["timeline_mode"] == "sequential"

sequential_video = chain.torch.arange(
    500, dtype=chain.torch.float32).reshape(500, 1, 1, 1).expand(-1, 2, 2, 3)
sequential_audio = {
    "waveform": chain.torch.arange(
        5000, dtype=chain.torch.float32).reshape(1, 1, 5000),
    "sample_rate": 240,
}
sequential_schedule = chain.MiniMaxH3ScheduledVideoReference().add(
    sequential_video, "motion", "", "motion_audio", "sequential",
    audio=sequential_audio)[0]
sequential_entry = sequential_schedule["entries"][0]
assert sequential_entry["timeline_mode"] == "sequential"
sequential_state = {
    "index": 2,
    "plan": {
        "shots": [
            {"raw_frames": 243, "generation_start_frame": 0},
            {"raw_frames": 243, "generation_start_frame": 221},
        ],
    },
}
video_slice, audio_slice, slice_detail = (
    chain._scheduled_video_reference_slice(
        sequential_entry, sequential_state, 2, 2, 243))
assert tuple(video_slice.shape) == (243, 2, 2, 3)
assert float(video_slice[0, 0, 0, 0]) == 221
assert float(video_slice[-1, 0, 0, 0]) == 463
assert tuple(audio_slice["waveform"].shape) == (1, 1, 2430)
assert float(audio_slice["waveform"][0, 0, 0]) == 2210
assert slice_detail == "@motion sequential frames 221:464 (origin scene 1)"
try:
    chain._scheduled_video_reference_slice(
        sequential_entry, None, 2, 2, 243)
except ValueError as exc:
    assert "Current Shot state" in str(exc)
else:
    raise AssertionError("sequential reference accepted missing state")
conditioning = object()
priority_result = chain.MiniMaxH3PatchPriority().claim(conditioning)
assert priority_result == (conditioning, "test patch owner")

original_output_root = chain._output_root
original_launch_directory = chain._launch_directory
try:
    with tempfile.TemporaryDirectory() as output_root:
        opened_paths = []
        chain._output_root = lambda: output_root
        chain._launch_directory = lambda path: (
            opened_paths.append(path) or True, None)
        folder_result = chain._open_run_output_directory("Project Name")
        expected_folder = pathlib.Path(
            output_root, "h3_chains", "Project_Name")
        assert folder_result["opened"] is True
        assert pathlib.Path(folder_result["path"]) == expected_folder
        assert expected_folder.is_dir()
        assert opened_paths == [str(expected_folder)]
        chain._launch_directory = lambda _path: (False, "headless host")
        fallback_result = chain._open_run_output_directory("Project Name")
        assert fallback_result["opened"] is False
        assert fallback_result["error"] == "headless host"
        try:
            chain._open_run_output_directory("../../")
        except ValueError as exc:
            assert "run_name" in str(exc)
        else:
            raise AssertionError("unsafe empty run_name was accepted")
finally:
    chain._output_root = original_output_root
    chain._launch_directory = original_launch_directory

i2va_workflow = json.loads((
    ROOT / "example_workflows" / "Archive" /
    "Looping MiniMax H3 V2 - Single Image I2VA 20s.json"
).read_text(encoding="utf-8"))
i2va_plan_node = next(node for node in i2va_workflow["nodes"]
                       if node.get("type") == "MiniMaxH3ChainPlan")
context_choices = chain.MiniMaxH3ChainPlan.INPUT_TYPES()["required"][
    "context_length"][0]
assert context_choices == [
    1, 5, 22, 39, 56, 73, 90, 107, 124,
    141, 158, 175, 192, 209, 226, 243,
]
normalized = chain.MiniMaxH3ChainPlan().build(
    *i2va_plan_node["widgets_values"])[0]
assert [shot["raw_frames"] for shot in normalized["shots"]] == [243, 243]
assert [shot["delivered_frames"] for shot in normalized["shots"]] == [243, 238]
assert normalized["total_delivered_frames"] == 481
assert normalized["total_delivered_frames"] / chain.FPS > 20
assert normalized["compatibility"]["context_length"] == 5
assert "<Picture 1>" in normalized["shots"][0]["scene_prompt"]
assert "<Picture" not in normalized["shots"][1]["scene_prompt"]

gate_node = next(node for node in i2va_workflow["nodes"]
                 if node.get("type") == "MiniMaxH3ChainFirstSceneImage")
assert gate_node["inputs"][0]["name"] == "state"
assert gate_node["inputs"][1]["name"] == "image"
opening_image = object()
gate = chain.MiniMaxH3ChainFirstSceneImage()
first_result = gate.select({"index": 1}, opening_image)
later_result = gate.select({"index": 2}, opening_image)
assert first_result[:2] == (opening_image, True)
assert later_result[:2] == (None, False)
last_target = object()
assert gate.select({"index": 1}, opening_image, last_target)[3] is last_target
assert gate.select({"index": 2}, opening_image, last_target)[3] is last_target
assert gate.INPUT_TYPES()["optional"]["last_frame"][0] == "IMAGE"
assert gate.RETURN_NAMES[-1] == "last_frame"

frame_a = object()
frame_b = object()
switch = chain.MiniMaxH3ChainFrameIndexSwitch()
assert switch.select(1, frame_b, frame_2=frame_a)[:2] == (frame_b, 1)
assert switch.select(2, frame_b, frame_2=frame_a)[:2] == (frame_a, 2)
assert switch.select(3, frame_b, frame_2=frame_a)[:2] == (frame_b, 1)
assert switch.INPUT_TYPES()["optional"]["frame_8"][0] == "IMAGE"

links = {link[0]: link for link in i2va_workflow["links"]}
nodes = {node["id"]: node for node in i2va_workflow["nodes"]}
for node in nodes.values():
    for slot, input_spec in enumerate(node.get("inputs", [])):
        link_id = input_spec.get("link")
        if link_id is None:
            continue
        assert link_id in links
        assert links[link_id][3:5] == [node["id"], slot]
    for slot, output_spec in enumerate(node.get("outputs", [])):
        for link_id in output_spec.get("links") or []:
            assert link_id in links
            assert links[link_id][1:3] == [node["id"], slot]
i2v_node = next(node for node in nodes.values()
                 if node.get("type") == "MiniMaxH3ImageToVideo")
assert next(item for item in i2v_node["inputs"]
            if item["name"] == "first_frame")["link"] is not None
assert next(item for item in i2v_node["inputs"]
            if item["name"] == "last_frame")["link"] is None

print("H3 scheduler: aliases, Plan guidance, and looping I2VA workflow pass")
