"""DocsRAG HTTP API. Phase 0: health check only; /ask streaming comes in Phase 3."""
from fastapi import FastAPI

app = FastAPI(title="DocsRAG", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. ≈ a minimal ASP.NET health endpoint."""
    return {"status": "ok"}
