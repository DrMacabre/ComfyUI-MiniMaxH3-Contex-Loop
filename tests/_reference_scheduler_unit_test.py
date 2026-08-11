#!/usr/bin/env python3
"""Standalone scheduler compiler test without importing a ComfyUI checkout."""

import importlib.util
import json
import pathlib
import sys
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
shared_nodes._prepare_native_guide_conditioning = lambda *args: None
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


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
    ROOT / "example_workflows" /
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

picture_inputs = chain.MiniMaxH3ScheduledPictureReference.INPUT_TYPES()[
    "required"]
video_inputs = chain.MiniMaxH3ScheduledVideoReference.INPUT_TYPES()["required"]
audio_inputs = chain.MiniMaxH3ScheduledAudioReference.INPUT_TYPES()["required"]
assert "declaration" not in picture_inputs
assert "declaration" not in video_inputs
assert "audio_declaration" not in video_inputs
assert "declaration" not in audio_inputs
assert "audio_tag" in video_inputs

print("H3 scheduler: alias-only compilation and visible Plan definitions pass")
