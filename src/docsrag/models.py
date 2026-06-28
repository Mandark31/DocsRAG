from pydantic import BaseModel, Field


class Chunk(BaseModel):
  id: str = Field(..., description="Stable unique id for this chunk (used as the Qdrant point it).")
  text: str = Field(..., description="The chunk's raw content.")
  source: str = Field(..., description="Source's filename, e.g. 'path-params.md'.")
  position: int = Field(..., description="0-based index of this chunk within its source file.")