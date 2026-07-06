"""DocsRAG HTTP API. Phase 0: health check & /ask streaming."""
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from docsrag.generate import stream_events
from docsrag.models import AskRequest

app = FastAPI(title="DocsRAG", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. ≈ a minimal ASP.NET health endpoint."""
    return {"status": "ok"}

@app.post("/ask")
def ask(request: AskRequest) -> StreamingResponse:
    """Stream a grounded, cited answer as Server-Sent Events."""

    def event_stream():
        for event in stream_events(request.question, request.k):
            payload = json.dumps(event)
            yield f"data: {payload}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
