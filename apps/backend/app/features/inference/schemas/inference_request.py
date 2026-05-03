"""InferenceRequest wire schema — public POST body for the inference endpoint."""

from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams

# Per-string cap for metadata values: bounds payload size symmetrically with
# Message string-content limits and prevents `{"x": "<10MiB string>"}`-style
# memory amplification on the LAN-trusted-but-not-infallible consumer path.
# The validator walks nested lists/dicts so a consumer cannot bypass the cap
# by wrapping a long string in a one-element list or a single-key dict.
_METADATA_VALUE_MAX_LENGTH: Final[int] = 4096


def _bounded_strings_in_metadata(value: JsonValue, key_path: str) -> None:
    """Recursively assert every str leaf is within the per-string cap.

    Walks dict values and list elements so the cap holds against deeply
    nested shapes. Raises ``ValueError`` with a key_path that points the
    operator at the offending leaf.
    """
    if isinstance(value, str):
        if len(value) > _METADATA_VALUE_MAX_LENGTH:
            msg = (
                f"metadata[{key_path}] string value exceeds the "
                f"{_METADATA_VALUE_MAX_LENGTH}-character cap."
            )
            raise ValueError(msg)
        return
    if isinstance(value, list):
        for index, element in enumerate(value):
            _bounded_strings_in_metadata(element, f"{key_path}[{index}]")
        return
    if isinstance(value, dict):
        for inner_key, inner_value in value.items():
            _bounded_strings_in_metadata(inner_value, f"{key_path}.{inner_key}")
        return
    # Other JsonValue branches (int, float, bool, None) are unbounded by
    # type — no per-leaf cap to enforce. The ``max_length`` on the outer
    # dict bounds the key count.


class InferenceRequest(BaseModel):
    """Request envelope accepted by the inference endpoint.

    `model` is a logical name the registry resolves to a concrete
    backend tag — never a backend-specific tag itself. `metadata` is a
    pass-through for future per-project attribution; structural bounds
    (key count + per-value length, recursive) are enforced, content
    semantics are opaque.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    messages: list[Message] = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    params: ModelParams = Field(default_factory=ModelParams)
    # ``JsonValue`` is Pydantic's recursive JSON-primitive type
    # (str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]).
    # Tightens the wire contract from ``dict[str, Any]`` so a consumer cannot
    # ship a non-JSON value (e.g. a datetime) that would deserialize fine on
    # input and fail downstream at JSON encoding.
    metadata: dict[str, JsonValue] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def _bound_metadata_values(self) -> Self:
        for key, value in self.metadata.items():
            _bounded_strings_in_metadata(value, repr(key))
        return self
