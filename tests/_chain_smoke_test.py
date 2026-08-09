#!/usr/bin/env python3
"""CPU smoke test for H3 chain timing, segments, checkpoints and resume.

Uses the adjacent ComfyUI checkout for its real node/runtime modules, but no
model or GPU.  It encodes two tiny H.264 segments, resumes clip 2 from clip 1's
safetensors checkpoint, and assembles both source-track and generated-audio
outputs with ffmpeg.
"""

import asyncio
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMFY_CANDIDATES = [ROOT.parent / "Comfyui", ROOT.parent / "ComfyUI"]
COMFY = next((path for path in COMFY_CANDIDATES
              if (path / "comfy" / "options.py").is_file()), None)
if COMFY is None:
    raise SystemExit("adjacent ComfyUI checkout not found")

sys.path.insert(0, str(COMFY))
sys.argv = ["h3-chain-smoke", "--cpu"]
import comfy.options  # noqa: E402

comfy.options.enable_args_parsing()
import folder_paths  # noqa: E402
import torch  # noqa: E402
import execution  # noqa: E402
import nodes as comfy_nodes  # noqa: E402


def load_package():
    spec = importlib.util.spec_from_file_location(
        "h3_chain_smoke_package",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return package, sys.modules[spec.name + ".chain_nodes"]


def av_latent(video_t=1, audio_t=9):
    return {
        "samples": [
            torch.zeros((1, 16, video_t, 2, 2), dtype=torch.float32),
            torch.zeros((1, 32, 2, audio_t), dtype=torch.float32),
        ]
    }


def audio_for_frames(frames, sample_rate=8000):
    samples = round(frames / 24.0 * sample_rate)
    return {
        "waveform": torch.zeros((1, 2, samples), dtype=torch.float32),
        "sample_rate": sample_rate,
    }


class FakeDynamicPrompt:
    def __init__(self, prompt):
        self.prompt = prompt

    def get_node(self, node_id):
        return self.prompt[str(node_id)]

    def get_display_node_id(self, node_id):
        return str(node_id)

    def get_original_prompt(self):
        return self.prompt


def main():
    package, chain = load_package()

    async def review_route_check():
        token = "review-route-smoke"
        future = asyncio.get_running_loop().create_future()
        chain._PENDING_REVIEWS[token] = {
            "future": future,
            "public": {"token": token},
            "current_seed": 7,
        }

        class Request:
            async def json(self):
                return {
                    "token": token,
                    "action": "retry",
                    "scene_prompt": "Edited after review.",
                    "seed": "18446744073709551615",
                }

        try:
            response = await chain._submit_review_decision(Request())
            assert response.status == 200
            decision = await future
            assert decision["action"] == "retry"
            assert decision["scene_prompt"] == "Edited after review."
            assert decision["seed"] == 18446744073709551615
        finally:
            chain._PENDING_REVIEWS.pop(token, None)

    asyncio.run(review_route_check())
    print("review: async decision route preserves exact uint64 seeds")
    required = {
        "MiniMaxH3ChainPlan", "MiniMaxH3ChainLoopStart",
        "MiniMaxH3ChainCurrent", "MiniMaxH3ChainContext",
        "MiniMaxH3ChainSegmentSave", "MiniMaxH3ChainLoopEnd",
        "MiniMaxH3ChainManifestLoad", "MiniMaxH3ChainAssemble",
    }
    assert required <= set(package.NODE_CLASS_MAPPINGS)
    assert package.WEB_DIRECTORY == "./web"
    assert (ROOT / "web" / "h3_chain_plan_editor.js").is_file()
    assert (ROOT / "web" / "h3_chain_plan_core.mjs").is_file()

    readable_prompts = chain._normalize_plan(
        json.dumps({
            "prompt_prefix": ["Shared identity.", "", "Shared wardrobe."],
            "shots": [{
                "id": "multiline",
                "prompt": [
                    "Use <Picture 1> for her facial identity.",
                    "Throughout every scene S1 wears the same dress.",
                    "<Subject 2> enters from camera right.",
                ],
                "length": 39,
            }],
        }),
        "readable", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    assert readable_prompts["shots"][0]["prompt"] == (
        "Shared identity.\n\nShared wardrobe.\n\n"
        "Use <Picture 1> for her facial identity.\n"
        "Throughout every scene S1 wears the same dress.\n"
        "<Subject 2> enters from camera right."
    )
    numeric_seed_plan = chain._normalize_plan(
        '{"shots":[{"prompt":"seed test","seed":18446744073709551615}]}',
        "numeric_seed", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    string_seed_plan = chain._normalize_plan(
        '{"shots":[{"prompt":"seed test","seed":"18446744073709551615"}]}',
        "numeric_seed", 32, 32, 22, "video", "head", "disabled",
        "source_track", 0, 15, 2, 1, 30,
    )
    assert numeric_seed_plan["shots"][0]["seed"] == chain.MAX_SEED
    assert numeric_seed_plan["plan_hash"] == string_seed_plan["plan_hash"]
    try:
        chain._normalize_plan(
            json.dumps({"shots": [{"prompt": ["valid", 42]}]}),
            "bad_lines", 32, 32, 22, "video", "head", "disabled",
            "source_track", 0, 15, 2, 1, 30,
        )
    except ValueError as exc:
        assert "only strings" in str(exc)
    else:
        raise AssertionError("prompt line array accepted a non-string item")
    print("prompts: string arrays become real newlines; invalid lines rejected")

    # ComfyUI rounds H3's 40 Hz audio grid to the nearest step. Depending on
    # frame length, the decoded stream can land 1/3 step above or below the
    # exact 24 fps picture duration. Match Tail must frame-lock both cases.
    trim_node = package.NODE_CLASS_MAPPINGS["MiniMaxH3MotionContextTrim"]()
    short_images = torch.zeros((260, 1, 1, 3), dtype=torch.float32)
    short_samples = 346400  # 433 audio steps; exact 260f target is 346667
    short_audio = {
        "waveform": torch.ones((1, 2, short_samples), dtype=torch.float32),
        "sample_rate": 32000,
    }
    _, padded = trim_node.trim(short_images, 0, short_audio, 24.0, True)
    assert int(padded["waveform"].shape[-1]) == 346667
    assert torch.count_nonzero(padded["waveform"][..., short_samples:]) == 0
    chain._validate_audio(padded, "260-frame regression", expected_frames=260)

    long_images = torch.zeros((124, 1, 1, 3), dtype=torch.float32)
    long_samples = 165600  # 207 audio steps; exact 124f target is 165333
    long_audio = {
        "waveform": torch.ones((1, 2, long_samples), dtype=torch.float32),
        "sample_rate": 32000,
    }
    _, truncated = trim_node.trim(long_images, 0, long_audio, 24.0, True)
    assert int(truncated["waveform"].shape[-1]) == 165333
    print("trim: 260-frame shortage padded and 124-frame excess truncated")

    giant_plan = chain._normalize_plan(
        json.dumps({
            "shots": [
                {"id": str(index), "prompt": "shot %d" % index}
                for index in range(1, 14)
            ] + [{"id": "14", "prompt": "outro", "duration_seconds": 5}]
        }),
        "timing", 960, 544, 22, "video", "head", "disabled",
        "source_track", 22, 15, 20, 123, 18,
    )
    assert giant_plan["shots"][0]["raw_frames"] == 362
    assert giant_plan["shots"][1]["generation_start_frame"] == 340
    assert giant_plan["shots"][-1]["raw_frames"] == 124
    assert giant_plan["shots"][-1]["generation_start_frame"] == 4420
    assert giant_plan["total_delivered_frames"] == 4544
    print("timing: 14 clips -> 4544 frames / 189.333s; frame-exact starts pass")

    assert chain._h3_frame_length(5 / 24 + 0.001) == 22
    assert chain._h3_frame_length(22 / 24 + 0.001) == 39
    try:
        chain._h3_frame_length(150.0)
    except ValueError as exc:
        assert "largest valid" in str(exc)
    else:
        raise AssertionError("duration-derived length exceeded H3's maximum")
    print("duration grid: always rounds up and rejects over-limit lengths")

    before_plan = chain._normalize_plan(
        json.dumps({"shots": ["first", "second", "third", "fourth"]}),
        "before", 32, 32, 1, "video", "before", "disabled",
        "generated_audio", 1, 0.1, 2, 1, 30,
    )
    assert [shot["delivered_frames"] for shot in before_plan["shots"]] == [5] * 4
    assert before_plan["shots"][1]["generation_start_frame"] == 5

    try:
        chain._normalize_plan(
            json.dumps({"shots": [
                {"prompt": "too short", "length": 5},
                {"prompt": "next", "length": 39},
            ]}),
            "short", 32, 32, 22, "video", "head", "disabled",
            "generated_audio", 22, 1, 2, 1, 30,
        )
    except ValueError as exc:
        assert "next clip requires 22 context frames" in str(exc)
    else:
        raise AssertionError("plan accepted an undersized predecessor context")

    plan = chain._normalize_plan(
        json.dumps({"shots": [
            {"id": "one", "prompt": "first", "length": 5, "seed": 1},
            {"id": "two", "prompt": "second", "length": 5, "seed": 2},
        ]}),
        "smoke", 32, 32, 1, "video", "head", "disabled",
        "source_track", 1, 1, 2, 1, 30,
    )
    assert [shot["delivered_frames"] for shot in plan["shots"]] == [5, 4]

    observed = {}

    class SmokePlan:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}

        RETURN_TYPES = (chain.PLAN_TYPE,)
        FUNCTION = "make"

        def make(self):
            return (before_plan,)

    class SmokeBody:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"state": (chain.STATE_TYPE,)}}

        RETURN_TYPES = ("IMAGE", "LATENT", chain.SEGMENT_TYPE)
        FUNCTION = "render"

        def render(self, state):
            shot = state["plan"]["shots"][state["index"] - 1]
            images = torch.zeros(
                (shot["delivered_frames"], 32, 32, 3), dtype=torch.float32)
            segment = {"index": state["index"], "id": shot["id"]}
            return (images, av_latent(), segment)

    class SmokeSink:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"manifest": (chain.MANIFEST_TYPE,)}}

        RETURN_TYPES = ("STRING",)
        FUNCTION = "take"
        OUTPUT_NODE = True

        def take(self, manifest):
            observed["manifest"] = manifest
            return ("ok",)

    class SmokeServer:
        client_id = None
        last_node_id = None

        def send_sync(self, *args, **kwargs):
            pass

    runtime_nodes = dict(package.NODE_CLASS_MAPPINGS)
    runtime_nodes.update({
        "H3ChainSmokePlan": SmokePlan,
        "H3ChainSmokeBody": SmokeBody,
        "H3ChainSmokeSink": SmokeSink,
    })
    previous_nodes = {name: comfy_nodes.NODE_CLASS_MAPPINGS.get(name)
                      for name in runtime_nodes}
    comfy_nodes.NODE_CLASS_MAPPINGS.update(runtime_nodes)
    try:
        prompt = {
            "1": {"class_type": "H3ChainSmokePlan", "inputs": {}},
            "2": {"class_type": "MiniMaxH3ChainLoopStart", "inputs": {
                "plan": ["1", 0], "start_clip": 1,
            }},
            "3": {"class_type": "H3ChainSmokeBody", "inputs": {
                "state": ["2", 1],
            }},
            "4": {"class_type": "MiniMaxH3ChainLoopEnd", "inputs": {
                "flow": ["2", 0], "state": ["2", 1],
                "images": ["3", 0], "sampled_latent": ["3", 1],
                "segment": ["3", 2],
            }},
            "5": {"class_type": "H3ChainSmokeSink", "inputs": {
                "manifest": ["4", 0],
            }},
        }
        executor = execution.PromptExecutor(
            SmokeServer(),
            cache_type=execution.CacheType.CLASSIC,
            cache_args={"ram": 0, "ram_inactive": 0},
        )
        executor.execute(prompt, "h3-chain-recursion-smoke", execute_outputs=["5"])
        assert executor.success
        assert observed["manifest"]["clip_count"] == 4
        assert len(observed["manifest"]["segments"]) == 4
        print("runtime recursion: real Comfy PromptExecutor completed 4 clips")
    finally:
        for name, previous in previous_nodes.items():
            if previous is None:
                comfy_nodes.NODE_CLASS_MAPPINGS.pop(name, None)
            else:
                comfy_nodes.NODE_CLASS_MAPPINGS[name] = previous

    previous_output = folder_paths.get_output_directory()
    with tempfile.TemporaryDirectory() as tempdir:
        folder_paths.set_output_directory(tempdir)
        try:
            source = audio_for_frames(9)
            changed_source = audio_for_frames(9)
            changed_source["waveform"][..., 0] = 1.0
            prepared_plan = chain._plan_with_source_audio(plan, source)
            started = chain.MiniMaxH3ChainLoopStart().start(plan, 1, source)
            assert started[1]["plan"]["compatibility"]["source_audio_hash"]
            current = chain.MiniMaxH3ChainCurrent().current(started[1], source)
            assert current[1:3] == (1, 2)
            assert current[6:10] == (5, 2, 32, 32)
            assert int(current[12]["waveform"].shape[-1]) == round(5 / 24 * 8000)
            try:
                chain.MiniMaxH3ChainCurrent().current(
                    started[1], changed_source)
            except ValueError as exc:
                assert "different source waveform" in str(exc)
            else:
                raise AssertionError("Current Shot accepted a different source song")
            short_source = audio_for_frames(4)
            try:
                chain.MiniMaxH3ChainLoopStart().start(plan, 1, short_source)
            except ValueError as exc:
                assert "too short" in str(exc)
            else:
                raise AssertionError("Loop Start accepted a short source song")
            conditioning = [["cond", {}]]
            bypass = chain.MiniMaxH3ChainContext().apply(
                started[1], conditioning, None, av_latent())
            assert bypass == (conditioning, 0, False)
            print("current/context: source window exact; clip 1 bypasses context")
            saver = chain.MiniMaxH3ChainSegmentSave()
            generated_state = chain._initial_state(
                chain._plan_with_source_audio(before_plan, None), 1)
            try:
                saver.save(
                    generated_state,
                    torch.zeros((5, 32, 32, 3), dtype=torch.float32),
                    av_latent())
            except ValueError as exc:
                assert "requires decoded audio" in str(exc)
            else:
                raise AssertionError("generated_audio saved without decoded audio")
            try:
                saver.save(
                    generated_state,
                    torch.zeros((5, 32, 32, 3), dtype=torch.float32),
                    av_latent(), audio_for_frames(4))
            except ValueError as exc:
                assert "expected exactly" in str(exc)
            else:
                raise AssertionError("Segment Save accepted mistimed audio")
            state1 = chain._initial_state(prepared_plan, 1)
            images1 = torch.zeros((5, 32, 32, 3), dtype=torch.float32)
            result1 = saver.save(
                state1, images1, av_latent(), audio_for_frames(5))
            segment1 = result1["result"][0]
            assert pathlib.Path(chain._absolute_output_path(
                segment1["segment"])).is_file()

            segment1_path = pathlib.Path(
                chain._absolute_output_path(segment1["segment"]))
            checkpoint1_path = pathlib.Path(
                chain._absolute_output_path(segment1["checkpoint"]))
            before_interruption = (
                segment1_path.read_bytes(), checkpoint1_path.read_bytes())
            real_st_save = chain._st_save

            def interrupted_save(*args, **kwargs):
                raise RuntimeError("simulated interrupted checkpoint write")

            chain._st_save = interrupted_save
            try:
                saver.save(
                    state1, torch.ones_like(images1), av_latent(),
                    audio_for_frames(5))
            except RuntimeError as exc:
                assert "simulated interrupted" in str(exc)
            else:
                raise AssertionError("simulated checkpoint interruption did not fire")
            finally:
                chain._st_save = real_st_save
            assert segment1_path.read_bytes() == before_interruption[0]
            assert checkpoint1_path.read_bytes() == before_interruption[1]
            assert chain._initial_state(prepared_plan, 2)["index"] == 2
            replacement = saver.save(
                state1, images1, av_latent(), audio_for_frames(5))["result"][0]
            assert replacement["segment"] != segment1["segment"]
            assert not segment1_path.exists()
            assert not checkpoint1_path.exists()
            segment1 = replacement
            print("atomic save: interruption preserved old pair; retry switched + cleaned")

            review_item, has_audio, warning = chain._review_video(
                prepared_plan, segment1, audio_for_frames(5))
            review_path = pathlib.Path(
                tempdir, review_item["subfolder"], review_item["filename"])
            assert has_audio and not warning and review_path.is_file()
            streams = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                "-of", "csv=p=0", str(review_path),
            ], text=True).splitlines()
            assert "video" in streams and "audio" in streams
            print("review: persisted segment muxed with frame-exact audio")

            async def approve_live_review():
                sent = []

                class ReviewServerInstance:
                    client_id = "smoke-client"

                    def send_sync(self, event, payload, client_id):
                        sent.append((event, payload, client_id))

                class ReviewServer:
                    instance = ReviewServerInstance()

                original_server = chain.PromptServer
                chain.PromptServer = ReviewServer
                try:
                    task = asyncio.create_task(
                        chain.MiniMaxH3ChainReview().review(
                            state1, segment1, True, False,
                            audio_for_frames(5), unique_id="review-node"))
                    for _ in range(100):
                        if chain._PENDING_REVIEWS:
                            break
                        await asyncio.sleep(0.01)
                    assert chain._PENDING_REVIEWS and sent
                    token = sent[-1][1]["token"]

                    class ApproveRequest:
                        async def json(self):
                            return {"token": token, "action": "approve"}

                    response = await chain._submit_review_decision(
                        ApproveRequest())
                    assert response.status == 200
                    result = await asyncio.wait_for(task, timeout=5.0)
                    assert result["result"][0]["segment"] == segment1["segment"]
                    assert not chain._PENDING_REVIEWS
                finally:
                    chain.PromptServer = original_server

            asyncio.run(approve_live_review())
            print("review: live async gate pauses and resumes on approval")

            revised = chain._plan_with_review_revision(
                prepared_plan, 2, "Revised second scene.", 999)
            assert revised["base_plan_hash"] == prepared_plan["base_plan_hash"]
            assert revised["shots"][1]["prompt"] == "Revised second scene."
            assert revised["shots"][1]["seed"] == 999
            assert (chain._history_hash(revised, 1) ==
                    chain._history_hash(prepared_plan, 1))
            assert (chain._history_hash(revised, 2) !=
                    chain._history_hash(prepared_plan, 2))
            print("review: prompt/seed retry preserves accepted predecessor history")

            fake_prompt = {
                "1": {"class_type": "MiniMaxH3ChainLoopStart", "inputs": {
                    "plan": plan, "start_clip": 1, "source_audio": source,
                }},
                "2": {"class_type": "MiniMaxH3ChainCurrent", "inputs": {
                    "state": ["1", 1],
                }},
                "3": {"class_type": "MiniMaxH3ChainSegmentSave", "inputs": {
                    "state": ["2", 0],
                }},
                "4": {"class_type": "MiniMaxH3ChainLoopEnd", "inputs": {
                    "flow": ["1", 0], "state": ["2", 0],
                    "images": ["3", 0], "sampled_latent": ["3", 0],
                    "segment": ["3", 0],
                }},
            }
            expanded = chain.MiniMaxH3ChainLoopEnd().end(
                ["1", 0], state1, images1, av_latent(), segment1,
                dynprompt=FakeDynamicPrompt(fake_prompt), unique_id="4")
            assert isinstance(expanded, dict) and expanded.get("expand")
            cloned_starts = [node for node in expanded["expand"].values()
                             if node["class_type"] == "MiniMaxH3ChainLoopStart"]
            assert len(cloned_starts) == 1
            assert cloned_starts[0]["inputs"]["initial_state"]["index"] == 2
            assert all(isinstance(link, list) for link in expanded["result"])
            print("recursion: GraphBuilder cloned the typed H3 body for clip 2")

            retry_segment = dict(segment1)
            retry_segment["_h3_review_decision"] = {
                "action": "retry",
                "scene_prompt": "Try the opening again.",
                "seed": 1234,
            }
            retried = chain.MiniMaxH3ChainLoopEnd().end(
                ["1", 0], state1, images1, av_latent(), retry_segment,
                dynprompt=FakeDynamicPrompt(fake_prompt), unique_id="4")
            retried_starts = [
                node for node in retried["expand"].values()
                if node["class_type"] == "MiniMaxH3ChainLoopStart"
            ]
            retry_state = retried_starts[0]["inputs"]["initial_state"]
            assert retry_state["index"] == 1
            assert retry_state["segments"] == []
            assert retry_state["plan"]["shots"][0]["seed"] == 1234
            assert retry_state["plan"]["shots"][0]["prompt"] == "Try the opening again."
            print("review: rejected clip recurses at the same index")

            state2 = chain._initial_state(prepared_plan, 2)
            assert state2["resumed_from"] == 1
            assert len(state2["segments"]) == 1
            assert tuple(state2["previous_frames"].shape) == (1, 32, 32, 3)
            assert len(state2["previous_latent"]["samples"]) == 2
            print("resume: clip 2 restored clip 1 frame tail + AV latent")

            images2 = torch.zeros((4, 32, 32, 3), dtype=torch.float32)
            result2 = saver.save(
                state2, images2, av_latent(), audio_for_frames(4))
            segment2 = result2["result"][0]
            complete = dict(state2)
            complete["segments"] = state2["segments"] + [segment2]
            manifest = chain._manifest_from_state(complete)

            loaded_manifest = chain.MiniMaxH3ChainManifestLoad().load(
                plan, source)[0]
            assert loaded_manifest["plan_hash"] == manifest["plan_hash"]
            assert len(loaded_manifest["segments"]) == 2
            assert pathlib.Path(tempdir, "h3_chains", "smoke",
                                "manifest.json").is_file()
            manifest = loaded_manifest
            print("manifest load: completed chain restored without rerender")

            assembler = chain.MiniMaxH3ChainAssemble()
            source_result = assembler.assemble(
                manifest, "source", "source_final", 96, source)
            source_path = pathlib.Path(source_result["result"][0])
            assert source_path.is_file() and source_path.stat().st_size > 0
            duration = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(source_path),
            ], text=True).strip())
            assert abs(duration - 9 / 24) < 0.05
            try:
                assembler.assemble(
                    manifest, "source", "wrong_source", 96, changed_source)
            except ValueError as exc:
                assert "different source waveform" in str(exc)
            else:
                raise AssertionError("Assemble accepted a different source song")

            generated_result = assembler.assemble(
                manifest, "generated", "generated_final", 96)
            generated_path = pathlib.Path(generated_result["result"][0])
            assert generated_path.is_file() and generated_path.stat().st_size > 0
            print("segments: H.264 save + source/generated audio assembly pass")

            changed = json.loads(json.dumps({"shots": [
                {"id": "one", "prompt": "changed", "length": 5, "seed": 1},
                {"id": "two", "prompt": "second", "length": 5, "seed": 2},
            ]}))
            changed_plan = chain._normalize_plan(
                json.dumps(changed), "smoke", 32, 32, 1, "video", "head",
                "disabled", "source_track", 1, 1, 2, 1, 30)
            try:
                chain._initial_state(
                    chain._plan_with_source_audio(changed_plan, source), 2)
            except ValueError as exc:
                assert "different settings, prompts, seeds, or durations" in str(exc)
            else:
                raise AssertionError("resume accepted a changed predecessor")
            print("resume guard: changed predecessor rejected")

            changed_generation_plan = chain._normalize_plan(
                json.dumps({"shots": [
                    {"id": "one", "prompt": "first", "length": 5, "seed": 1},
                    {"id": "two", "prompt": "second", "length": 5, "seed": 2},
                ]}),
                "smoke", 32, 32, 1, "video", "head", "disabled",
                "source_track", 1, 1, 2, 1, 30, "model-and-refs-v2")
            try:
                chain._initial_state(chain._plan_with_source_audio(
                    changed_generation_plan, source), 2)
            except ValueError as exc:
                assert "different settings" in str(exc)
            else:
                raise AssertionError(
                    "resume accepted a changed generation fingerprint")
            print("resume guard: external generation fingerprint enforced")

            try:
                chain._initial_state(
                    chain._plan_with_source_audio(plan, changed_source), 2)
            except ValueError as exc:
                assert "different settings, prompts, seeds, or durations" in str(exc)
            else:
                raise AssertionError("resume accepted changed source audio")
            print("resume guard: changed source track rejected")
        finally:
            folder_paths.set_output_directory(previous_output)

    print("chain smoke test passed")


if __name__ == "__main__":
    main()
