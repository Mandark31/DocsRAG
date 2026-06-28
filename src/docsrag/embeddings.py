from functools import lru_cache

from fastembed import TextEmbedding

from docsrag.config import settings


EMBED_DIM = 384 # bge-small-en-v1.5 output size — must match the Qdrant collection.

@lru_cache(maxsize = 1)
def _model() -> TextEmbedding:
  return TextEmbedding(model_name = settings.embed_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
  return [vec.tolist() for vec in _model().embed(texts)]

def embed_query(text: str) -> list[float]:
  return embed_texts([text])[0]