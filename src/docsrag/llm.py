"""OpenAI-compatible LLM client factory (Groq by default).

Provider-agnostic: all LLM calls in the app go through here. Swapping providers
= change LLM_BASE_URL + key in .env only — no code changes elsewhere.
"""
from functools import lru_cache

from openai import OpenAI

from docsrag.config import settings

@lru_cache(maxsize = 1)
def get_client() -> OpenAI:
  """One OpenAI-compatible client per process (lazy singleton)."""
  return OpenAI(api_key=settings.groq_api_key, base_url=settings.llm_base_url)