#!/usr/bin/env python3
"""Focused CPU tests for sigma-matched H3 Guide late reveal."""

import copy
import importlib.util
import pathlib
import sys
import types

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_NAME = "h3_visual_context_schedule_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package

spec = importlib.util.spec_from_file_location(
    PACKAGE_NAME + ".visual_context_schedule",
    ROOT / "visual_context_schedule.py",
)
schedule = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = schedule
spec.loader.exec_module(schedule)


assert schedule.scheduled_visual_condition_aug(1.0) == 0.0
assert schedule.scheduled_visual_condition_aug(0.75) == 0.25
assert schedule.scheduled_visual_condition_aug(0.5) == 0.5
assert schedule.scheduled_visual_condition_aug(0.0) == 0.999
assert schedule.scheduled_visual_condition_aug(0.95, 0.1, 0.999) == 0.1
assert schedule.scheduled_visual_condition_aug(0.0, 0.0, 1.0) == 1.0

full_sigmas = torch.tensor([1.0, 0.995633, 0.990826, 0.0])
assert abs(schedule.next_schedule_sigma(1.0, full_sigmas) - 0.995633) < 1e-6
assert abs(schedule.next_schedule_sigma(
    0.995633, full_sigmas) - 0.990826) < 1e-6
assert abs(schedule.next_schedule_sigma(0.993, full_sigmas) - 0.990826) < 1e-6
assert schedule.next_schedule_sigma(0.0, full_sigmas) == 0.0
next_runtime = schedule._VisualContextScheduleState(
    0.0, 0.999, mode="next_step", full_sigmas=full_sigmas)
assert abs(next_runtime.aug_for_sigma(1.0) - 0.004367) < 1e-6
assert abs(next_runtime.aug_for_sigma(0.990826) - 0.999) < 1e-6
assert next_runtime.last_basis_sigma == 0.0
assert next_runtime.endpoint_aug_summary() == (
    "3 calls: [0.004, 0.009, 0.999]")

assert schedule.parse_manual_schedule("0, .25;\n1") == (0.0, 0.25, 1.0)
for invalid_manual in ("", "0, nope", "-0.1", "1.1", "nan", [False]):
    try:
        schedule.parse_manual_schedule(invalid_manual)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "invalid manual schedule was accepted: %r" % invalid_manual)

manual_sigmas = torch.tensor([1.0, 0.9, 0.8, 0.7, 0.0])
assert schedule.schedule_step_index(1.0, manual_sigmas) == 0
assert schedule.schedule_step_index(0.95, manual_sigmas) == 0
assert schedule.schedule_step_index(0.9, manual_sigmas) == 1
assert schedule.schedule_step_index(0.85, manual_sigmas) == 1
assert schedule.schedule_step_index(0.0, manual_sigmas) == 3
manual_runtime = schedule._VisualContextScheduleState(
    0.0,
    0.999,
    mode="manual",
    full_sigmas=manual_sigmas,
    manual_schedule="0, 0.999",
)
assert manual_runtime.aug_for_sigma(1.0) == 0.0
assert manual_runtime.aug_for_sigma(0.95) == 0.0
assert manual_runtime.aug_for_sigma(0.9) == 0.999
assert manual_runtime.aug_for_sigma(0.85) == 0.999
assert manual_runtime.aug_for_sigma(0.7) == 0.999
assert manual_runtime.endpoint_aug_summary() == (
    "manual values [0.000, 0.999] over 4 sampler steps; final value "
    "holds after entry 2")

for manual_kwargs in (
    {"full_sigmas": None, "manual_schedule": "0, 0.999"},
    {"full_sigmas": manual_sigmas, "manual_schedule": ""},
    {"full_sigmas": manual_sigmas, "manual_schedule": "0, .2, .4, .6, .8"},
):
    try:
        schedule._VisualContextScheduleState(
            0.0, 0.999, mode="manual", **manual_kwargs)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "manual mode accepted incomplete configuration: %r"
            % manual_kwargs)

# Both sides of a model/sigma split resolve the same absolute manual index.
manual_values = "0, .2, .4, .6"
manual_high = schedule._VisualContextScheduleState(
    0.0, 0.999, mode="manual", full_sigmas=manual_sigmas,
    manual_schedule=manual_values)
manual_low = schedule._VisualContextScheduleState(
    0.0, 0.999, mode="manual", full_sigmas=manual_sigmas,
    manual_schedule=manual_values)
assert manual_high.aug_for_sigma(0.8) == 0.4
assert manual_low.aug_for_sigma(0.7) == 0.6

# Separate model objects on opposite sides of a sigma split resolve against
# the same unsplit schedule instead of restarting their local progress.
split_schedule = torch.tensor([1.0, 0.9, 0.8, 0.7, 0.0])
high_branch = schedule._VisualContextScheduleState(
    0.0, 0.999, mode="next_step", full_sigmas=split_schedule)
low_branch = schedule._VisualContextScheduleState(
    0.0, 0.999, mode="next_step", full_sigmas=split_schedule)
assert abs(high_branch.aug_for_sigma(0.8) - 0.3) < 1e-6
assert abs(low_branch.aug_for_sigma(0.7) - 0.999) < 1e-6

try:
    schedule._VisualContextScheduleState(0.0, 0.999, mode="next_step")
except ValueError as exc:
    assert "full_sigmas" in str(exc)
else:
    raise AssertionError("next_step accepted no full schedule")

for args in (
    (float("nan"), 0.0, 0.999),
    (1.0, -0.1, 0.999),
    (1.0, 0.0, 1.1),
    (1.0, 0.8, 0.2),
):
    try:
        schedule.scheduled_visual_condition_aug(*args)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid schedule arguments were accepted")


def chain_state(index, mode="guide", context_length=22, external=False):
    return {
        "index": index,
        "external_context": external,
        "plan": {
            "compatibility": {
                "continuation_mode": "guide",
                "context_length": 22,
            },
            "shots": [
                {"continuation_mode": mode,
                 "context_length": context_length}
                for _ in range(max(1, index))
            ],
        },
    }


assert schedule._active_guide_context(chain_state(1)) is False
assert schedule._active_guide_context(chain_state(1, external=True)) is True
assert schedule._active_guide_context(chain_state(2)) is True
assert schedule._active_guide_context(chain_state(2, mode="latent_guide"))
assert not schedule._active_guide_context(
    chain_state(2, mode="drift_control_av", context_length=39))
assert not schedule._active_guide_context(chain_state(2, context_length=0))


# ComfyUI packs visual conditions as keyframe latents first, then reference
# latents. Only Chain Context-marked keyframes receive the dynamic value.
selective_payload = {
    "keyframes": [
        {"latent": torch.tensor(1), "h3_chain_context_visual": True},
        {"audio_latent": torch.tensor(2)},
        {"latent": torch.tensor(3)},
    ],
    "refs": [
        {"kind": "image", "latent": torch.tensor(4)},
        {"kind": "audio", "audio_latent": torch.tensor(5)},
    ],
    "cond_video_latents": [
        torch.tensor(1), torch.tensor(3), torch.tensor(4),
    ],
    "visual_cond_noise_aug": 0.875,
}
assert schedule._context_visual_flags(selective_payload) == [
    True, False, False]
assert schedule._selective_visual_augs(
    selective_payload, 0.004, 0.999) == [0.004, 0.875, 0.875]

# Dynamic calls must traverse one coherent forward-noise trajectory. H3
# restarts the same seeded CPU generator for a condition on every call; it
# must not redraw unrelated noise as the clean fraction changes.
trajectory_h3m = types.SimpleNamespace(
    patchify_video=lambda value, _patch: value.reshape(-1, 2))
trajectory_owner = types.SimpleNamespace(patch_size=(1, 1, 1))
trajectory_latent = torch.arange(8, dtype=torch.float32).reshape(
    1, 2, 1, 2, 2)
trajectory_payload = {
    "cond_video_latents": [trajectory_latent],
    "seed": 1234,
}
trajectory_clean = trajectory_h3m.patchify_video(
    trajectory_latent, trajectory_owner.patch_size)
trajectory_early = schedule._condition_rows_with_augs(
    trajectory_owner, trajectory_h3m, trajectory_payload, "cpu", [0.004])
trajectory_late = schedule._condition_rows_with_augs(
    trajectory_owner, trajectory_h3m, trajectory_payload, "cpu", [0.5])
early_noise = (
    trajectory_early - 0.004 * trajectory_clean) / (1.0 - 0.004)
late_noise = (trajectory_late - 0.5 * trajectory_clean) / (1.0 - 0.5)
assert torch.allclose(early_noise, late_noise, atol=2e-6, rtol=2e-6)
stock_generator = torch.Generator("cpu").manual_seed(1234)
stock_row_noise = torch.randn(
    trajectory_clean.shape,
    generator=stock_generator,
    dtype=torch.float32,
)
assert torch.equal(
    trajectory_early,
    0.004 * trajectory_clean + (1.0 - 0.004) * stock_row_noise,
)
assert torch.allclose(early_noise, stock_row_noise, atol=2e-6, rtol=2e-6)

# Public H3 ports construct seeded visual noise in latent space with temporal
# length target_T + number_of_visual_conditions, slice the condition prefix,
# and only then patchify. The alternate backend applies that construction only
# to marked recursive context; ordinary references remain byte-identical to
# current ComfyUI's packed-row noise.
def tiny_patchify(value, _patch):
    return value.permute(0, 2, 3, 4, 1).reshape(-1, value.shape[1])


official_h3m = types.SimpleNamespace(patchify_video=tiny_patchify)
official_owner = types.SimpleNamespace(patch_size=(1, 1, 1))
official_context = torch.arange(16, dtype=torch.float32).reshape(
    1, 2, 2, 2, 2)
ordinary_reference = official_context + 20.0
official_payload = {
    "cond_video_latents": [official_context, ordinary_reference],
    "seed": 41,
}
dependent_rows = schedule._condition_rows_with_augs(
    official_owner,
    official_h3m,
    official_payload,
    "cpu",
    [0.0, 0.0],
    context_flags=[True, False],
    target_latent_t=3,
    noise_backend="dependent_latent",
)
latent_generator = torch.Generator("cpu").manual_seed(41)
full_latent_noise = torch.randn(
    1, 2, 5, 2, 2,
    generator=latent_generator,
    dtype=torch.float32,
)
expected_context_noise = tiny_patchify(
    full_latent_noise[:, :, :2], official_owner.patch_size)
row_generator = torch.Generator("cpu").manual_seed(41)
ordinary_clean_rows = tiny_patchify(
    ordinary_reference, official_owner.patch_size)
expected_ordinary_noise = torch.randn(
    ordinary_clean_rows.shape,
    generator=row_generator,
    dtype=torch.float32,
)
context_row_count = expected_context_noise.shape[0]
assert torch.equal(
    dependent_rows[:context_row_count], expected_context_noise)
assert torch.equal(
    dependent_rows[context_row_count:], expected_ordinary_noise)
assert not torch.equal(expected_context_noise, expected_ordinary_noise)

# The official backend also reuses the exact same latent-space draw across
# schedule calls, so changing the clean fraction remains one coherent path.
dependent_half = schedule._condition_rows_with_augs(
    official_owner,
    official_h3m,
    official_payload,
    "cpu",
    [0.5, 1.0],
    context_flags=[True, False],
    target_latent_t=3,
    noise_backend="dependent_latent",
)
official_clean_rows = tiny_patchify(
    official_context, official_owner.patch_size)
recovered_dependent_noise = (
    dependent_half[:context_row_count] - 0.5 * official_clean_rows
) / 0.5
assert torch.equal(
    dependent_half[:context_row_count],
    0.5 * official_clean_rows + 0.5 * expected_context_noise,
)
assert torch.allclose(
    recovered_dependent_noise, expected_context_noise,
    atol=2e-6, rtol=2e-6)

bad_payload = copy.copy(selective_payload)
bad_payload["cond_video_latents"] = bad_payload["cond_video_latents"][:-1]
try:
    schedule._context_visual_flags(bad_payload)
except RuntimeError as exc:
    assert "payload order changed" in str(exc)
else:
    raise AssertionError("visual payload/layout mismatch was accepted")


class FakeLayout:
    segments = [
        (0, 2, "text"),
        (2, 4, "cond"),
        (4, 6, "cond_audio"),
        (6, 8, "ref_img"),
        (8, 10, "ref_audio"),
        (10, 12, "audio"),
        (12, 14, "video"),
    ]


assert schedule._segment_timestep_plan(
    FakeLayout(), 0.1, 0.2, [0.1, 0.999], 1.0) == [
        0.1, 0.1, 1.0, 0.999, 1.0, 0.2, 0.1]


runtime = schedule._VisualContextScheduleState(0.0, 0.999)
original_payload = {
    "cond_video_latents": [torch.ones((1, 24, 1, 2, 2))],
    "visual_cond_noise_aug": 0.999,
    "seed": 17,
}
captured = {}


def executor(*args, **kwargs):
    captured.update(kwargs)
    return "ok"


assert runtime.diffusion_model_wrapper(
    executor,
    "x",
    torch.tensor([996.0]),
    "context",
    transformer_options={"sample_sigmas": torch.tensor([1.0, 0.0])},
    minimax_payload=original_payload,
) == "ok"
patched_payload = captured["minimax_payload"]
assert patched_payload is not original_payload
assert abs(patched_payload["visual_cond_noise_aug"] - 0.004) < 1e-6
assert original_payload["visual_cond_noise_aug"] == 0.999
assert patched_payload["cond_video_latents"] is original_payload[
    "cond_video_latents"]
assert runtime.model_calls == 1

# No visual rows: payload identity and schedule state stay unchanged.
captured.clear()
audio_payload = {"cond_audio_latents": [torch.ones((1, 8, 4))]}
assert runtime.diffusion_model_wrapper(
    executor,
    "x",
    torch.tensor([500.0]),
    "context",
    transformer_options={},
    minimax_payload=audio_payload,
) == "ok"
assert captured["minimax_payload"] is audio_payload
assert runtime.model_calls == 1


class ModelType:
    name = "FLOW_AV"


class InnerModel:
    model_type = ModelType()


class FakeModel:
    def __init__(self):
        self.model = InnerModel()
        self.model_options = {"transformer_options": {}}
        self.wrappers = []

    def clone(self):
        cloned = FakeModel()
        cloned.model_options = copy.copy(self.model_options)
        return cloned

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers.append((wrapper_type, key, wrapper))


comfy = types.ModuleType("comfy")
patcher_extension = types.ModuleType("comfy.patcher_extension")


class WrappersMP:
    DIFFUSION_MODEL = "diffusion_model"


patcher_extension.WrappersMP = WrappersMP
comfy.patcher_extension = patcher_extension
sys.modules["comfy"] = comfy
sys.modules["comfy.patcher_extension"] = patcher_extension

source = FakeModel()
patched = schedule.install_visual_context_schedule_model(
    source, 0.0, 0.999, scope="all_visual_conditions")
assert patched is not source
assert len(patched.wrappers) == 1
assert patched.wrappers[0][:2] == (
    "diffusion_model", schedule._WRAPPER_KEY)
assert schedule._MODEL_OPTION_MARKER in patched.model_options
assert schedule._STATE_MARKER in patched.model_options
assert schedule._MODEL_OPTION_MARKER not in source.model_options

try:
    schedule.install_visual_context_schedule_model(
        patched, 0.0, 0.999, scope="all_visual_conditions")
except ValueError as exc:
    assert "already installed" in str(exc)
else:
    raise AssertionError("duplicate schedule patch was accepted")


# Selective installation is source-hash gated and object-patches only the H3
# diffusion instance. This synthetic core function carries the same contract
# markers while avoiding a heavyweight ComfyUI import in the CPU unit test.
def synthetic_core_forward(self, *args, **kwargs):
    payload = kwargs.get("minimax_payload") or {}
    layout = payload.get("layout")
    device = "cpu"
    cond_video_rows = self._cond_video_rows(payload, device)
    mod_segments = []
    mask_row_values = None
    self.final_layer
    return ("stock", layout, cond_video_rows, mod_segments, mask_row_values)


h3m = types.ModuleType("comfy.ldm.minimax.model")
synthetic_core_forward.__module__ = h3m.__name__
h3m.__name__ = "comfy.ldm.minimax.model"
h3m.VISUAL_COND_TIMESTEP = 0.999
h3m.AUDIO_COND_TIMESTEP = 1.0
ldm = types.ModuleType("comfy.ldm")
minimax = types.ModuleType("comfy.ldm.minimax")
minimax.model = h3m
ldm.minimax = minimax
comfy.ldm = ldm
sys.modules["comfy.ldm"] = ldm
sys.modules["comfy.ldm.minimax"] = minimax
sys.modules["comfy.ldm.minimax.model"] = h3m

synthetic_hash = __import__("hashlib").sha256(
    __import__("inspect").getsource(synthetic_core_forward).encode()
).hexdigest()
schedule._VALIDATED_FORWARD_SHA256S = frozenset((synthetic_hash,))


class Diffusion:
    def __init__(self):
        self._forward = types.MethodType(synthetic_core_forward, self)
        self.final_layer = object()

    def _cond_video_rows(self, _payload, _device):
        return "rows"


class SelectiveInner:
    model_type = ModelType()

    def __init__(self):
        self.diffusion_model = Diffusion()


class SelectiveFakeModel:
    def __init__(self):
        self.model = SelectiveInner()
        self.model_options = {"transformer_options": {}}
        self.object_patches = []
        self.wrappers = []

    def clone(self):
        cloned = SelectiveFakeModel()
        cloned.model_options = copy.copy(self.model_options)
        return cloned

    def get_model_object(self, key):
        assert key == "diffusion_model._forward"
        return self.model.diffusion_model._forward

    def add_object_patch(self, key, value):
        self.object_patches.append((key, value))
        self.model.diffusion_model._forward = value

    def add_wrapper_with_key(self, wrapper_type, key, wrapper):
        self.wrappers.append((wrapper_type, key, wrapper))


selective_source = SelectiveFakeModel()
selective_model = schedule.install_visual_context_schedule_model(
    selective_source, 0.0, 0.999, scope="chain_context_only")
assert len(selective_model.object_patches) == 1
assert selective_model.model_options[
    schedule._MODEL_OPTION_MARKER]["scope"] == "chain_context_only"
selective_forward = selective_model.object_patches[0][1]
assert selective_forward(
    "x", "t", "context", minimax_payload={})[0] == "stock"

selective_capture = {}
original_selective_forward = schedule._selective_context_forward


def capture_selective(*args, **kwargs):
    selective_capture["args"] = args
    selective_capture["kwargs"] = kwargs
    return "selective"


schedule._selective_context_forward = capture_selective
try:
    marked_payload = {
        "keyframes": [{
            "latent": torch.tensor(1),
            "h3_chain_context_visual": True,
        }],
        "cond_video_latents": [torch.tensor(1)],
    }
    assert selective_forward(
        "x", torch.tensor([996.0]), "context",
        minimax_payload=marked_payload) == "selective"
finally:
    schedule._selective_context_forward = original_selective_forward
assert selective_capture["args"][1] is h3m
runtime = selective_model.model_options[schedule._STATE_MARKER]
assert abs(runtime.last_sigma - 0.996) < 1e-6
assert abs(runtime.last_aug - 0.004) < 1e-6


# A future ComfyUI core that consumes per-condition augmentation values in
# both row construction and timestep assignment uses only the public wrapper;
# no copied/object-patched _forward is installed.
def synthetic_native_forward(self, *args, **kwargs):
    payload = kwargs.get("minimax_payload") or {}
    visual_cond_noise_augs = payload.get("visual_cond_noise_augs")
    return ("native", visual_cond_noise_augs)


synthetic_native_forward.__module__ = h3m.__name__


class NativeDiffusion:
    def __init__(self):
        self._forward = types.MethodType(synthetic_native_forward, self)

    def _cond_video_rows(self, payload, _device):
        return payload.get("visual_cond_noise_augs")


class NativeInner:
    model_type = ModelType()

    def __init__(self):
        self.diffusion_model = NativeDiffusion()


class NativeFakeModel(SelectiveFakeModel):
    def __init__(self):
        self.model = NativeInner()
        self.model_options = {"transformer_options": {}}
        self.object_patches = []
        self.wrappers = []

    def clone(self):
        cloned = NativeFakeModel()
        cloned.model_options = copy.copy(self.model_options)
        return cloned


native_model = schedule.install_visual_context_schedule_model(
    NativeFakeModel(), 0.0, 0.999, scope="chain_context_only")
assert native_model.object_patches == []
assert len(native_model.wrappers) == 1
assert native_model.model_options[
    schedule._MODEL_OPTION_MARKER]["backend"] == "core_per_condition"
native_wrapper = native_model.wrappers[0][2]
native_capture = {}


def native_executor(*args, **kwargs):
    native_capture.update(kwargs)
    return "native-wrapper"


native_payload = copy.copy(selective_payload)
native_payload["visual_cond_noise_augs"] = [0.9, 0.8, 0.7]
assert native_wrapper(
    native_executor,
    "x",
    torch.tensor([996.0]),
    "context",
    transformer_options={},
    minimax_payload=native_payload,
) == "native-wrapper"
native_augs = native_capture["minimax_payload"]["visual_cond_noise_augs"]
assert abs(native_augs[0] - 0.004) < 1e-6
assert native_augs[1:] == [0.8, 0.7]
assert native_payload["visual_cond_noise_augs"] == [0.9, 0.8, 0.7]

bad_native_payload = copy.copy(native_payload)
bad_native_payload["visual_cond_noise_augs"] = [0.9]
try:
    native_wrapper(
        native_executor,
        "x",
        torch.tensor([996.0]),
        "context",
        transformer_options={},
        minimax_payload=bad_native_payload,
    )
except RuntimeError as exc:
    assert "strengths for 3 condition blocks" in str(exc)
else:
    raise AssertionError("native per-condition length mismatch was accepted")


# The proposed compact core implementation centralizes list resolution in a
# helper and advertises an explicit capability marker. Detect both consumers
# as well as the payload read in the helper before trusting that contract.
def helper_native_forward(self, *args, **kwargs):
    payload = kwargs.get("minimax_payload") or {}
    visual_augs = self._visual_cond_noise_augs(payload)
    return visual_augs


class HelperNativeDiffusion:
    def _visual_cond_noise_augs(self, payload):
        return payload.get("visual_cond_noise_augs")

    def _cond_video_rows(self, payload, _device):
        return self._visual_cond_noise_augs(payload)


h3m.PER_CONDITION_VISUAL_COND_NOISE_AUGS = 1
try:
    assert schedule._core_supports_per_condition_visual_augs(
        h3m,
        HelperNativeDiffusion(),
        __import__("inspect").getsource(helper_native_forward),
    )
finally:
    del h3m.PER_CONDITION_VISUAL_COND_NOISE_AUGS

# A changed core must fail closed instead of running a stale copied forward.
validated_hashes = schedule._VALIDATED_FORWARD_SHA256S
schedule._VALIDATED_FORWARD_SHA256S = frozenset(("not-the-current-core",))
try:
    schedule.install_visual_context_schedule_model(
        SelectiveFakeModel(), 0.0, 0.999, scope="chain_context_only")
except RuntimeError as exc:
    assert "changed MiniMax H3 _forward" in str(exc)
else:
    raise AssertionError("unknown ComfyUI H3 core was accepted")
finally:
    schedule._VALIDATED_FORWARD_SHA256S = validated_hashes


# Exercise the complete selective forward on a tiny synthetic packed layout.
# This proves that the context segment receives the target-matched timestep
# while an authored keyframe and Ref2VA image retain the stock 0.999 label.
class TinyLayout:
    signature = (1, 1, 1, 1, 1)
    segments = [
        (0, 1, "text"),
        (1, 2, "cond"),
        (2, 3, "cond"),
        (3, 4, "ref_img"),
        (4, 6, "audio"),
        (6, 7, "video"),
    ]
    seq_len = 7
    position_ids = torch.zeros((7, 3), dtype=torch.float64)
    img_update = torch.tensor([False, False, False, True])
    audio_update = torch.tensor([True, True])


class IdentityProjection:
    def __call__(self, value):
        return value


class CaptureBlock:
    def __init__(self):
        self.mod_segments = None

    def __call__(self, hidden, _t_emb, mod_segments, _rope_freqs,
                 transformer_options=None):
        self.mod_segments = mod_segments
        return hidden


class TinyFinal:
    def __call__(self, hidden, _t_emb, video_segment, audio_segment):
        va, vb, _vr = video_segment
        aa, ab, _ar = audio_segment
        return hidden[va:vb], hidden[aa:ab]


class TinyModel:
    patch_size = (1, 1, 1)
    sigma_shift_video = 1.0
    sigma_shift_audio = 1.0
    hidden_size = 2
    latents_dim = 2
    use_adaln_curves = False

    def __init__(self):
        self.video_patch_proj = IdentityProjection()
        self.audio_patch_proj = IdentityProjection()
        self.condition_proj = IdentityProjection()
        self.token_refiner = IdentityProjection()
        self.blocks = [CaptureBlock()]
        self.final_layer = TinyFinal()

    def _cond_audio_rows(self, _payload, _device):
        return None

    def time_embedder(self, values):
        return values[:, None]

    def rope_freqs(self, position_ids, _device):
        return position_ids


class CommonDit:
    @staticmethod
    def pad_to_patch_size(value, _patch_size):
        return value


class ModelManagement:
    @staticmethod
    def cast_to(value, device=None):
        return value.to(device)


class ModelPrefetch:
    @staticmethod
    def make_prefetch_queue(_blocks, _device, _options):
        return None

    @staticmethod
    def prefetch_queue_pop(_queue, _device, _block):
        return None


tiny_h3m = types.SimpleNamespace(
    VISUAL_COND_TIMESTEP=0.999,
    AUDIO_COND_TIMESTEP=1.0,
    comfy=types.SimpleNamespace(
        ldm=types.SimpleNamespace(common_dit=CommonDit),
        model_management=ModelManagement,
        model_prefetch=ModelPrefetch,
    ),
    PackedLayout=lambda *_args, **_kwargs: TinyLayout(),
    patchify_video=lambda value, _patch: value.permute(
        0, 2, 3, 4, 1).reshape(-1, value.shape[1]),
    pack_audio=lambda value: value[0].permute(1, 2, 0).reshape(
        -1, value.shape[1]),
    time_shift_sigma=lambda sigma, _from, _to: sigma,
    mask_row_values=lambda *_args: None,
    rope_rotation_table=lambda value, _dtype: value,
    unpatchify_video=lambda rows, _t, _h, _w, channels, _patch:
        rows.reshape(1, 1, 1, 1, channels).permute(0, 4, 1, 2, 3),
    unpack_audio=lambda rows: rows.reshape(2, 1, rows.shape[-1]).permute(
        2, 0, 1).unsqueeze(0),
)

tiny_model = TinyModel()
tiny_runtime = schedule._VisualContextScheduleState(0.0, 0.999)
tiny_payload = {
    "layout": TinyLayout(),
    "keyframes": [
        {"latent": torch.full((1, 2, 1, 1, 1), 2.0),
         "h3_chain_context_visual": True},
        {"latent": torch.full((1, 2, 1, 1, 1), 3.0)},
    ],
    "refs": [{
        "kind": "image",
        "latent": torch.full((1, 2, 1, 1, 1), 4.0),
    }],
    "cond_video_latents": [
        torch.full((1, 2, 1, 1, 1), 2.0),
        torch.full((1, 2, 1, 1, 1), 3.0),
        torch.full((1, 2, 1, 1, 1), 4.0),
    ],
    "visual_cond_noise_aug": 0.999,
    "seed": 7,
}
tiny_result = schedule._selective_context_forward(
    tiny_model,
    tiny_h3m,
    tiny_runtime,
    [
        torch.full((1, 2, 1, 1, 1), 5.0),
        torch.full((1, 2, 2, 1), 6.0),
    ],
    torch.tensor([996.0]),
    torch.zeros((1, 1, 2)),
    minimax_payload=tiny_payload,
)
assert tuple(tiny_result[0].shape) == (1, 2, 1, 1, 1)
assert tuple(tiny_result[1].shape) == (1, 2, 2, 1)
mods = tiny_model.blocks[0].mod_segments
assert [(start, stop) for start, stop, _row in mods] == [
    (0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 7)]
# Two timestep levels: target-matched .004 has row base 0; stock .999 has
# row base 3. Text/audio modality tags add 1/2 respectively.
assert [int(row) for _start, _stop, row in mods] == [1, 0, 3, 3, 2, 0]

node = schedule.MiniMaxH3VisualContextLateRevealModelPatch()
node_inputs = node.INPUT_TYPES()
assert node_inputs["required"]["preset"][0] == [
    "off", "matched", "next_step", "manual", "custom"]
assert node_inputs["required"]["preset"][1]["default"] == "matched"
assert node_inputs["required"]["manual_schedule"][1]["default"] == (
    "0.000, 0.999")
assert node_inputs["required"]["noise_backend"][0] == [
    "comfy_rows", "dependent_latent"]
assert node_inputs["required"]["noise_backend"][1]["default"] == (
    "comfy_rows")
try:
    node.patch(
        source, chain_state(1), "next_step", "chain_context_only",
        "comfy_rows", "0, 0.999", 0.0, 0.999)
except ValueError as exc:
    assert "full_sigmas" in str(exc)
else:
    raise AssertionError("scene 1 did not preflight missing full_sigmas")
try:
    node.patch(
        source, chain_state(1), "manual", "chain_context_only",
        "comfy_rows", "0, 0.999", 0.0, 0.999)
except ValueError as exc:
    assert "full_sigmas" in str(exc)
else:
    raise AssertionError(
        "scene 1 did not preflight manual missing full_sigmas")
assert node.patch(
    source, chain_state(1), "matched", "chain_context_only",
    "comfy_rows", "0, 0.999", 0.0, 0.999)[0] is source
assert node.patch(
    source, chain_state(2, mode="masked_av", context_length=39),
    "matched", "chain_context_only", "comfy_rows",
    "0, 0.999", 0.0, 0.999)[0] is source
assert node.patch(
    source, chain_state(2), "off", "chain_context_only",
    "comfy_rows", "0, 0.999", 0.0, 0.999)[0] is source
assert node.patch(
    source, chain_state(2), "matched", "all_visual_conditions",
    "comfy_rows", "0, 0.999", 0.3, 0.4)[0] is not source

manual_model = node.patch(
    source, chain_state(2), "manual", "all_visual_conditions",
    "comfy_rows", "0, 0.999", 0.0, 0.999,
    full_sigmas=manual_sigmas)[0]
manual_metadata = manual_model.model_options[schedule._MODEL_OPTION_MARKER]
assert manual_metadata["mode"] == "manual"
assert manual_metadata["manual_schedule"] == [0.0, 0.999]
manual_state = manual_model.model_options[schedule._STATE_MARKER]
assert manual_state.aug_for_sigma(1.0) == 0.0
assert manual_state.aug_for_sigma(0.9) == 0.999

try:
    node.patch(
        source, chain_state(2), "matched", "all_visual_conditions",
        "dependent_latent", "0, 0.999", 0.0, 0.999)
except ValueError as exc:
    assert "selective to Chain Context" in str(exc)
else:
    raise AssertionError("dependent latent noise accepted all-visual scope")

print("visual context schedule unit test passed")
