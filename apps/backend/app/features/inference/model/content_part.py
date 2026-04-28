"""Discriminated-union type alias over the three multimodal content variants.

`ContentPart` is the union Pydantic uses to route a `Message.content`
list element to its concrete variant by inspecting the `type` field.

Note: `ContentPart` is a type alias, not a runtime class. `isinstance`
checks must target the concrete variants (`TextContent`, `ImageContent`,
`AudioContent`), not this alias.
"""

from typing import Annotated

from pydantic import Field

from app.features.inference.model.audio_content import AudioContent
from app.features.inference.model.image_content import ImageContent
from app.features.inference.model.text_content import TextContent

type ContentPart = Annotated[
    TextContent | ImageContent | AudioContent,
    Field(discriminator="type"),
]
