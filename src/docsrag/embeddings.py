from functools import lru_cache

from fastembed import SparseTextEmbedding, TextEmbedding

from docsrag.config import settings


EMBED_DIM = 384 # bge-small-en-v1.5 output size — must match the Qdrant collection.

# A sparse vector as (indices, values) in plain Python. Kept store-agnostic on
# purpose: this module knows how to embed, not how Qdrant wants it shaped.
SparseVec = tuple[list[int], list[float]]

@lru_cache(maxsize = 1)
def _model() -> TextEmbedding:
  return TextEmbedding(model_name = settings.embed_model)

@lru_cache(maxsize = 1)
def _sparse_model() -> SparseTextEmbedding:
  return SparseTextEmbedding(model_name = settings.sparse_model)

def embed_texts(texts: list[str]) -> list[list[float]]:
  return [vec.tolist() for vec in _model().embed(texts)]

def embed_query(text: str) -> list[float]:
  return embed_texts([text])[0]

def embed_sparse_texts(texts: list[str]) -> list[SparseVec]:
  """BM25 term-frequency vectors. Qdrant applies IDF at query time — only the
  server knows corpus-wide term statistics, so weighting can't happen here."""
  out: list[SparseVec] = []
  for emb in _sparse_model().embed(texts):
    obj = emb.as_object() # {"indices": ndarray, "values": ndarray}
    out.append((obj["indices"].tolist(), obj["values"].tolist()))
  return out

def embed_sparse_query(text: str) -> SparseVec:
  return embed_sparse_texts([text])[0]