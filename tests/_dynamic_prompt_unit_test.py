#!/usr/bin/env python3
"""Random prompt alternatives stay reproducible and resume-safe."""

import importlib.util
import json
import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "h3_dynamic_prompt_unit"

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
shared_nodes._prepare_native_guide_conditioning = lambda value: value
shared_nodes._resize = lambda *args: None
shared_nodes._streams_from_latent = lambda *args: None
sys.modules[shared_nodes.__name__] = shared_nodes

spec = importlib.util.spec_from_file_location(
    PACKAGE + ".chain_nodes", ROOT / "chain_nodes.py")
chain = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = chain
spec.loader.exec_module(chain)


def normalize(prompt_seed, prompt="A {wide|close} shot with {rain|sun}."):
    return chain._normalize_plan(
        json.dumps({"shots": [{
            "id": "one", "prompt": prompt, "length": 39, "seed": 123,
        }]}),
        "dynamic-prompt-test", 64, 64, 22, "video", "head", "disabled",
        "generated_audio", 22, 2.0, 8, 7, 18, "model-stack", 0,
        "guide", None, prompt_seed)


rendered, used = chain._resolve_dynamic_prompt(
    r"Keep \{literal\}, {one|two}, and {outer {left|right}|still}.",
    42, "one")
assert used
assert "{literal}" in rendered
assert "|" not in rendered.replace("{literal}", "")
assert chain._resolve_dynamic_prompt("ordinary {camera note}", 42) == (
    "ordinary {camera note}", False)
assert chain._resolve_dynamic_prompt(r"literal \{one\|two\}", 42) == (
    "literal {one|two}", False)

first = normalize(0)
assert first["shots"][0]["seed"] == 123
assert first["shots"][0]["scene_prompt_template"] == (
    "A {wide|close} shot with {rain|sun}.")
assert first["shots"][0]["scene_prompt"] != (
    first["shots"][0]["scene_prompt_template"])
assert first["shots"][0]["prompt_choice_seed"] == chain._derived_seed(
    0, 1, "one")

different = None
for candidate_seed in range(1, 100):
    candidate = normalize(candidate_seed)
    if (candidate["shots"][0]["scene_prompt"] !=
            first["shots"][0]["scene_prompt"]):
        different = candidate
        break
assert different is not None, "prompt seeds did not exercise another alternative"
assert different["shots"][0]["seed"] == first["shots"][0]["seed"]
assert different["plan_hash"] == first["plan_hash"]
assert chain._history_hash(different, 1) == chain._history_hash(first, 1)
assert chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(different, 1),
) == []

changed_template = normalize(candidate_seed, "A {wide|close} shot at night.")
template_diffs = chain._scene_dependency_diffs(
    chain._scene_dependency_record(first, 1),
    chain._scene_dependency_record(changed_template, 1),
)
assert any(item["field"] == "prompt_template_hash" for item in template_diffs)

rerolled_sampler = chain._plan_with_review_revision(
    first, 1, first["shots"][0]["scene_prompt_template"], 999, 39)
assert rerolled_sampler["shots"][0]["seed"] == 999
assert (rerolled_sampler["shots"][0]["scene_prompt"] ==
        first["shots"][0]["scene_prompt"])
assert (rerolled_sampler["shots"][0]["prompt_choice_seed"] ==
        first["shots"][0]["prompt_choice_seed"])

plain_zero = normalize(0, "A fixed shot.")
plain_random = normalize(999, "A fixed shot.")
assert plain_zero["shots"][0]["scene_prompt"] == "A fixed shot."
assert "scene_prompt_template" not in plain_zero["shots"][0]
assert plain_zero["plan_hash"] == plain_random["plan_hash"]

prompt_seed_schema = chain.MiniMaxH3ChainPlan.INPUT_TYPES()["optional"][
    "prompt_seed"][1]
assert prompt_seed_schema["control_after_generate"] is True

print("dynamic prompt unit test passed")
