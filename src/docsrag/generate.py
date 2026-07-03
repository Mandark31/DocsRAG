"""Generation: build a grounded prompt from retrieved chunks and ask the LLM
for an answer with inline numbered citations."""
from docsrag.config import settings
from docsrag.llm import get_client
from docsrag.models import Chunk
from docsrag.retrieval import retrieve

SYSTEM_PROMPT = (
    "You are a documentation assistant. Answer the user's question using ONLY the "
    "numbered context passages provided. Cite every claim inline with its passage "
    "number in square brackets, like [1] or [2][3]. If the context does not contain "
    "the answer, say you don't know — do not use outside knowledge or make things up."
)

def format_context(chunks: list[Chunk]) -> str:
  """Render chunks as a numbered list the model can cite: '[1] (source) text'."""
  blocks = []
  for i, chunk in enumerate(chunks, start=1):
    blocks.append(f"[{i}] (source : {chunk.source})\n{chunk.text}")
  return "\n\n".join(blocks) 

def generate_answer(question: str, k: int = 5) -> tuple[str, list[Chunk]]:
  """Retrieve context for `question`, ask the LLM, return (answer, chunks).

  The returned chunks are in citation order: chunks[0] is passage [1], etc.
  """
  chunks = retrieve(question, k)
  context = format_context(chunks)

  user_prompt = f"Context passages:\n\n{context}\n\nQuestion: {question}"

  response = get_client().chat.completions.create(
    model=settings.llm_model,
    messages=[
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user", "content": user_prompt},
    ],
    temperature=0.0
  )
  answer = response.choices[0].message.content
  return answer, chunks

