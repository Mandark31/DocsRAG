from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    FusionQuery,
    Modifier,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from docsrag.config import settings
from docsrag.embeddings import EMBED_DIM, SparseVec
from docsrag.models import Chunk

# Named vectors: one point carries both representations, like two indexes on
# the same table — one full-text (sparse), one vector (dense).
DENSE = "dense"
SPARSE = "sparse"


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection() -> None:
    client = _client()
    if client.collection_exists(settings.qdrant_collection):
        return
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={DENSE: VectorParams(size=EMBED_DIM, distance=Distance.COSINE)},
        # Modifier.IDF makes Qdrant apply inverse-document-frequency weighting to
        # the raw term frequencies fastembed sends. Without it, BM25 is just TF.
        sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)},
    )


def reset_collection() -> None:
    """Drop the collection if it exists, then recreate it empty.

    Makes ingest a clean full rebuild — no orphaned points when content changes.
    """
    _client().delete_collection(settings.qdrant_collection)
    ensure_collection()


def upsert_chunks(
    chunks: list[Chunk],
    dense_vectors: list[list[float]],
    sparse_vectors: list[SparseVec],
) -> int:
    points = [
        PointStruct(
            id=chunk.id,
            vector={
                DENSE: dense,
                SPARSE: SparseVector(indices=indices, values=values),
            },
            payload=chunk.model_dump(),
        )
        for chunk, dense, (indices, values) in zip(
            chunks, dense_vectors, sparse_vectors, strict=True
        )
    ]
    _client().upsert(collection_name=settings.qdrant_collection, points=points)
    return len(points)


def search(vector: list[float], k: int = 5) -> list[tuple[Chunk, float]]:
    """Dense-only search. Kept as a debugging lens (docsrag-search) so we can
    still see what pure vector similarity does, separate from the hybrid path."""
    hits = (
        _client()
        .query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            using=DENSE,
            limit=k,
            with_payload=True,
        )
        .points
    )
    return [(Chunk(**hit.payload), hit.score) for hit in hits]


def hybrid_search(
    dense_vector: list[float], sparse_vector: SparseVec, limit: int
) -> list[tuple[Chunk, float]]:
    """Run dense and sparse branches, fuse them with Reciprocal Rank Fusion.

    Each Prefetch is an independent ranked search. RRF combines them by *rank*,
    not raw score — a cosine similarity and a BM25 score are on incomparable
    scales, but "3rd place" means the same thing in both lists.

    NOTE: the returned float is an RRF score, not a similarity. It's only
    meaningful for ordering within this result set.
    """
    indices, values = sparse_vector
    hits = (
        _client()
        .query_points(
            collection_name=settings.qdrant_collection,
            prefetch=[
                Prefetch(query=dense_vector, using=DENSE, limit=limit),
                Prefetch(
                    query=SparseVector(indices=indices, values=values),
                    using=SPARSE,
                    limit=limit,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        .points
    )
    return [(Chunk(**hit.payload), hit.score) for hit in hits]
