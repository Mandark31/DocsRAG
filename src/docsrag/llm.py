"""OpenAI-compatible LLM client factory (Groq by default).

Provider-agnostic: all LLM calls in the app go through here. Swapping providers
= change LLM_BASE_URL + key in .env only — no code changes elsewhere.
"""
from functools import lru_cache

from openai import APIConnectionError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from docsrag.config import settings

@lru_cache(maxsize = 1)
def get_client() -> OpenAI:
  """One OpenAI-compatible client per process (lazy singleton)."""
  return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

@retry(
      retry=retry_if_exception_type((APIConnectionError, RateLimitError)),
      wait=wait_exponential(multiplier=1, min=1, max=10),
      stop=stop_after_attempt(3),
      reraise=True
)
def chat(messages: list[dict], *, model: str | None = None, **kwargs):
    """Create a chat completion with automatic retries on transient errors.

    Works for both blocking and streaming calls — pass stream=True through kwargs.
    Retries only on connection/rate-limit errors (not on bad requests).
    """
    return get_client().chat.completions.create(
       model=model or settings.llm_model,
       messages=messages,
       **kwargs,
    )
