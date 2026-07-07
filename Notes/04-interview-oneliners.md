# DocsRAG — Interview One-Liners (through Phase 4)

> Skim this before an interview. Just the load-bearing framings — the sentences that, said cleanly, prove you understand the _why_. Full reasoning lives in the other three docs.

---

## RAG, big picture

- **"Training changes what the model _is_; RAG changes what the model _sees_."**
- **"Training is memorization in the weights; RAG is open-book retrieval at query time."**
- "RAG = retrieval (find the right text) + generation (turn it into an answer). **Retrieval finds; the LLM phrases.**"
- "Most RAG wins and most RAG failures live in **retrieval**, not the model."
- "Ingestion is offline and builds the index; retrieval is online and reads it."

## When NOT to use RAG (the senior move)

- **"For 15 docs, pasting into a chat works — and I'd say so. RAG is justified by what 15 _becomes_."**
- "RAG earns its place at scale: corpus too big for any context window, data that must stay current, verifiable citations, and running as an automated service rather than a human pasting text."
- "Stuffing the model with mostly-irrelevant text _degrades_ answers — less-but-relevant beats more-but-noisy. RAG feeds only the relevant chunks."
- "Pasting cost scales with corpus size; RAG cost stays flat — ~5 chunks per query regardless of corpus size."

## Citations

- **"Citations are literally impossible with pure training — the documents are dissolved into the weights. RAG knows which chunk produced the answer, so attribution falls out of the architecture for free."**

## Chunking

- "1000 chars is a **baseline default, not a tuned value** — I'd let the eval harness tell me whether to adjust it or move to structure-aware chunking."
- "Overlap is insurance against arbitrary cuts: an idea straddling a boundary survives intact in at least one chunk."
- "This is **naive fixed-size chunking, chosen deliberately** — baseline first, measure, then improve."

## Embeddings — same model both sides

- **"Matching dimensions does NOT mean matching spaces."**
- "Two reasons the model must match: dimensions (mechanical — **fails loud**, the upsert is rejected) and geometric space (semantic — **fails silent**, retrieval just returns garbage). **The silent one is the dangerous one.**"
- "Each model learns its own arrangement of meaning during training; a vector from model A and model B aren't comparable even at the same dimension count."

## Cosine

- "Cosine measures the **angle**, not the magnitude — because meaning lives in **direction**, and I don't want a longer chunk to score higher just for being longer."
- "The formula divides out magnitude: dot product, then strip away length."
- "bge vectors are normalized to length 1, so cosine collapses to the dot product — same ranking either way."
- "Training arranges meaning as direction; cosine reads that direction back out. Not a coincidence — it's the property the model was built to produce."

## src layout

- **"The src layout forces importing the package _by name_, the way installed code must — not _by happening to be in the same folder_."**
- "It catches the 'works locally, missing after install' class of bug before prod."
- "The explicit `packages=[...]` line is a **build-time** concern, not a deploy-time one — moving the package into `src/` breaks build-tool auto-detection, so I point the tool at it."

## Provider-agnostic LLM layer

- "'OpenAI-compatible' is a **de facto wire protocol**, not an official spec — Groq exposes the same `/chat/completions` shape, so the OpenAI SDK works against it by swapping `base_url` + key."
- **"One source of truth for `base_url`/`key`, read everywhere — so swapping providers changes everything atomically, in one place."**
- "It's the Adapter / anti-corruption layer pattern — Dependency Inversion applied to model providers."

## Fail-fast config

- **"Fail-fast turns a runtime error into a deploy-time error — so orchestration catches it instead of users."**
- "A missing key becomes a _failed deployment_ (safe, automated rollback) rather than a _production incident_ (pages, debugging, angry users) — because the health check never goes green."

## Docker

- "Containerize the thing you _depend on_ (Qdrant — set once, isolated); keep the thing you're _changing_ native (the app — `--reload`, fast iteration)."
- "'Is the app containerized?' depends on lifecycle stage — native in dev for speed, containerized in prod for reproducibility. That's why Phase 5 has a Dockerfile."
- "Compose **orchestrates** containers; a Dockerfile **builds** one image. Right now Compose pulls a pre-built Qdrant image — I didn't build it."
- "The named volume is why my vectors survive a restart — without it, every `down`/`up` gives an empty DB."

## Re-ingestion / no duplicates

- **"Same content → same deterministic ID → upsert overwrites in place rather than inserting. That's why 138 chunks stay 138, not 414."**
- "Deterministic IDs alone do nothing — it's the _pairing_ with upsert that de-duplicates. The idempotent collection setup is just hygiene."

## Chunk count

- "138 isn't `total_chars / 384` — the 384 is the embedding dimension, decided _after_ chunking. 138 is per-file chunking summed across 15 files, with an 850-char stride (1000 − 150 overlap)."
- "Chunking is per-file, not over a concatenated blob — so no chunk straddles two documents, and every chunk traces to exactly one source for citations."

## @lru_cache lazy singleton

- "Loading the embedding model is expensive (hundreds of MB disk→RAM); `@lru_cache` makes that load happen **once per process**, not once per call. Lazy + singleton — like `Lazy<T>` as a singleton."
- "Two caches, two problems: **disk cache** (don't re-download from the internet, handled by fastembed) and **in-memory cache** (don't reload from disk per call, handled by `@lru_cache`)."
- "The **library** (fastembed) and the **weights** (bge-small) are two artifacts — the dependency ships the code; the weights are fetched on first use and cached on disk."

## Retrieval & generation (Phase 2)

- "`retrieve()` = embed the query (same model as ingestion) → vector-search Qdrant → reconstruct chunks from the payload. The vector finds the match; the payload is what I cite."
- "I discarded the retrieval score — fine for now, but it's the one _mechanical_ lever for 'docs don't cover this': a low top score could refuse _before_ the LLM call."
- **"Grounding is one prompt instruction: 'answer only from this context, else say you don't know.' That's the primary hallucination lever."**
- **"Citation numbers are trustworthy because the _same ordered list_ is used in both the prompt and the sources display — the prompt asks the model to cite by number, but the mapping to real files is structural, not the model's cooperation."**

## Grounded refusal (the "I don't know" property)

- **"A grounded RAG system refuses rather than hallucinates — 'I don't know' is an engineered feature, not a gap."**
- "Two separate failure modes: chunks-don't-contain-the-answer → model says 'I don't know' _by design_; API returns `None` content → a response-shape edge case fixed with `or ""`. Don't conflate them — in the first, content is a normal string that says 'I don't know'."
- **"The prompt _instructs_ refusal but doesn't _enforce_ it — so the eval harness exists to _verify_ it. Prompt asks → eval verifies → retrieval score could enforce."**

## temperature = 0

- "Temperature 0 for two reasons: grounding not creativity (there's a correct answer to report, not embellish), and **reproducibility for evals** — output must be a stable function of input or eval scores are noise."

## Streaming citations (Phase 3)

- **"Streaming breaks the 'sources footer at the end' model, so I made the response a stream of typed events — `sources` up front, then `token`s, then `done`."**
- **"Sources go up front so every inline `[n]` marker is resolvable the instant it streams in — sources-at-the-end would leave citations dangling until completion."**
- "`done` isn't decorative — it's how the client knows the stream ended _cleanly_ vs. the socket dropping. Every stream ends in exactly one terminal event: `done` or `error`."
- "`done` is the echo of Groq's `[DONE]` sentinel — I'm a consumer of Groq's stream and a producer of my own, same 'emit then signal exhaustion' contract."
- "Two stacked generators: `stream_events` yields domain event-dicts (transport-agnostic); `event_stream` wraps them as SSE frames. One produces meaning, the other formats for HTTP."

## SSE vs WebSocket / POST

- **"The answer stream is strictly one-directional, so SSE fits — WebSocket would be over-engineering: bidirectional complexity and lost HTTP-friendliness to gain a return channel I don't use."**
- "SSE is just a long-lived HTTP response that flushes text frames; WebSocket is a two-way channel after an HTTP upgrade."
- "POST because I send a request body, and because the browser's native `EventSource` is GET-only/no-body — SSE-with-a-payload uses POST + `fetch` streaming."

## Sync vs async streaming (THE Phase 3 question)

- **"Sync works because Starlette runs sync stream generators in a bounded threadpool (~40), off the event loop — so blocking calls don't stall it."**
- **"The ceiling: a streaming generator holds its thread for the _whole stream duration_, so I cap at ~40 concurrent streams. The 41st waits."**
- **"Async fixes it: each stream becomes a coroutine on the event loop, and the thread is _released while awaiting each token_ — a few threads serve thousands of streams."**
- "Sync-in-threadpool ≈ blocking I/O on `Task.Run` threads; async ≈ real `async/await` over `IAsyncEnumerable<T>`."

## Mid-stream error handling

- "No mid-stream error handling yet — an LLM error after the first token propagates out and the socket just dies; the client can't tell clean completion from failure. Fix: a 4th `error` event from a `try/except` inside the generator."
- "Retries help _before_ the first token; once mid-stream, retrying re-emits tokens the client has. So: **retry before first token, error-event after.**"

## Generators / yield (mechanics)

- "`yield` = C# `yield return` — a generator produces values lazily, pausing between each; the body doesn't run until something iterates it."
- "`delta` is the _increment_ — the new text in one streaming chunk; the full answer is all deltas concatenated. `if delta:` skips the role-only first chunk and empty final chunk."
- "`event_stream` is a closure — it captures `request` and stays valid when Starlette iterates it after the handler returns. ≈ a C# local function."
- "A `for` loop ends when the iterator raises `StopIteration` — for the LLM stream, that fires when the SDK sees Groq's `[DONE]` sentinel. No length involved; the producer signals done."

## Eval harness / LLM-as-judge (Phase 4)

- "The eval turns 'I think it works' into a repeatable measurement — run each golden question through the real pipeline, have an LLM judge the answer against a human-written reference."
- **"An LLM judge over keyword matching because I'm grading _meaning, not string similarity_ — keyword matching fails correct answers worded differently AND passes wrong answers that contain the right tokens. It can't detect negation."**
- **"Same model generates and judges — that's a real limitation (self-bias, shared blind spots). I concede it, then: verification is narrower than generation, the human references anchor it, and the fix is a different/stronger judge model — trivial via my provider-agnostic layer."**
- **"What it proves: end-to-end correctness. What it doesn't: _which_ stage failed (system-level, not component-level), and with 12 questions it's a smoke test — 11/12 isn't a real 92%, it's a directional signal."**
- "An eval that honestly states its scope beats one quoting a confident number it can't support."
- **"My proudest property — 'refuses rather than hallucinates' — is currently untested. The highest-value addition is out-of-scope golden questions expecting 'I don't know', which closes the loop: prompt instructs refusal → eval verifies it."**
- "To diagnose the failing stage I'd add a retrieval-only eval keyed on expected source file — checkable mechanically, no judge needed."
- "`temperature=0` on the judge too — a flaky judge makes a flaky harness."
- "`@pytest.mark.parametrize` makes each golden case an independent test — all run even if some fail, and failures name the exact question. Beats a loop that stops at the first failure."

---

## The three things I wrote by hand (and why)

- `retrieve()` (Phase 2 ✅), the streaming `/ask` endpoint (Phase 3 ✅), the LLM-judge prompt (Phase 4 ✅) — implemented myself to internalize retrieval flow, streaming/async, and eval design rather than auto-generating them. All five phases build-complete; Phase 5 is polish.
