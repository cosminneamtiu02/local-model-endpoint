"""Message value-object — one turn of a conversation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.inference.model.caps import TEXT_PART_MAX_CHARS
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
    # Per-arm constraints: str -> char-count cap (single-turn plain prompt);
    # list -> part-count cap. ``TEXT_PART_MAX_CHARS`` is shared with
    # ``TextContent.text`` so a future cap bump moves both at once. The
    # ``union_mode`` metadata rides inside the outer ``Annotated`` so all
    # union-related Field metadata lives in one wrapper — symmetric with
    # the per-arm Annotated form already used on each branch.
    content: Annotated[
        Annotated[str, Field(min_length=1, max_length=TEXT_PART_MAX_CHARS)]
        | Annotated[list[ContentPart], Field(min_length=1, max_length=32)],
        Field(union_mode="left_to_right"),
    ]
