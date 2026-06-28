import sys

from docsrag.embeddings import embed_query
from docsrag.vectorstore import search


def main() -> None:
  if len(sys.argv) < 2:
    print('Usage: Python -m docsrag.search "your query"')
    raise SystemExit(1)

  query = " ".join(sys.argv[1:])
  vector = embed_query(query)
  results = search(vector, k=5)

  print(f'Query: {query}\n')
  for rank, (chunk, score) in enumerate(results, start=1):
    preview = chunk.text[:200].replace("\n", " ")
    print(f"#{rank} score={score: 4f} [{chunk.source} # {chunk.position}]")
    print(f"    {preview}...\n")


if __name__ == "__main__":
  main()