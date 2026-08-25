"""Cross-encoder reranking: re-score candidate chunks against the query.

The bi-encoder in embeddings.py is a *recall* stage — it compares pre-computed
vectors and never sees query and document together. A cross-encoder reads
(query, document) as a single input, which is far more accurate but far too
expensive to run over a whole corpus. Hence the two-stage shape: cheap ANN
narrows the corpus to ~20, this re-scores exactly those.
"""

from functools import lru_cache

from fastembed.rerank.cross_encoder import TextCrossEncoder

from docsrag.config import settings
from docsrag.models import Chunk

 
@lru_cache(maxsize = 1)
def _reranker() -> TextCrossEncoder: 
  """One cross-encoder per process (lazy singleton), mirroring _model()."""
  return TextCrossEncoder(model_name = settings.reranker_model)

def rerank(query: str, chunks: list[Chunk]) -> list[tuple[Chunk, float]]:
  """Re-score `chunks` against `query`, most relevant first.

  fastembed returns one score per document **in input order**, so the scores
  must be zipped back onto their chunks before sorting. Higher = better.
  """
  if not chunks:
    return []
  scores = list(_reranker().rerank(query, [chunk.text for chunk in chunks]))
  ranked = list(zip(chunks, scores))
  ranked.sort(key = lambda pair: pair[1], reverse = True)
  return ranked
