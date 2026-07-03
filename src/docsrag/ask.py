"""Ask CLI: question in → cited answer + Sources footer out (non-streaming).

Run:  PYTHONPATH=src uv run python -m docsrag.ask "your question"
"""
import sys

from docsrag.generate import generate_answer


def main() -> None:
  if len(sys.argv) < 2:
    print('Usage: python -m docsrag.ask "your question"')
    raise SystemExit(1)

  question = " ".join(sys.argv[1:])
  answer, chunks = generate_answer(question)

  print(f"\nQ: {question}\n")
  print(answer)

  print("\nSources:")
  for i, chunk in enumerate(chunks, start=1):
    print(f" [{i}] {chunk.source} (chunk #{chunk.position})")


if __name__ == "__main__":
  main()
