"""Health endpoint — mounted at root, outside /api/v1/.

Liveness only in v1. Readiness will be added by LIP-E006-F001 when the
warm-up signal from LIP-E005-F001 is wired during feature-dev.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is alive."""
    return {"status": "ok"}
