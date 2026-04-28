"""LIP feature slices.

Each slice follows the vertical-slice layout: model/ (Pydantic value-objects,
not ORM), repository/ (Ollama HTTP client wrappers, not DB access),
service/ (orchestration), router/ (FastAPI endpoints), schemas/ (wire shapes).
Layer ordering: router -> service -> repository -> model. Features cannot
import from other features. See CLAUDE.md for the full contract.
"""
