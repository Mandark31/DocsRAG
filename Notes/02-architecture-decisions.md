# DocsRAG — Architecture & Project Decisions (through Phase 4)

> Personal study notes. Every decision here should be defensible cold.
> These are the _architectural_ choices (the "why we built it this way"), separate from RAG theory and Python mechanics.

---

## 1. Project structure: the `src/` layout

Package lives at `src/docsrag/`, not `docsrag/` at the root. Two config lines support it:

- `[tool.hatch.build.targets.wheel] packages=["src/docsrag"]`
- `[tool.pytest.ini_options] pythonpath=["src"]`

### Why

Putting the package one level down makes it **impossible to import by accident from the project root.** Code/tests then run against the package _as it would actually be installed_, catching packaging bugs early (a file that imports fine locally because it's right there on disk, but is missing after install).

The bug it catches, stated precisely: src layout forces importing the package **by name** the same way installed code must, instead of importing it **by happening to be in the same folder**.

### Why the explicit `packages=[...]` line

When the package sits at the root, build tools **auto-detect** it. Moving it into `src/` **breaks auto-detection**, so you point the tool at it.

- This is a **build-time** concern, **not** a deploy-time one. (Common misconception: it's _not_ "required for prod deployment.")
- Lifecycle: build once into a **wheel** (`.whl` — standard distribution format, basically a zip of the package). The `packages=[...]` line is read _at build time_. The wheel installs into the target env; the package is then just importable. Prod doesn't re-read `pyproject.toml`.

### Symptom to recognize

`ModuleNotFoundError: docsrag` → first thing to check. Also why the run command uses `--app-dir src`.

---

## 2. Provider-agnostic LLM layer

**Rule:** every LLM call goes through `llm.py`'s OpenAI-compatible client. Swapping providers = change `base_url` + key in `.env`/`config.py` only. No provider-specific code anywhere else.

### Why it works

"OpenAI-compatible" is a **de facto wire protocol** (NOT an official spec — phrase it as "Groq exposes an OpenAI-compatible API surface," not "the OpenAI protocol"). Groq and many providers implement the _identical_ `/chat/completions` request/response shape. So the OpenAI _SDK_ works against any of them by swapping `base_url` + key.

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

> **Fail-fast turns a runtime error into a deploy-time error**, so orchestration catches it instead of users. A config problem becomes a _failed deployment_ (safe, automated rollback) rather than a _production incident_ (pages, debugging, angry users).

### Secrets hygiene

- `.env` — real key, **gitignored**, never committed.
- `.env.example` — committed template documenting _which_ vars are required, without leaking values.
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
- Pattern: keep the thing you're _changing_ outside a container (fast iteration), the thing you _depend on_ inside one (clean isolation).

### "Is the app containerized?" — depends on lifecycle stage

- **Dev (now):** app native, Qdrant containerized. Optimized for iteration speed.
- **Prod (later):** containerize the app too → whole system ships as a reproducible unit. This is exactly why **Phase 5 lists a Dockerfile** as a stretch goal.

### Compose vs Dockerfile (get this precise)

- `docker-compose.yml` **orchestrates** containers (declares what runs + how they connect). Currently references a **pre-built** Qdrant image pulled from a registry — we didn't build it.
- `Dockerfile` **builds** a single image (recipe for one container). Adding our app later = write a Dockerfile to build _our_ image, then add it as a second service in the same Compose file.

### Ports & volumes

- **Ports** punch a hole through container isolation. `6333:6333` = "traffic to host:6333 forwards to container:6333." Two doors into Qdrant: **6333 HTTP/REST** (+ dashboard), **6334 gRPC** (faster for bulk upserts).
- **Named volume (`qdrant_storage`)** = Docker-managed persistent storage _outside_ the container lifecycle, mounted in. Vectors survive `docker compose down` + restart (die only with `-v`). Without it: empty DB on every restart (classic beginner trap, pre-empted).

### The dashboard

`http://localhost:6333/dashboard` — Qdrant's **built-in** admin/inspection UI, served on its HTTP port, reachable because of the port mapping. Not part of our project. Useful _after_ ingestion: verify collection size (384) + metric (cosine), point count matches chunks ingested, inspect vectors/payloads, sanity-check + debug retrieval.

---

## 5. Idempotent + repeatable ingestion

### Idempotent collection setup

`ensure_collection()` only creates the collection if it doesn't already exist — call it any number of times, no error, no duplicate. Lets the ingestion script run repeatedly without special-casing "first run vs later."

### Safe re-ingestion (no duplicate vectors)

Two mechanisms **combined**:

1. **Deterministic `uuid5` IDs** — same chunk content/source always computes to the **same ID**.
2. **Upsert** = update-or-insert: if the ID exists, **overwrite in place**; else insert.

> Pairing: same content → same ID → upsert overwrites rather than inserts. That's why 138 chunks stay 138 across re-runs, not 414.
> Deterministic IDs alone do nothing — it's the _pairing_ (a stable ID for upsert to match against) that de-duplicates. The idempotent collection setup is hygiene; **upsert + deterministic IDs** is what actually prevents duplicate vectors.

---

## 6. Corpus & known limitations

- Corpus: 15 curated FastAPI tutorial `.md` files in `./data` (flat, top-level).
- **Known harmless noise:** chunks contain FastAPI doc-build macros (`{* ../../docs_src/... *}`) — doc-build include directives that become real code samples only when the docs site is built; in raw `.md` they're literal text. Judged harmless (small noise, doesn't meaningfully shift embeddings, retrieval verified working).
- **What I'd improve with time:** preprocess markdown (strip macros/boilerplate) _before_ chunking so chunks hold only real content. Consciously deferred — knowing it's there and choosing to leave it is fine; _not_ knowing would be the red flag.

---

## 7. Tooling decisions

- **uv** — one tool for Python version management (pins 3.12 via `.python-version`, system Python 3.9.6 untouched), virtualenv management (`.venv`), and dependency resolution/install. `uv.lock` = pinned transitive deps for reproducible installs.
- **pyproject.toml** — unified manifest: `[project]` (metadata + deps), `[tool.*]` (hatch, pytest config co-located).
- **FastAPI** (web framework), **uvicorn** (ASGI server that hosts it), **ASGI** = async-native server↔app standard that makes streaming clean. `--reload` = watch + restart on save.
- **Local-first embeddings** (fastembed) — see RAG concepts doc for the cost/latency/privacy rationale.

---

## 8. Streaming architecture (Phase 3)

### The typed-event protocol (the standout design decision)

The `/ask` response is a **stream of typed events**, not a raw token stream:

- `{"type": "sources", "sources": [...]}` — once, **up front**.
- `{"type": "token", "text": "..."}` — many.
- `{"type": "done"}` — once, terminal.

**Why up-front sources:** inline `[n]` markers stream _inside_ the tokens; the client needs the source mapping _before_ they arrive so every citation is resolvable the instant it appears. Sources-in-`done` would leave `[2]` markers dangling until the end. (Full reasoning in RAG concepts §12.)

**Why typed events (client state machine):** the client has an unambiguous contract — set up sources, append tokens, finalize on `done`. `done` is **not decorative**: it's how the client knows the stream ended _cleanly_ vs. the socket dropping mid-answer (both otherwise look like "tokens stopped"). Every stream should end in exactly one terminal event — `done` (success) or `error` (failure, currently missing). "Socket closed with neither" = itself an error.

**Symmetry:** `done` is the echo of Groq's `[DONE]` sentinel — we're a consumer of Groq's stream and a producer of our own, using the identical "emit items, then signal exhaustion" contract at both boundaries.

### Two stacked generators (separation of concerns)

- `stream_events` (`generate.py`) yields **event dicts** — pure domain data, transport-agnostic (a CLI or WebSocket could consume it).
- `event_stream` (`api.py`) iterates that and yields **SSE-formatted strings** (`data: {...}\n\n`) — the wire format only.
- One produces meaning; the other formats it for HTTP. Clean boundary — call it out as deliberate.

### SSE vs WebSocket (why SSE)

- **SSE** = one-directional (server→client) over plain HTTP; literally a long-lived response that flushes text frames. Works through proxies/LBs with zero special handling, free browser reconnection.
- **WebSocket** = bidirectional persistent channel after an HTTP upgrade; needs lifecycle management + infra support.
- **Our case is strictly one-directional** (ask once, stream answer back) → SSE is the right fit. WebSocket would be over-engineering: bidirectional complexity + lost HTTP-friendliness to gain a return channel we don't use. **Choosing the less powerful tool because it exactly fits = maturity signal.**

### Why `POST` (not GET)

1. We send a **request body** (`AskRequest`: `question`, `k`). GET conventionally has no body; a free-text question in a query string is clunky + length-limited. Submitting data for processing = POST.
2. The browser's native `EventSource` is **GET-only, no body** — so SSE-with-a-payload deliberately uses POST + `fetch` streaming (`getReader()`), which is exactly our client shape.

### Sync generator in a threadpool — why it works and the scaling ceiling

The endpoint is `def ask` (sync), and `stream_events` / `event_stream` are **sync generators**.

- **Why it doesn't block the server:** Starlette runs a sync `StreamingResponse` generator in a **bounded threadpool** (anyio default ~40 workers), off the event loop. So blocking calls (`retrieve()`, blocking iteration of the LLM stream) don't stall the loop.
- **The ceiling:** a streaming generator **holds its thread for the entire stream duration** (the whole time the LLM emits tokens). So the real limit is ~**40 concurrent in-flight streams**; the 41st waits for a thread to free, and threads only free when a stream _completes_. Under real load the pool drains fast.
- **The async fix:** `async def ask` + `AsyncOpenAI` + `async for` + `async def` generator puts each stream on the **event loop** as a coroutine — the thread is **released while awaiting each token**, so a handful of threads serve thousands of concurrent streams.
- **Interview line:** "Sync works because Starlette threadpools sync stream generators; the tradeoff is one thread per concurrent stream, capping concurrency near the pool size. To scale I'd go async so the thread frees during the await." Knowing the tradeoff ≈ as valuable as implementing it for a weekend project.
- **.NET framing:** sync-in-threadpool ≈ blocking I/O on `Task.Run` threads (works, thread-bound); async ≈ real `async/await` over `IAsyncEnumerable<T>` (thread released during await, tiny thread count serves huge concurrency).

### Where retries fit (Phase 5 tenacity) vs. error events

- **tenacity retries** help _before_ the first token (retry the whole call).
- Once **mid-stream**, retrying re-emits tokens the client already has → messy. So the `error` event is the mid-stream safety net retries can't cover. Division: **retry before first token; error-event after.**

---

## 9. Eval harness design (Phase 4)

### The shape

`golden_qa.json` (human-curated Q&A pairs) + `test_eval.py` (pytest, LLM-as-judge). Each pair: run the real pipeline → judge the answer against the reference → PASS/FAIL. (Concepts in RAG doc §13.)

### Key design decisions

- **`@pytest.mark.parametrize` — one test per golden case** (≈ xUnit `[Theory]`+`[MemberData]`), not a loop inside one test. Independent pass/fail per case; **all cases run even when some fail**; `ids=[question]` labels each run with its actual question so a red test names _which_ question broke. A loop would stop at the first failure and hide the rest.
- **`temperature=0.0` on the judge** — same reproducibility reason as the pipeline. A flaky judge = a flaky harness. Deterministic judge → run-to-run reproducible eval.
- **Judge rubric calibrated for semantics** — PASS on different wording / extra detail / omitted code; FAIL only on contradiction / missing key point / wrong. This is _why_ an LLM judge over keyword matching (which fails correct-but-differently-worded answers AND passes wrong answers containing the right tokens — can't detect negation).
- **Rich failure message** — prints question, expected, actual, judge verdict → lets you eyeball whether the _judge_ was wrong vs. the _system_ was wrong. Debuggability is the point of an eval.

### The self-grading tradeoff (design-level)

Generator and judge are the same model (`settings.llm_model`) → self-bias risk. **Chosen for simplicity in a portfolio project**, with a known upgrade path: a different/stronger judge model, which the **provider-agnostic layer makes a config change**. (Full concede→explain→fix in RAG doc §13.) The mitigation being trivial is a direct payoff of the §2 provider-agnostic design.

### Cost/scale note

Each run = N generate + N judge calls (12+12=24 here), serial. Fine at this scale; at scale you'd cache generations / batch judges. Explains why big evals get slow/expensive.

---

## Phase status

- **Phase 0 ✅** — scaffold: uv, Docker/Qdrant, typed config, FastAPI `/health`, Groq smoke test.
- **Phase 1 ✅** — ingestion: per-file chunking, local bge-small embeddings, Qdrant upsert with deterministic IDs, search CLI verified (`"declare a path parameter"` → top-5 all from `path-params*.md`, top score 0.8357).
- **Phase 2 ✅** — retrieval + generation (non-streaming, console): `retrieve()`, grounded prompt + citation stitching in `generate.py`, `ask.py` CLI prints answer + Sources. Citation numbering aligned (same ordered list in prompt + footer).
- **Phase 3 ✅** — streaming API: `POST /ask` SSE endpoint, `stream_events()` typed-event generator (`sources`/`token`/`done`), sync generator in Starlette threadpool. `curl` streams a cited answer.
- **Phase 4 ✅** — eval harness: `golden_qa.json` (12 pairs) + `test_eval.py` (pytest, parametrized, LLM-as-judge, temperature 0). Prints per-question PASS/FAIL with rich diagnostics.
- **Three pieces written by hand (learning goals):** `retrieve()` (P2 ✅), streaming `/ask` (P3 ✅), LLM-judge prompt (P4 ✅).
- **Next:** Phase 5 — polish (work the backlog below + README + refusal test).

### Known gaps / hardening backlog (mostly Phase 5)

- **No mid-stream error handling** — LLM error after streaming starts propagates out of the generator, SSE socket dies, client can't distinguish clean completion from failure. Fix: 4th event type `error` from a `try/except` inside the generator.
- **`part.choices[0]` can IndexError** — some final chunks carry `choices: []`. Guard: `if part.choices and part.choices[0].delta.content`.
- **Sources = retrieved, not used** — footer lists all `k`, not only cited passages.
- **Sync streaming caps concurrency** at ~threadpool size (see §8). Async is the upgrade.
- **Provider-agnostic naming leak** — `settings.groq_api_key` should be `llm_api_key` to match the generic `llm_base_url` and back the provider-agnostic claim.
- **`answer` typed `str` but can be `None`** in non-streaming path — guard `content or ""`.
- **Prompt duplication** between `generate_answer` and `stream_events` — extract `_build_messages()`.
- **Mixed indentation** (2-space old code, 4-space new) — run `ruff format` / `black` (also fixes PEP 8 → 4-space).
- **Stale docstring** in `api.py` ("Phase 0: health check only").
- **[P4] No refusal test** — highest-value gap: the "refuses rather than hallucinates" safety property is untested. Add 1–2 out-of-scope golden questions expecting "I don't know," with a refusal-specific judge rubric.
- **[P4] `.strip()` on possibly-`None`** in `judge()` — same bug pattern as `generate.py`; guard `(content or "").strip()`.
- **[P4] `None` answer flows into judge** — a `None` from `generate_answer` becomes the literal string "None" and gets graded; should be an explicit FAIL with a clear reason.
- **[P4, stretch] Component-level eval** — retrieval-only check keyed on expected source file, to isolate retrieval misses from generation misses.
- **[P4, stretch] Stronger/different judge model** — breaks the self-grading loop; trivial via the provider-agnostic layer.
