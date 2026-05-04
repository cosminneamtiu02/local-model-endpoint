"""ModelParams value-object — sampling overrides supplied by the consumer."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Single stop-token alias so the per-token min/max bounds appear in one
# place rather than inline on the list-element type. `max_length=64`
# bounds the cost of the stop-sequence compare path inside Ollama (8
# sequences of 64 chars each is far above any realistic prompt-engineering
# need); `min_length=1` rejects empty matches that would terminate
# generation immediately.
type StopToken = Annotated[str, Field(min_length=1, max_length=64)]


class ModelParams(BaseModel):
    """Sampling parameters merged over per-model registry defaults.

    Every sampling field defaults to `None` so that
    `model_dump(exclude_unset=True)` on a freshly constructed instance
    returns `{}` — the merge logic interprets that as "consumer
    overrode nothing." `think` is the lone non-sampling toggle and
    defaults to `False`.

    `top_p` excludes zero (`gt=0.0`) because nucleus sampling with zero
    probability mass is undefined; `temperature` includes zero
    (`ge=0.0`) because greedy decoding is a legitimate setting.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description=(
            "Softmax temperature. 0.0 = greedy (argmax) decoding; higher values "
            "flatten the distribution. Capped at 2.0 to bound nonsense output."
        ),
        examples=[0.7],
    )
    top_p: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Nucleus-sampling probability mass. Excludes zero because nucleus "
            "sampling with zero mass is undefined."
        ),
        examples=[0.9],
    )
    top_k: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Top-k sampling: keep only the k highest-probability tokens at each "
            "step. Strictly positive."
        ),
        examples=[40],
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Hard upper bound on completion tokens generated. Maps to Ollama's "
            "``num_predict`` option in the translation layer."
        ),
        examples=[256],
    )
    # max_length on the list and on each token bounds the cost of the
    # stop-sequence compare path inside Ollama; 8 sequences of 64 chars
    # each is far above any realistic prompt-engineering need.
    stop: list[StopToken] | None = Field(
        default=None,
        max_length=8,
        description=(
            "List of stop sequences. Generation halts the moment any of these "
            "appears in the streamed output."
        ),
        examples=[["</answer>", "STOP"]],
    )
    seed: int | None = Field(
        default=None,
        ge=0,
        # Ollama's underlying llama.cpp sampler casts the seed to ``uint32``,
        # so any value > 2^32-1 silently mod-truncates inside the backend.
        # Capping at the schema boundary surfaces the truncation as a
        # consumer-visible ValidationError instead of a "two different
        # large seeds reproduce the same output" determinism puzzle.
        le=2**32 - 1,
        description=(
            "Deterministic-sampling seed. Non-negative, ≤2^32-1 (uint32 "
            "ceiling enforced by Ollama / llama.cpp); identical (model, "
            "prompt, params, seed) tuples reproduce the same output."
        ),
        examples=[42],
    )
    think: bool = Field(
        default=False,
        description=(
            "Enable Ollama thinking mode. Forwarded via the Ollama options "
            "block alongside sampling fields."
        ),
    )
