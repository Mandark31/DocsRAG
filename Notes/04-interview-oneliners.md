# DocsRAG — Interview One-Liners (through Phase 1)

> Skim this before an interview. Just the load-bearing framings — the sentences that, said cleanly, prove you understand the *why*. Full reasoning lives in the other three docs.

---

## RAG, big picture
- **"Training changes what the model *is*; RAG changes what the model *sees*."**
- **"Training is memorization in the weights; RAG is open-book retrieval at query time."**
- "RAG = retrieval (find the right text) + generation (turn it into an answer). **Retrieval finds; the LLM phrases.**"
- "Most RAG wins and most RAG failures live in **retrieval**, not the model."
- "Ingestion is offline and builds the index; retrieval is online and reads it."

## When NOT to use RAG (the senior move)
- **"For 15 docs, pasting into a chat works — and I'd say so. RAG is justified by what 15 *becomes*."**
- "RAG earns its place at scale: corpus too big for any context window, data that must stay current, verifiable citations, and running as an automated service rather than a human pasting text."
- "Stuffing the model with mostly-irrelevant text *degrades* answers — less-but-relevant beats more-but-noisy. RAG feeds only the relevant chunks."
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
- **"The src layout forces importing the package *by name*, the way installed code must — not *by happening to be in the same folder*."**
- "It catches the 'works locally, missing after install' class of bug before prod."
- "The explicit `packages=[...]` line is a **build-time** concern, not a deploy-time one — moving the package into `src/` breaks build-tool auto-detection, so I point the tool at it."

## Provider-agnostic LLM layer
- "'OpenAI-compatible' is a **de facto wire protocol**, not an official spec — Groq exposes the same `/chat/completions` shape, so the OpenAI SDK works against it by swapping `base_url` + key."
- **"One source of truth for `base_url`/`key`, read everywhere — so swapping providers changes everything atomically, in one place."**
- "It's the Adapter / anti-corruption layer pattern — Dependency Inversion applied to model providers."

## Fail-fast config
- **"Fail-fast turns a runtime error into a deploy-time error — so orchestration catches it instead of users."**
- "A missing key becomes a *failed deployment* (safe, automated rollback) rather than a *production incident* (pages, debugging, angry users) — because the health check never goes green."

## Docker
- "Containerize the thing you *depend on* (Qdrant — set once, isolated); keep the thing you're *changing* native (the app — `--reload`, fast iteration)."
- "'Is the app containerized?' depends on lifecycle stage — native in dev for speed, containerized in prod for reproducibility. That's why Phase 5 has a Dockerfile."
- "Compose **orchestrates** containers; a Dockerfile **builds** one image. Right now Compose pulls a pre-built Qdrant image — I didn't build it."
- "The named volume is why my vectors survive a restart — without it, every `down`/`up` gives an empty DB."

## Re-ingestion / no duplicates
- **"Same content → same deterministic ID → upsert overwrites in place rather than inserting. That's why 138 chunks stay 138, not 414."**
- "Deterministic IDs alone do nothing — it's the *pairing* with upsert that de-duplicates. The idempotent collection setup is just hygiene."

## Chunk count
- "138 isn't `total_chars / 384` — the 384 is the embedding dimension, decided *after* chunking. 138 is per-file chunking summed across 15 files, with an 850-char stride (1000 − 150 overlap)."
- "Chunking is per-file, not over a concatenated blob — so no chunk straddles two documents, and every chunk traces to exactly one source for citations."

## @lru_cache lazy singleton
- "Loading the embedding model is expensive (hundreds of MB disk→RAM); `@lru_cache` makes that load happen **once per process**, not once per call. Lazy + singleton — like `Lazy<T>` as a singleton."
- "Two caches, two problems: **disk cache** (don't re-download from the internet, handled by fastembed) and **in-memory cache** (don't reload from disk per call, handled by `@lru_cache`)."
- "The **library** (fastembed) and the **weights** (bge-small) are two artifacts — the dependency ships the code; the weights are fetched on first use and cached on disk."

---

## The three things I wrote by hand (and why)
- `retrieve()` (Phase 2), the streaming `/ask` endpoint (Phase 3), the LLM-judge prompt (Phase 4) — implemented myself to internalize retrieval flow, async streaming, and eval design rather than auto-generating them.
