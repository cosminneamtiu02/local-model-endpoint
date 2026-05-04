"""Unit tests for ModelParams (LIP-E001-F001).

The exhaustive boundary scenarios are inherited from the LIP-E001-F001
spec. ``exclude_unset`` semantics are core to the merge logic the
service-layer feature (LIP-E001-F002) will build on top.
"""

import pytest
from pydantic import ValidationError

from app.features.inference.model.model_params import ModelParams


def test_model_params_default_construction_has_all_none_sampling_fields() -> None:
    params = ModelParams()
    assert params.temperature is None
    assert params.top_p is None
    assert params.top_k is None
    assert params.max_tokens is None
    assert params.stop is None
    assert params.seed is None
    assert params.think is False


def test_model_params_default_construction_dumps_empty_when_exclude_unset() -> None:
    params = ModelParams()
    assert params.model_dump(exclude_unset=True) == {}


def test_model_params_explicit_none_is_dumped_when_exclude_unset() -> None:
    params = ModelParams(temperature=None)
    assert params.model_dump(exclude_unset=True) == {"temperature": None}


@pytest.mark.parametrize(
    "temperature",
    [
        pytest.param(0.0, id="lower-bound-inclusive"),
        pytest.param(1.0, id="midrange"),
        pytest.param(2.0, id="upper-bound-inclusive"),
    ],
)
def test_model_params_temperature_accepts_values_in_range(temperature: float) -> None:
    params = ModelParams(temperature=temperature)
    assert params.temperature == temperature


@pytest.mark.parametrize(
    "temperature",
    [
        pytest.param(-0.1, id="below-lower-bound"),
        pytest.param(2.5, id="above-upper-bound"),
    ],
)
def test_model_params_temperature_rejects_values_out_of_range(temperature: float) -> None:
    with pytest.raises(ValidationError):
        ModelParams(temperature=temperature)


@pytest.mark.parametrize(
    "top_p",
    [
        pytest.param(0.001, id="just-above-zero"),
        pytest.param(0.95, id="midrange"),
        pytest.param(1.0, id="upper-bound-inclusive"),
    ],
)
def test_model_params_top_p_accepts_values_in_range(top_p: float) -> None:
    params = ModelParams(top_p=top_p)
    assert params.top_p == top_p


@pytest.mark.parametrize(
    "top_p",
    [
        pytest.param(0.0, id="zero-excluded"),
        pytest.param(1.5, id="above-upper-bound"),
    ],
)
def test_model_params_top_p_rejects_values_out_of_range(top_p: float) -> None:
    with pytest.raises(ValidationError):
        ModelParams(top_p=top_p)


@pytest.mark.parametrize(
    "top_k",
    [
        pytest.param(1, id="lower-bound-just-above-zero"),
        pytest.param(40, id="midrange"),
    ],
)
def test_model_params_top_k_accepts_values_in_range(top_k: int) -> None:
    params = ModelParams(top_k=top_k)
    assert params.top_k == top_k


@pytest.mark.parametrize(
    "top_k",
    [
        pytest.param(0, id="zero-excluded"),
        pytest.param(-1, id="negative"),
    ],
)
def test_model_params_top_k_rejects_values_out_of_range(top_k: int) -> None:
    with pytest.raises(ValidationError):
        ModelParams(top_k=top_k)


@pytest.mark.parametrize(
    "max_tokens",
    [
        pytest.param(1, id="lower-bound-just-above-zero"),
        pytest.param(512, id="midrange"),
    ],
)
def test_model_params_max_tokens_accepts_values_in_range(max_tokens: int) -> None:
    params = ModelParams(max_tokens=max_tokens)
    assert params.max_tokens == max_tokens


@pytest.mark.parametrize(
    "max_tokens",
    [
        pytest.param(0, id="zero-excluded"),
        pytest.param(-1, id="negative"),
    ],
)
def test_model_params_max_tokens_rejects_values_out_of_range(max_tokens: int) -> None:
    with pytest.raises(ValidationError):
        ModelParams(max_tokens=max_tokens)


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(0, id="zero-included"),
        pytest.param(42, id="midrange"),
        pytest.param(2**32 - 1, id="uint32-ceiling-included"),
    ],
)
def test_model_params_seed_accepts_values_in_range(seed: int) -> None:
    params = ModelParams(seed=seed)
    assert params.seed == seed


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(-1, id="negative-excluded"),
        # Above the uint32 ceiling Ollama / llama.cpp accept; left
        # unbounded the consumer's seed would silently mod-truncate
        # inside the backend, breaking the determinism contract the
        # field's description promises.
        pytest.param(2**32, id="uint32-overflow-rejected"),
    ],
)
def test_model_params_seed_rejects_out_of_range_values(seed: int) -> None:
    with pytest.raises(ValidationError):
        ModelParams(seed=seed)


def test_model_params_stop_accepts_list_of_strings() -> None:
    params = ModelParams(stop=["</end>", "STOP"])
    assert params.stop == ["</end>", "STOP"]


def test_model_params_think_can_be_set_true() -> None:
    params = ModelParams(think=True)
    assert params.think is True


def test_model_params_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError, match="extra"):
        ModelParams.model_validate({"temperature": 0.5, "bogus": 1})
