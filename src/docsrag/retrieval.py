
from docsrag.embeddings import embed_query
from docsrag.models import Chunk
from docsrag.vectorstore import search


def retrieve(query: str, k: int = 5) -> list[Chunk]:
    """Embed the query and return the top-k most relevant chunks from Qdrant."""
    vector = embed_query(query)
    results = search(vector, k)
    return [chunk for chunk, _ in results]