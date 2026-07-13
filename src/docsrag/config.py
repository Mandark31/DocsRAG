"""Typed application settings, loaded from .env. (≈ IOptions<T> in .NET.)"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM (OpenAI-compatible interface; Groq by default)
    llm_api_key: str
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_model_fallback: str = "llama-3.1-8b-instant"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "docsrag"

    # Embeddings (local)
    embed_model: str = "BAAI/bge-small-en-v1.5"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Single shared instance, imported elsewhere (≈ a registered singleton).
settings = Settings()  # type: ignore[call-arg]
