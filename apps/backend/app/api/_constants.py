"""Cross-module constants for the api/ package.

Centralizes string and bytes constants that previously appeared in multiple
sites (RFC 7807 media type, Content-Language, EXC_MESSAGE preview cap)."""

from typing import Final

CONTENT_LANGUAGE: Final[str] = "en"
PROBLEM_JSON_MEDIA_TYPE: Final[str] = "application/problem+json; charset=utf-8"
