"""Entry point: `python -m app` reads Settings and launches uvicorn.

Going through this entry point (rather than `uvicorn app.main:app
--host ... --port ...` with hardcoded flags) keeps Settings as the
single source of truth for bind_host / bind_port. The validator that
rejects 0.0.0.0 binds without ALLOW_PUBLIC_BIND=true then actually
takes effect on the running process.
"""

import uvicorn

from app.api.deps import get_settings


def main(*, reload: bool = False) -> None:
    """Run the FastAPI app via uvicorn, sourcing host/port from Settings."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        reload=reload,
    )


if __name__ == "__main__":
    # `python -m app` runs without reload; `task dev` toggles reload by
    # passing --reload on the command line, which uvicorn picks up via
    # its own argv parsing when invoked as a script. Keeping reload as a
    # function kwarg means the production launch path stays clean.
    import sys

    main(reload="--reload" in sys.argv)
