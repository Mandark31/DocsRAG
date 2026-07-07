from pathlib import Path
import re
import uuid

from docsrag.embeddings import embed_texts
from docsrag.models import Chunk
from docsrag.vectorstore import reset_collection, upsert_chunks


DATA_DIR = Path("data")
CHUNK_SIZE = 1000 # characters per chunk
CHUNK_OVERLAP = 150  # characters shared between consecutive chunks

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
  """Split text into fixed-size character windows that overlap by `overlap`.

  The window advances by (size - overlap) each step, so adjacent chunks share
  `overlap` characters — this preserves context that would otherwise be cut
  mid-sentence at a boundary.
  """
  if size <= overlap:
    raise ValueError("size must be greater than overlap")
  chunks: list[str] = []
  start = 0
  while start < len(text):
    chunk = text[start : start + size].strip()
    if chunk:
      chunks.append(chunk)
      start += size - overlap
  return chunks

def clean_markdown(text: str) -> str:
    """Remove FastAPI doc-build artifacts that aren't real content.

    - {* ../../docs_src/... *}  → code-include macros (MkDocs plugin)
    - { #some-anchor }          → heading anchor tags
    """
    text = re.sub(r"\{\*.*?\*\}", "", text)   # include macros
    text = re.sub(r"\{\s*#[\w-]+\s*\}", "", text)  # heading anchors
    return text

def build_chunks() -> list[Chunk]:
  """Read every .md file in ./data and turn it into Chunk DTOs."""
  chunks: list[Chunk] = []
  files = sorted(DATA_DIR.glob("*.md"))
  for path in files:
    text = clean_markdown(path.read_text(encoding="utf-8"))
    for position, piece in enumerate(chunk_text(text)):
      chunks.append(
        Chunk(
          id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{position}")),
          text=piece,
          source=path.name,
          position=position,
        )
      )
  print(f"Loaded {len(files)} files -> {len(chunks)} chunks")
  return chunks

def main() -> None:
  chunks = build_chunks()
  vectors = embed_texts([c.text for c in chunks])
  reset_collection()
  written = upsert_chunks(chunks, vectors)
  print(f"Upserted {written} point into Qdrant")

if __name__ == "__main__":
  main()
    