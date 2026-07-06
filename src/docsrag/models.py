from pydantic import BaseModel, Field


class Chunk(BaseModel):
  id: str = Field(..., description="Stable unique id for this chunk (used as the Qdrant point id).")
  text: str = Field(..., description="The chunk's raw content.")
  source: str = Field(..., description="Source's filename, e.g. 'path-params.md'.")
  position: int = Field(..., description="0-based index of this chunk within its source file.")

class AskRequest(BaseModel):
  """Request body for POST /ask."""

  question: str = Field(..., description="The user's question.")
  k: int = Field(default=5, ge=1, le=20, description="How many chunks to retrieve.")