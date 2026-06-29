# DocsRAG — Architecture & Project Decisions (through Phase 1)

> Personal study notes. Every decision here should be defensible cold.
> These are the *architectural* choices (the "why we built it this way"), separate from RAG theory and Python mechanics.

---

## 1. Project structure: the `src/` layout

Package lives at `src/docsrag/`, not `docsrag/` at the root. Two config lines support it:
- `[tool.hatch.build.targets.wheel] packages=["src/docsrag"]`
- `[tool.pytest.ini_options] pythonpath=["src"]`

### Why
Putting the package one level down makes it **impossible to import by accident from the project root.** Code/tests then run against the package *as it would actually be installed*, catching packaging bugs early (a file that imports fine locally because it's right there on disk, but is missing after install).

The bug it catches, stated precisely: src layout forces importing the package **by name** the same way installed code must, instead of importing it **by happening to be in the same folder**.

### Why the explicit `packages=[...]` line
When the package sits at the root, build tools **auto-detect** it. Moving it into `src/` **breaks auto-detection**, so you point the tool at it.
- This is a **build-time** concern, **not** a deploy-time one. (Common misconception: it's *not* "required for prod deployment.")
- Lifecycle: build once into a **wheel** (`.whl` — standard distribution format, basically a zip of the package). The `packages=[...]` line is read *at build time*. The wheel installs into the target env; the package is then just importable. Prod doesn't re-read `pyproject.toml`.

### Symptom to recognize
`ModuleNotFoundError: docsrag` → first thing to check. Also why the run command uses `--app-dir src`.

---

## 2. Provider-agnostic LLM layer

**Rule:** every LLM call goes through `llm.py`'s OpenAI-compatible client. Swapping providers = change `base_url` + key in `.env`/`config.py` only. No provider-specific code anywhere else.

### Why it works
"OpenAI-compatible" is a **de facto wire protocol** (NOT an official spec — phrase it as "Groq exposes an OpenAI-compatible API surface," not "the OpenAI protocol"). Groq and many providers implement the *identical* `/chat/completions` request/response shape. So the OpenAI *SDK* works against any of them by swapping `base_url` + key.

### Resolving the apparent contradiction
"How are you provider-agnostic if you imported the OpenAI SDK?"
→ Because `base_url` and `api_key` are config values (in `config.py`/`.env`), and the `Settings` object is a **single shared instance read everywhere**. There's exactly **one source of truth**; every call site reads from it; changing it changes everything **atomically**. The SDK is just a client speaking a shape many providers also speak.

This is the **Adapter / anti-corruption layer** pattern — Dependency Inversion applied to model providers. No Groq-specific code leaks into the domain.

### Model slugs (verified live)
- Primary: `llama-3.3-70b-versatile`
- Fallback: `llama-3.1-8b-instant`

---

## 3. Fail-fast typed config

`config.py` uses pydantic-settings: reads env vars / `.env`, **validates types at construction**, throws immediately if a required value (e.g. `GROQ_API_KEY`) is missing/malformed. Nowhere else does stringly-typed env reading; everything goes through one typed object.

### Why timing matters (the senior point)
- **Without fail-fast:** a missing key is discovered when the **first request** hits the code path that reads it — minutes/hours post-deploy, on a real user's request, as a confusing 500 deep in a stack trace.
- **With fail-fast:** discovered at **process startup, before accepting any connection.** Health check never goes green → the deployment system can auto-rollback because the new version never reported healthy.

> **Fail-fast turns a runtime error into a deploy-time error**, so orchestration catches it instead of users. A config problem becomes a *failed deployment* (safe, automated rollback) rather than a *production incident* (pages, debugging, angry users).

### Secrets hygiene
- `.env` — real key, **gitignored**, never committed.
- `.env.example` — committed template documenting *which* vars are required, without leaking values.
- (Analogous to user-secrets locally + a committed appsettings template.)

---

## 4. Containerization strategy (Docker)

### Current split (development)
```
Mac (host)
├── FastAPI app  → runs natively via `uv run`   (NOT containerized)
│        │ talks over localhost:6333
└── Docker
     └── Qdrant  → the ONLY thing in a container
```

### Why this split
- **Qdrant is containerized** because it's an **unchanging external dependency** — want the exact published version, isolated, set-once-forget. Official image maintained by Qdrant.
- **App is NOT containerized** because it's **actively being developed**. Native + `--reload` = near-instant edit-run-test loop. Running the app in a container during dev = rebuild/mount friction on every edit.
- Pattern: keep the thing you're *changing* outside a container (fast iteration), the thing you *depend on* inside one (clean isolation).

### "Is the app containerized?" — depends on lifecycle stage
- **Dev (now):** app native, Qdrant containerized. Optimized for iteration speed.
- **Prod (later):** containerize the app too → whole system ships as a reproducible unit. This is exactly why **Phase 5 lists a Dockerfile** as a stretch goal.

### Compose vs Dockerfile (get this precise)
- `docker-compose.yml` **orchestrates** containers (declares what runs + how they connect). Currently references a **pre-built** Qdrant image pulled from a registry — we didn't build it.
- `Dockerfile` **builds** a single image (recipe for one container). Adding our app later = write a Dockerfile to build *our* image, then add it as a second service in the same Compose file.

### Ports & volumes
- **Ports** punch a hole through container isolation. `6333:6333` = "traffic to host:6333 forwards to container:6333." Two doors into Qdrant: **6333 HTTP/REST** (+ dashboard), **6334 gRPC** (faster for bulk upserts).
- **Named volume (`qdrant_storage`)** = Docker-managed persistent storage *outside* the container lifecycle, mounted in. Vectors survive `docker compose down` + restart (die only with `-v`). Without it: empty DB on every restart (classic beginner trap, pre-empted).

### The dashboard
`http://localhost:6333/dashboard` — Qdrant's **built-in** admin/inspection UI, served on its HTTP port, reachable because of the port mapping. Not part of our project. Useful *after* ingestion: verify collection size (384) + metric (cosine), point count matches chunks ingested, inspect vectors/payloads, sanity-check + debug retrieval.

---

## 5. Idempotent + repeatable ingestion

### Idempotent collection setup
`ensure_collection()` only creates the collection if it doesn't already exist — call it any number of times, no error, no duplicate. Lets the ingestion script run repeatedly without special-casing "first run vs later."

### Safe re-ingestion (no duplicate vectors)
Two mechanisms **combined**:
1. **Deterministic `uuid5` IDs** — same chunk content/source always computes to the **same ID**.
2. **Upsert** = update-or-insert: if the ID exists, **overwrite in place**; else insert.

> Pairing: same content → same ID → upsert overwrites rather than inserts. That's why 138 chunks stay 138 across re-runs, not 414.
> Deterministic IDs alone do nothing — it's the *pairing* (a stable ID for upsert to match against) that de-duplicates. The idempotent collection setup is hygiene; **upsert + deterministic IDs** is what actually prevents duplicate vectors.

---

## 6. Corpus & known limitations

- Corpus: 15 curated FastAPI tutorial `.md` files in `./data` (flat, top-level).
- **Known harmless noise:** chunks contain FastAPI doc-build macros (`{* ../../docs_src/... *}`) — doc-build include directives that become real code samples only when the docs site is built; in raw `.md` they're literal text. Judged harmless (small noise, doesn't meaningfully shift embeddings, retrieval verified working).
- **What I'd improve with time:** preprocess markdown (strip macros/boilerplate) *before* chunking so chunks hold only real content. Consciously deferred — knowing it's there and choosing to leave it is fine; *not* knowing would be the red flag.

---

## 7. Tooling decisions

- **uv** — one tool for Python version management (pins 3.12 via `.python-version`, system Python 3.9.6 untouched), virtualenv management (`.venv`), and dependency resolution/install. `uv.lock` = pinned transitive deps for reproducible installs.
- **pyproject.toml** — unified manifest: `[project]` (metadata + deps), `[tool.*]` (hatch, pytest config co-located).
- **FastAPI** (web framework), **uvicorn** (ASGI server that hosts it), **ASGI** = async-native server↔app standard that makes streaming clean. `--reload` = watch + restart on save.
- **Local-first embeddings** (fastembed) — see RAG concepts doc for the cost/latency/privacy rationale.

---

## Phase status
- **Phase 0 ✅** — scaffold: uv, Docker/Qdrant, typed config, FastAPI `/health`, Groq smoke test.
- **Phase 1 ✅** — ingestion: per-file chunking, local bge-small embeddings, Qdrant upsert with deterministic IDs, search CLI verified (`"declare a path parameter"` → top-5 all from `path-params*.md`, top score 0.8357).
- **Three pieces written by hand (learning goals):** `retrieve()` (P2), streaming `/ask` (P3), LLM-judge prompt (P4).
