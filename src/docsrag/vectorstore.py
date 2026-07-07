from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from docsrag.config import settings
from docsrag.embeddings import EMBED_DIM
from docsrag.models import Chunk

@lru_cache(maxsize = 1)
def _client() -> QdrantClient:
  return QdrantClient(url=settings.qdrant_url)

def ensure_collection() -> None:
  client = _client()
  if(client.collection_exists(settings.qdrant_collection)):
    return
  client.create_collection(
    collection_name = settings.qdrant_collection,
    vectors_config = VectorParams(size=EMBED_DIM, distance=Distance.COSINE)
  )

def reset_collection() -> None:
    """Drop the collection if it exists, then recreate it empty.

    Makes ingest a clean full rebuild — no orphaned points when content changes.
    """
    _client().delete_collection(settings.qdrant_collection)
    ensure_collection()

def upsert_chunks(chunks: list[Chunk], vectors: list[list[float]]) -> int:
  points = [
    PointStruct(id=chunk.id, vector = vector, payload = chunk.model_dump())
    for chunk, vector in zip(chunks, vectors)
  ]
  _client().upsert(collection_name=settings.qdrant_collection, points=points)
  return len(points)


def search(vector: list[float], k: int = 5) -> list[tuple[Chunk, float]]:
  hits = _client().query_points(
    collection_name = settings.qdrant_collection,
    query = vector,
    limit = k,
    with_payload = True,
  ).points
  return [(Chunk(**hit.payload), hit.score) for hit in hits]

