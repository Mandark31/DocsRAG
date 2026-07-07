# DocsRAG — Python & Programming Concepts (through Phase 4)

> Personal study notes for a .NET dev learning Python/FastAPI.
> C#/.NET analogies included where they genuinely fit; concept stated directly first.

---

## 1. Python has no per-project isolation by default

The biggest mental shift from .NET. In .NET, every project is naturally sandboxed (deps in its own build output, SDK pinnable via `global.json`, nothing leaks). Python is the opposite: `pip install` dumps packages into a **global** site-packages shared by every project → version collisions.

- **Virtual environment (`.venv`)** — the historical fix: a per-project folder of isolated packages.
- **uv** collapses three tools into one:
  - Python _version_ manager — pinned 3.12 via `.python-version` (≈ `global.json`), system 3.9.6 untouched.
  - virtualenv manager — creates/manages the `.venv`.
  - dependency resolver/installer (≈ NuGet restore).
- `uv run <cmd>` = "run this command _inside_ the project's isolated env with the right Python + deps" (≈ `dotnet run`'s guarantee you're using resolved deps).
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
- FastAPI uses them for request/response models _and_ auto-generates Swagger from them.
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
2. **In-memory cache (`@lru_cache`)** — "already loaded weights from disk into RAM _this process_, don't reload." Lives only for the process lifetime.

Lifecycle: first embed ever → fastembed downloads from internet → saves to disk. Every process start → weights read disk→memory (slow). `@lru_cache` ensures that disk→memory load happens **once per process**, not once per call.

### Library vs. weights (two artifacts)

- **`fastembed`** (the dependency) = the _library code_ that runs an embedding model (tokenize, run the net, produce vectors). Small; installed by `uv add`.
- **`BAAI/bge-small-en-v1.5`** (the weights) = the _trained network itself_, hundreds of MB. **Not bundled** — too large; fetched on first use and cached on disk.
- Code vs. data — two distinct things. Adding the dependency gives you only the first.

---

## 6. Generators & `yield` (Phase 3)

`yield` turns a function into a **generator** — produces a sequence _lazily, one at a time_, pausing between values. **Exact analog of C# `yield return` + `IEnumerable<T>`** — the mental model transfers completely.

Mechanics:

- Calling a generator function runs **nothing** — it returns a generator object paused at the top.
- Each "next" request runs the body **until the next `yield`**, hands that value out, and **freezes** — all locals + loop position preserved.
- Next request **resumes from exactly where it froze**. Function end = sequence over.

```python
def stream_events(question, k):
    chunks = retrieve(question, k)
    yield {"type": "sources", ...}      # produce, FREEZE
    for part in stream:
        if delta:
            yield {"type": "token", ...}  # produce, freeze, resume...
    yield {"type": "done"}               # final, then done
```

- **Laziness is the point for streaming:** each token is yielded the instant the model emits it, not after computing the whole answer. Contrast `generate_answer` (`return answer, chunks` — computes everything, hands back one result) vs `stream_events` (hands back values as it goes).
- **A generator's body doesn't run until iterated.** Call `stream_events(...)` and never loop → `retrieve()` never executes. It's a recipe, dormant until consumed (≈ C# `IEnumerable` deferred execution).

---

## 7. `Iterator[dict]` return type (Phase 3)

The type hint for "returns a generator that yields `dict` values" ≈ C# `IEnumerable<Dictionary<...>>`.

- `Iterator[X]` = "iterable producing values of type `X`." Each yielded event is a `dict` → `Iterator[dict]`.
- Imported via `from collections.abc import Iterator`. Documentation + tooling only; not runtime-enforced.
- **`Iterable` vs `Iterator`:** `Iterable` = anything you _can_ start iterating (list, range, generator); `Iterator` = the thing actually _producing_ values as you advance it. A generator is **both**, so either hint is valid.
- `Generator[dict, None, None]` is the _more specific_ hint (also captures `.send()` input + return value — both `None` for us). `Iterator[dict]` is the clean choice when you don't use those. (≈ `IEnumerator<T>` vs `IEnumerable<T>`.)

---

## 8. `delta` — the streaming increment (Phase 3)

`delta` = **the small new piece of text in one streaming chunk** — the _increment_, not the cumulative answer. Deliberate word: "the change / new addition."

Access path `part.choices[0].delta.content`:

- `part` — one streaming chunk that arrived.
- `.choices[0]` — first (only) candidate completion.
- `.delta` — the incremental-update object (streaming). _(Non-streaming uses `.message` = the whole answer.)_
- `.content` — the new text string in this delta.

The full answer = **concatenation of all deltas in order**; the client glues them as they arrive (≈ read-file-line-by-line: you don't know how many, you read until end).

**Why `if delta:` guards:** some chunks have `delta.content = None` — the first chunk carries a _role_ delta (`role="assistant"`, no content), the final often has empty/`None` content while signaling finish. Skip those; only emit a token event on real text. Without the guard you'd yield `{"text": None}` noise.

---

## 9. Nested functions & closures (Phase 3)

```python
@app.post("/ask")
def ask(request: AskRequest) -> StreamingResponse:
    def event_stream():                      # nested function
        for event in stream_events(request.question, request.k):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- **Nested/inner function** — defining a function inside a function. Normal + idiomatic. ≈ C# **local function** (and closely related to a lambda/closure).
- **Closure** — `event_stream` references `request` from the enclosing scope; it "closes over" that variable and can use it **even when run later**, elsewhere (inside Starlette's machinery, after `ask` has returned). Exactly what C# closures/local functions do.
- **Why write it this way:**
  1. `StreamingResponse` needs a generator to iterate, and that generator needs the request data. Nesting lets it grab `request.question`/`k` from the closure — no passing around. We return `event_stream()` (note the **call** — creating the generator object); Starlette iterates it _after_ `ask` returns; the closure keeps `request` alive/reachable.
  2. It's scoped exactly where used — an implementation detail of this one endpoint, kept out of the module namespace (≈ C# private local function).

---

## 10. The iterator protocol — how a `for` loop knows when it's done (Phase 3)

`for part in stream` doesn't know a length. It repeatedly asks the iterator "**give me the next item**": either gets one (body runs, ask again) or receives the **"exhausted" signal** (`StopIteration`, raised invisibly, caught by `for`, loop ends). This is how **every** Python for-loop ends — list, range, file, or LLM stream. No length; only "next item" or "I'm done."

For the **LLM stream** specifically, `stream` wraps the **open network connection to Groq**:

- Asking for next → **reads from the network**, waits for the next chunk of bytes (this blocking wait is why a thread is held the whole stream — see §11 / architecture §8).
- **When is it done?** Groq's OpenAI-compatible SSE stream ends with an explicit sentinel line — `data: [DONE]`. The SDK's stream object sees it → stops reading → raises `StopIteration` → your `for` ends.
- **The producer decides when done and tells you** via the sentinel; the consumer just loops until told. Your code is decoupled from _how many_ tokens (5 or 500 → identical loop).

**Same pattern at both boundaries:** Groq signals done via `[DONE]` → your `stream_events` loop ends → _your_ generator signals done by yielding `{"type": "done"}` then falling off the end (same `StopIteration` to Starlette's loop). Consumer of one stream, producer of another; identical contract.

---

## 11. `StreamingResponse` — two loops, one pipe (Phase 3)

**There are two separate iterations on two machines connected by a network pipe** — NOT one shared loop.

- **Server:** Starlette iterates your generator — each `yield`ed SSE frame → written as bytes to the open HTTP socket → **flushed immediately** (pushed now, not buffered) → asks the generator for the next.
- **Client:** iterates the _incoming byte stream_ off the same socket (JS: `response.body.getReader()` + `reader.read()` loop), parsing SSE frames into events. It can't "iterate your generator" — that lives on the server.
- **Chain:** your `yield` → Starlette writes bytes → network → client reads bytes → client parses events.
- The connection is a normal HTTP response that **stays open and dribbles data** (chunked transfer) instead of "compute whole body, send, close." Generator exhaustion (after `done`) closes it.

---

## 12. async — the scaling version (Phase 3)

- Everything in §6–§11 is the **synchronous** generator machinery (≈ C# `yield return` + `IEnumerable<T>` + local functions/closures).
- **Async flavor:** `async def` + `async for` + `AsyncIterator[dict]` ≈ `IAsyncEnumerable<T>` with `await foreach`.
- `asyncio` ≈ `async`/`await` + `Task`.
- **ASGI** = the async-native server↔app standard (uvicorn ↔ FastAPI); async-native is what makes streaming clean.
- **The scaling point (see architecture §8):** sync stream generators run in Starlette's bounded threadpool (~40), one thread held per concurrent stream → caps concurrency. Async puts each stream on the event loop as a coroutine → thread **released while awaiting each token** → tiny thread count serves huge concurrency. "The same, but the thread is released during the await."

---

## 7. Framework / runtime mapping (quick reference)

| Python / FastAPI                    | .NET                                                    |
| ----------------------------------- | ------------------------------------------------------- |
| Pydantic model                      | DTO / record (with runtime validation)                  |
| pydantic-settings `Settings`        | `IOptions<T>` from config, fail-fast                    |
| FastAPI `Depends`                   | DI container registration + constructor injection       |
| FastAPI                             | ASP.NET Core minimal APIs                               |
| uvicorn                             | Kestrel                                                 |
| ASGI                                | the Kestrel↔middleware-pipeline contract (async-native) |
| `pyproject.toml` / uv               | `.csproj` / NuGet                                       |
| `uv.lock`                           | `packages.lock.json`                                    |
| `.python-version`                   | `global.json`                                           |
| `.whl` wheel                        | `.nupkg`                                                |
| hatch (build backend)               | MSBuild step producing the artifact                     |
| pytest                              | xUnit                                                   |
| `@lru_cache` lazy singleton         | `Lazy<T>` as singleton                                  |
| `yield` / generator                 | `yield return` / `IEnumerable<T>`                       |
| `Iterator[dict]` / `Iterable[dict]` | `IEnumerator<T>` / `IEnumerable<T>`                     |
| nested function + closure           | local function / lambda closure                         |
| `StopIteration` (loop-end signal)   | end-of-`IEnumerator` (`MoveNext()` → false)             |
| `async def` + `async for` (SSE)     | `IAsyncEnumerable<T>` + `await foreach`                 |
| `asyncio`                           | `async`/`await` + `Task`                                |
| sync gen in threadpool              | blocking I/O on `Task.Run` threads                      |
| async gen on event loop             | real `async/await` over async I/O                       |
| `--reload`                          | `dotnet watch`                                          |

---

## 8. CLI / run notes

- Ad-hoc commands need `PYTHONPATH=src` (consequence of the src layout). Convenience shortcut deferred to Phase 5.
- Run server: `uv run uvicorn docsrag.api:app --reload --app-dir src` → `/docs` (auto Swagger) + `/health`.
- Restart infra: `docker compose up -d` (data persists in the `qdrant_storage` volume).
- Ask (non-streaming CLI, P2): `PYTHONPATH=src uv run python -m docsrag.ask "your question"` → answer + Sources footer.
- Ask (streaming API, P3): `POST /ask` with JSON `{"question": "...", "k": 5}` → SSE stream of `sources`/`token`/`done` events. Verify with `curl -N` (the `-N`/`--no-buffer` flag is what lets you _see_ it stream rather than buffering the whole response).

---

## 13. pytest — testing, for a .NET dev (Phase 4)

### Convention-based, not attribute-based

Biggest surprise from xUnit: pytest **discovers** tests by naming, no `[Fact]` needed.

- `test_*.py` files → test files.
- `test_*` functions → test cases.
- `Test*` classes → test classes.
  Naming **is** the registration. `judge()` (not `test_`-prefixed) is ignored as a test → it's just a helper. Run with `uv run pytest` (or `PYTHONPATH=src uv run pytest` for the src layout) ≈ `dotnet test`.

### Plain `assert`, no assertion library

`assert <condition>, "<message if it fails>"` — Python's built-in keyword, not `Assert.Equal(...)`. pytest **rewrites** asserts so failures show the actual values (rich diff), so you get xUnit-quality output from a language keyword. `assert answer == expected` prints both on failure.

### `@pytest.mark.parametrize` — the one decorator (≈ `[Theory]`+`[MemberData]`)

```python
@pytest.mark.parametrize("case", GOLDEN, ids=[c["question"] for c in GOLDEN])
def test_answer_is_correct(case):
    ...
```

- `"case"` = **name of the injected parameter**; matches the function arg `def ...(case)`.
- `GOLDEN` = **list of values** → the test runs once per item.
- `ids=[...]` = **human-readable label per run** → failures name the actual question (without it: `[case0]`, `[case1]`…, useless).
- One function definition → **12 independent tests.** All run even if some fail; independent pass/fail. Beats a `for` loop inside one test (which stops at the first failure and hides the rest).
- **Injection model (pytest's signature feature):** _you_ never pass `case`; the function _declares_ a parameter and pytest _supplies_ it. Same mechanism powers **fixtures** (pytest's DI for setup — ≈ constructor injection / `IClassFixture`): declare a parameter, pytest matches it to a data source or setup function by name. (Not used yet, but now it won't surprise you.)

### File-path & data-loading idioms

```python
GOLDEN = json.loads((Path(__file__).parent / "golden_qa.json").read_text())
```

- Runs **once at import time** (module level).
- `__file__` = path to this source file. `Path(...)` = `pathlib.Path` (≈ richer `FileInfo`).
- `.parent` = the containing directory.
- `/ "golden_qa.json"` = `pathlib` overloads `/` as **path-join** (not division) when the left side is a `Path`.
- **Why not bare `open("golden_qa.json")`:** a bare filename is relative to _where you ran pytest from_, not the test file. `Path(__file__).parent / ...` anchors to the test file's own location → works from any CWD. Kills "works here, not there" path bugs.
- `.read_text()` = whole file → string. `json.loads(...)` = parse JSON string → Python objects (`loads` = "load string"; array → `list` of `dict`).

### Small Python idioms in this file

- **Tuple return + unpack:** `judge` returns `(passed, verdict)`; caller does `passed, verdict = judge(...)`. Lightweight multi-return (vs C# out-params / a small class).
- **`_` throwaway:** `answer, _ = generate_answer(...)` — `_` = "I don't need this value" (the chunks).
- **List comprehension:** `[c["question"] for c in GOLDEN]` = `[expression for item in iterable]` — compact "build a list by looping."
- **Adjacent-string / f-string concatenation:** stacked `f"\n..."` literals with no `+` auto-join into one string; each `\n` = newline for readable multi-line failure output.

### Mental map

| This file                        | xUnit                                      |
| -------------------------------- | ------------------------------------------ |
| `test_*.py` file / `test_*` func | `[Fact]` / `[Test]`                        |
| `@pytest.mark.parametrize`       | `[Theory]` + `[MemberData]`/`[InlineData]` |
| `assert passed, "msg"`           | `Assert.True(passed, "msg")`               |
| `case` param filled by pytest    | params from `[MemberData]`                 |
| non-`test_` helper (`judge`)     | private helper method                      |
| fixtures (not used yet)          | ctor injection / `IClassFixture`           |
| `uv run pytest`                  | `dotnet test`                              |
