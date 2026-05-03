"""Entry point: `python -m app` reads Settings and launches uvicorn.

Going through this entry point (rather than `uvicorn app.main:app
--host ... --port ...` with hardcoded flags) keeps Settings as the
single source of truth for bind_host / bind_port. The validator that
rejects 0.0.0.0 binds without LIP_ALLOW_PUBLIC_BIND=true then actually
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
        # ``log_config=None`` disables uvicorn's default ``dictConfig`` so
        # the structlog stdlib bridge configured in
        # :func:`app.core.logging.configure_logging` keeps ownership of the
        # ``uvicorn`` / ``uvicorn.error`` / ``uvicorn.access`` loggers.
        # Without this kwarg, uvicorn replaces the root handler chain at
        # process start and every framework log line ships in uvicorn's
        # plain-text format instead of our JSON pipeline.
        log_config=None,
    )


if __name__ == "__main__":
    # ``--reload`` is the ONLY CLI knob this entry point honors;
    # everything else (host, port, log_level, etc.) is Settings-driven
    # so the SSRF / public-bind validators have a single source of
    # truth. Adding a second CLI knob requires an ADR — the temptation
    # to add ``--port`` here is exactly the paradigm-drift seed
    # CLAUDE.md sacred rule #3 ("one way to do each thing") forbids.
    import sys

    main(reload="--reload" in sys.argv)
