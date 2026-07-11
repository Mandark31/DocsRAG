# DocsRAG API image.
FROM python:3.12-slim

# Bring in the uv binary (fast, reproducible installs from uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifests + the package source first, so `uv sync` is cached
# unless these change. README is needed because pyproject.toml references it and
# the package build reads it.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Install runtime deps + the docsrag package itself, exactly per the lockfile,
# skipping dev tools (pytest). Creates /app/.venv.
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Copy the rest of the project (corpus, eval, scripts).
COPY . .

EXPOSE 8000

# docsrag is installed, so uvicorn can import docsrag.api directly.
CMD ["uv", "run", "uvicorn", "docsrag.api:app", "--host", "0.0.0.0", "--port", "8000"]
