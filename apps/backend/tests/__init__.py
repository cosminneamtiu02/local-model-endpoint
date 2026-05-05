"""Backend test suite (pytest).

Three tiers: unit (no network), integration (in-process FastAPI via
httpx ASGITransport), contract (wire-shape canaries). e2e arrives with
LIP-E001-F002 router per ADR-011.
"""
