# DocsRAG — Python & Programming Concepts (through Phase 1)

> Personal study notes for a .NET dev learning Python/FastAPI.
> C#/.NET analogies included where they genuinely fit; concept stated directly first.

---

## 1. Python has no per-project isolation by default

The biggest mental shift from .NET. In .NET, every project is naturally sandboxed (deps in its own build output, SDK pinnable via `global.json`, nothing leaks). Python is the opposite: `pip install` dumps packages into a **global** site-packages shared by every project → version collisions.

- **Virtual environment (`.venv`)** — the historical fix: a per-project folder of isolated packages.
- **uv** collapses three tools into one:
  - Python *version* manager — pinned 3.12 via `.python-version` (≈ `global.json`), system 3.9.6 untouched.
  - virtualenv manager — creates/manages the `.venv`.
  - dependency resolver/installer (≈ NuGet restore).
- `uv run <cmd>` = "run this command *inside* the project's isolated env with the right Python + deps" (≈ `dotnet run`'s guarantee you're using resolved deps).
- `uv.lock` = pinned transitive deps for reproducible installs (≈ `packages.lock.json`).
- `pyproject.toml` = unified manifest (≈ `.csproj` + tooling config in one file).

---

## 2. Packages, `__init__.py`, wheels

- `__init__.py` files mark a folder as an importable **package**. (No clean .NET analogy — Python namespaces are file/folder-driven, not declared.)
- **Wheel (`.whl`)** = the build artifact, a zip of the package (≈ a `.nupkg`). Built once; installed into target environments.
- **hatch** = the build backend (≈ the MSBuild step producing the artifact). Needs to be told where the package lives once it's under `src/`.
- See architecture doc for the full src-layout rationale.

---

## 3. Type hints

Python type hints (`def embed_query(text: str) -> list[float]:`) are like C# types but **not enforced at runtime by the language** — they're annotations used by tooling (editors, type checkers like mypy/pyright) and by libraries (FastAPI/Pydantic read them to do real work). Think "documented + tool-checked intent," with Pydantic turning them into actual runtime validation where it matters.

---

## 4. Pydantic models (≈ DTOs / records)

- A Pydantic model (`Chunk`: `id`, `text`, `source`, `position`) ≈ a C# DTO/record, but with **runtime validation** built from the type hints.
- On construction it validates and coerces types; bad data raises immediately.
- FastAPI uses them for request/response models *and* auto-generates Swagger from them.
- **pydantic-settings** (the `Settings` class) ≈ `IOptions<T>` bound from config, with fail-fast validation. See architecture doc.

---

## 5. The lazy singleton via `@lru_cache`

```python
@lru_cache
def get_embedding_model():
    return TextEmbedding("BAAI/bge-small-en-v1.5")
```

### Problem it solves
Loading an embedding model is **expensive** (reads hundreds of MB of weights from disk into RAM). Want it to happen **once per process**, and the loaded model reused for every call.

### How `@lru_cache` does it
On a zero-arg function: first call runs the body + caches the return value; every later call returns the **cached instance** without re-running the body.
- **Lazy** = deferred until first actually needed (not at import time).
- **Singleton** = one shared instance for the whole process.

≈ `Lazy<T>` registered as a singleton — deferred construction + single shared instance.

### Two caches, two problems (don't conflate)
1. **Disk cache (download cache)** — "already downloaded these weights, don't re-fetch from the internet." Persists across runs (`~/.cache/...`). Managed by **fastembed**, populated on first-ever embed call.
2. **In-memory cache (`@lru_cache`)** — "already loaded weights from disk into RAM *this process*, don't reload." Lives only for the process lifetime.

Lifecycle: first embed ever → fastembed downloads from internet → saves to disk. Every process start → weights read disk→memory (slow). `@lru_cache` ensures that disk→memory load happens **once per process**, not once per call.

### Library vs. weights (two artifacts)
- **`fastembed`** (the dependency) = the *library code* that runs an embedding model (tokenize, run the net, produce vectors). Small; installed by `uv add`.
- **`BAAI/bge-small-en-v1.5`** (the weights) = the *trained network itself*, hundreds of MB. **Not bundled** — too large; fetched on first use and cached on disk.
- Code vs. data — two distinct things. Adding the dependency gives you only the first.

---

## 6. async (preview — fuller treatment in later phases)

- `async def` + `yield` for SSE streaming ≈ `IAsyncEnumerable<T>`.
- `asyncio` ≈ `async`/`await` + `Task`.
- **ASGI** = the async-native server↔app standard (uvicorn ↔ FastAPI); ASGI being async-native is what makes streaming responses clean.
- (Deeper async coverage deferred to Phase 3 when we build the streaming `/ask` endpoint.)

---

## 7. Framework / runtime mapping (quick reference)

| Python / FastAPI | .NET |
|---|---|
| Pydantic model | DTO / record (with runtime validation) |
| pydantic-settings `Settings` | `IOptions<T>` from config, fail-fast |
| FastAPI `Depends` | DI container registration + constructor injection |
| FastAPI | ASP.NET Core minimal APIs |
| uvicorn | Kestrel |
| ASGI | the Kestrel↔middleware-pipeline contract (async-native) |
| `pyproject.toml` / uv | `.csproj` / NuGet |
| `uv.lock` | `packages.lock.json` |
| `.python-version` | `global.json` |
| `.whl` wheel | `.nupkg` |
| hatch (build backend) | MSBuild step producing the artifact |
| pytest | xUnit |
| `@lru_cache` lazy singleton | `Lazy<T>` as singleton |
| `async def` + `yield` (SSE) | `IAsyncEnumerable<T>` streaming |
| `asyncio` | `async`/`await` + `Task` |
| `--reload` | `dotnet watch` |

---

## 8. CLI / run notes

- Ad-hoc commands need `PYTHONPATH=src` (consequence of the src layout). Convenience shortcut deferred to Phase 5.
- Run server: `uv run uvicorn docsrag.api:app --reload --app-dir src` → `/docs` (auto Swagger) + `/health`.
- Restart infra: `docker compose up -d` (data persists in the `qdrant_storage` volume).
