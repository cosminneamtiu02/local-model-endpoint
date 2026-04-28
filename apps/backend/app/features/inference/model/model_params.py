"""ModelParams value-object — sampling overrides supplied by the consumer."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


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

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    # max_length on the list and on each token bounds the cost of the
    # stop-sequence compare path inside Ollama; 8 sequences of 64 chars
    # each is far above any realistic prompt-engineering need.
    stop: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(
        default=None,
        max_length=8,
    )
    seed: int | None = Field(default=None, ge=0)
    think: bool = Field(
        default=False,
        description=(
            "Enable Ollama thinking mode (LIP-E003-F002 [RESOLVED]). Forwarded "
            "via the Ollama options block alongside sampling fields."
        ),
    )
