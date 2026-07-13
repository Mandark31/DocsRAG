"""Phase 0 smoke test: one chat completion through the OpenAI-compatible client.

Provider-agnostic: we use the stock `openai` SDK but point base_url at Groq.
Swapping providers later = change LLM_BASE_URL + key in .env only.
"""
import sys
from pathlib import Path

# Make `import docsrag...` work when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI
from docsrag.config import settings

client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

resp = client.chat.completions.create(
    model=settings.llm_model,
    messages=[{"role": "user", "content": "In one sentence, what is retrieval-augmented generation?"}],
)

print(f"Model: {settings.llm_model}")
print("Reply:", resp.choices[0].message.content)
