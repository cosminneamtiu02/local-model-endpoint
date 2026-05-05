"""InferenceRequest wire schema — public POST body for the inference endpoint."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.features.inference.model.caps import (
    METADATA_KEY_MAX_LENGTH,
    METADATA_VALUE_MAX_LENGTH,
    MODEL_NAME_MAX_LENGTH,
)
from app.features.inference.model.message import Message
from app.features.inference.model.model_params import ModelParams

# Hoist the bounded-string key alias so the metadata field shape and the
# validator below can both reference one declaration. Mirrors the
# ``StopToken`` alias in ``model_params.py`` — single source of truth for
# parametrized strings used both as a type and as a validator constant.
type MetadataKey = Annotated[str, Field(max_length=METADATA_KEY_MAX_LENGTH)]


def _bounded_strings_in_metadata(value: JsonValue, key_path: str) -> None:
    """Recursively assert every str leaf is within the per-string cap.

    Walks dict values and list elements so the cap holds against deeply
    nested shapes. Raises ``ValueError`` with a key_path that points the
    operator at the offending leaf.
    """
    if isinstance(value, str):
        if len(value) > METADATA_VALUE_MAX_LENGTH:
            msg = (
                f"metadata[{key_path}] string value exceeds the "
                f"{METADATA_VALUE_MAX_LENGTH}-character cap."
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
    (key count, per-key length, and per-value length, recursive) are
    enforced, content semantics are opaque.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    messages: list[Message] = Field(
        min_length=1,
        max_length=64,
        description="Ordered chat messages; first must be system or user.",
    )
    model: str = Field(
        min_length=1,
        max_length=MODEL_NAME_MAX_LENGTH,
        description="Logical model name resolved by the registry to a backend tag.",
    )
    # ``default_factory=ModelParams`` is the Pydantic v2 idiom — symmetric
    # with the ``metadata: dict[...] = Field(default_factory=dict, ...)``
    # declaration two lines below, and matches the ``Settings.ollama_host
    # = Field(default_factory=lambda: AnyHttpUrl(...))`` precedent in
    # ``app/core/config.py``. ``ModelParams`` is ``frozen=True`` so a
    # shared class-level instance would be safe today, but factory-based
    # construction defends against a future ``frozen=False`` flip
    # silently turning the field into a class-level mutable default.
    params: ModelParams = Field(
        default_factory=ModelParams,
        description="Optional per-request inference parameters (temperature, etc.).",
    )
    # ``JsonValue`` is Pydantic's recursive JSON-primitive type
    # (str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]).
    # Tightens the wire contract from ``dict[str, Any]`` so a consumer cannot
    # ship a non-JSON value (e.g. a datetime) that would deserialize fine on
    # input and fail downstream at JSON encoding. The Annotated key type
    # bounds the third orthogonal DoS axis (key length); the
    # ``_bound_metadata_values`` validator below bounds string-value leaves
    # recursively — together they pin all three metadata-DoS surfaces
    # (key count via ``max_length``, key length via the key Annotated cap,
    # per-string-leaf length via the recursive validator).
    metadata: dict[MetadataKey, JsonValue] = Field(
        default_factory=dict,
        max_length=16,
        description=(
            "Pass-through per-project metadata; structural bounds enforced "
            "(<=16 keys, key length, recursive string-leaf length), content "
            "semantics opaque to LIP."
        ),
    )

    @model_validator(mode="after")
    def _bound_metadata_values(self) -> Self:
        for key, value in self.metadata.items():
            # Defense-in-depth: the dict-key Annotated cap above already
            # bounds key length, but a future schema rebuild that drops
            # the Annotated wrapper without updating this validator would
            # otherwise silently widen the surface — re-check here keeps
            # the cap visible at the validator level too.
            if len(key) > METADATA_KEY_MAX_LENGTH:
                msg = f"metadata key {key!r} exceeds the {METADATA_KEY_MAX_LENGTH}-character cap."
                raise ValueError(msg)
            _bounded_strings_in_metadata(value, repr(key))
        return self
