"""Retrieval: hybrid recall (dense + BM25, RRF-fused), then cross-encoder precision."""

from docsrag.config import settings
from docsrag.embeddings import embed_query, embed_sparse_query
from docsrag.models import Chunk
from docsrag.rerank import rerank
from docsrag.vectorstore import hybrid_search


def retrieve(query: str, k: int = 5) -> list[Chunk]:
    """Return the k most relevant chunks for `query`.

    Two stages, cheap-then-expensive:
      1. Recall    — dense and BM25 branches fused by RRF into N candidates.
                     Casts a wide net; BM25 catches exact tokens dense blurs.
      2. Precision — a cross-encoder re-reads (query, chunk) pairs and reorders
                     those N candidates; only the top k survive into the prompt.
    """

    dense = embed_query(query)
    sparse = embed_sparse_query(query)

    candidates = hybrid_search(dense, sparse, limit=settings.retrieval_candidates)
    ranked = rerank(query, [chunk for chunk, _ in candidates])
    
    return [chunk for chunk, _ in ranked[:k]]