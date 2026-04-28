"""ModelParams value-object — sampling overrides supplied by the consumer."""

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

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    top_k: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: list[str] | None = Field(default=None)
    seed: int | None = Field(default=None, ge=0)
    think: bool = False
