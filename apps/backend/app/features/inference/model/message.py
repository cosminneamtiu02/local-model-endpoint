"""Message value-object — one turn of a conversation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.content_part import ContentPart


class Message(BaseModel):
    """One conversation turn.

    `content` is either a plain string (the simple, single-turn happy
    path) or a list of ContentPart variants for multimodal inputs.
    Role/multimodal compatibility is enforced at the adapter layer,
    not here.

    `union_mode="left_to_right"` pins the resolution order so a plain
    string is matched as `str` first, never as an iterable; this defends
    against Pydantic's smart-union routing edge cases on `str | list`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role: Literal["user", "assistant", "system"]
    # Per-arm constraints so Pydantic knows which length applies to which type:
    # str -> char-count cap (single-turn plain prompt); list -> part-count cap
    # (the third orthogonal DoS axis after per-part size and per-request message
    # count). min_length=1 on each arm rejects empty content. `union_mode` is on
    # the outer Field so the str arm is matched first; constraints with
    # `union_mode` cannot live on the same Field per Pydantic v2 semantics.
    content: Annotated[
        Annotated[str, Field(min_length=1, max_length=131072)]
        | Annotated[list[ContentPart], Field(min_length=1, max_length=32)],
        Field(union_mode="left_to_right"),
    ]
