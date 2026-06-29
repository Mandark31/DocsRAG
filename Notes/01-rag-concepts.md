# DocsRAG — RAG Concepts (through Phase 1)

> Personal study notes. Goal: be able to defend every concept cold in an interview.
> Scope: everything conceptual we've covered building DocsRAG up to the end of ingestion.

---

## 1. The end-to-end mental model

RAG = **Retrieval-Augmented Generation**. Two halves:

- **Retrieval** (search engineering): find the text relevant to a question.
- **Generation** (LLM orchestration): turn that retrieved text into a written answer.

One-line definition: *"Search, then summarize the results with an LLM that's been told to stay grounded in them."*

**Query-path flow (5 steps):**
1. **Embed the question** — same embedding model as ingestion → a 384-dim vector.
2. **Vector search** — Qdrant does approximate-nearest-neighbor, returns top-k chunks by cosine similarity.
3. **Assemble the prompt** — top-k chunks + question + instruction ("answer only from this context, cite sources").
4. **Generate** — send to the LLM (Groq / Llama 3.3 70B), stream the response.
5. **Return answer + citations** — relay tokens with inline markers tying claims back to chunk sources.

**The key split:** ingestion is **offline** (runs once, ahead of time, builds the index); retrieval is **online** (runs live on each query, reads the index). Phase 1 built the offline half.

**Where quality lives:** most RAG wins and most RAG failures live in **retrieval**, not in the model. If retrieval feeds the LLM the wrong chunks, even a perfect model gives a wrong answer.

---

## 2. The ingestion pipeline (offline half)

Four-stage transformation, each a distinct concern:

```
load .md files → chunk into pieces → embed each chunk → upsert vectors into Qdrant
```

---

## 3. Chunking

### Why chunk at all
1. **Embeddings are fixed-size regardless of input length.** Embed a whole 5000-word doc into one vector and it becomes a blurry *average* of every topic — it won't sit close to any specific question. Smaller, focused chunks = sharper vectors.
2. **Retrieval feeds chunks into the prompt.** You want to retrieve a relevant *passage*, not a whole document — to stay within context limits and keep the prompt focused.

### The core tradeoff
- **Too small** → precise vectors, but a single chunk may lack enough context to answer.
- **Too large** → plenty of context, but blurry vectors (averaging problem), less precise retrieval, wasted prompt space.
- **1000 chars** = middle-ground default. *Not a tuned value* — a starting point you'd adjust based on eval results.

### Overlap (150 chars) — the subtle part
Fixed-size chunking cuts text at **arbitrary positions** (blind to sentence/paragraph boundaries). Without overlap, a boundary can slice a key idea in half — setup at the end of chunk 3, payoff at the start of chunk 4, neither chunk alone can answer.
**Overlap repeats the last 150 chars of each chunk at the start of the next**, so an idea straddling a boundary survives intact in at least one chunk. Cost: mild redundancy. Cheap insurance against arbitrary cuts.

### Stride
With overlap, consecutive chunks advance by `CHUNK_SIZE − CHUNK_OVERLAP = 1000 − 150 = 850` chars (the "stride"), not a full 1000.

### Chunk count math (how 138 arose)
Chunking is **per-file**, not over one concatenated blob (a chunk must never straddle two unrelated docs — keeps each chunk traceable to one source for citations).

Per file: `chunks ≈ ceil((file_chars − overlap) / stride) = ceil((file_chars − 150) / 850)`
Total = sum across all 15 files = **138**. (Nothing to do with the 384 embedding dimension — that's decided later, at embedding, after the count is already fixed.)

### "Naive" framing (say this in interviews)
This is **naive fixed-size character chunking**, chosen deliberately as a baseline: simple, works, easy to reason about. Known weakness: blind to document structure. Smarter strategies: split on markdown headers, on sentence/paragraph boundaries, recursively. Philosophy: **baseline first, measure with the eval harness, then improve.**

---

## 4. Embeddings — the conceptual core

An **embedding** is a function turning text into a vector (384 floats here), positioned in high-dimensional space so that **similar meaning → geometrically close, unrelated meaning → far apart**.

It captures *meaning*, not words: "feline" lands near "cat" despite zero shared letters. The trick: converts the fuzzy human notion of "relevant" into the precise mathematical notion of "nearby."

### Model: `BAAI/bge-small-en-v1.5`
- `bge` = model family, `small` = size variant (smaller = faster, less accurate; base/large exist), `en` = English.
- Run **locally** via `fastembed` (model downloaded + cached on disk; embedding happens on-machine, no API call).
- **Why local:** embeddings are computed constantly (every chunk at ingest, every query at retrieval) → no per-embedding cost, no network latency, no rate limits, text never leaves the machine. Tradeoff: smaller/less powerful than a paid embedding API; fine here, tunable later.

### 384 dimensions
- A **property of the model** — bge-small always emits 384 floats. You don't choose it; the model dictates it.
- **Hard coupling:** the Qdrant collection was created with vector size 384 *because* that's what this model emits. If they disagree, **upserts fail outright**. Swapping to a different-dimension model means recreating the collection.

### Same model on both sides — non-negotiable
Embed chunks (ingest) and queries (retrieval) with the **same** model. Two **independent** reasons:

1. **Dimensions must match (mechanical constraint).** Collection expects 384-dim; a 512-dim vector is rejected. **Fails loud** — you notice instantly.
2. **Geometric space must match (semantic constraint).** Each model learns its *own* arrangement of meaning during training. Two *different* models can both output 384 dims (constraint 1 satisfied, no error) and still be incompatible — each dimension *means* something different, so the same concept lands at different coordinates. Cosine distance across them is comparing two unrelated maps: the math runs, the number is meaningless. **Fails silent** — no error, just quietly wrong results.

> Critical insight: matching dimensions does NOT mean matching spaces. The silent failure (reason 2) is the dangerous one.

### Query vs. document embedding
bge-style models sometimes embed *queries* slightly differently from *documents* (small instruction prefix on the query). That's why having distinct `embed_query()` vs `embed_texts()` functions is good design — separate by intent, both routing through the same underlying model.

---

## 5. Cosine similarity

### What it measures
The **angle** between two vectors, ignoring magnitude. Meaning is encoded in **direction**, so "how similar?" = "how close are the directions?" = "how small is the angle?"

- angle 0° → cos = **1.0** (identical direction, max similar)
- angle 90° → cos = **0.0** (perpendicular, unrelated)
- angle 180° → cos = **−1.0** (opposite)

A score of **0.83** = small angle (~34°), directions nearly aligned, meanings nearly the same. Higher = more relevant. The *ranking* and *gaps between scores* matter more than the absolute number.

### Why direction, not magnitude
For text embeddings, meaning lives in direction. You don't want a longer chunk to score higher just because its vector happens to be longer. Cosine asks the question you care about ("same meaning?") and ignores the one you don't ("same length?").

### Why "similar direction = similar meaning" is true
**Training.** The model is optimized on huge text corpora with a signal like "similar-meaning texts → push vectors to point the same way; unrelated → push apart." Over billions of examples it learns an arrangement where direction encodes meaning. So it's not a coincidence cosine exploits — it's the property the model was *built* to produce. The model arranges meaning as direction; cosine reads it back.

### The formula
```
cos(θ) = (A · B) / (|A| × |B|)
```
Numerator (dot product) is large when vectors point the same way. Denominator (product of magnitudes) **divides length back out** → magnitude-independent. Literally "dot product, then strip away length."

### Normalization nuance
bge embeddings are **normalized** (every vector scaled to length 1). When all vectors are length 1, the denominator = 1×1 = 1, so **cosine collapses to the dot product** — identical ranking. Hence "cosine vs dot product doesn't matter here" *for normalized vectors*.

---

## 6. The vector store (Qdrant) — conceptually

### Why a vector DB at all
Brute-force "compute distance to every vector and sort" works for 50 chunks, dies at 50k–5M. "Find nearest vectors fast among millions" is genuinely hard. Qdrant uses **approximate-nearest-neighbor (ANN)** index structures + persistence + filtering + concurrency. It's the storage-and-search engine at the center of retrieval — the "search" half of RAG.

### Collection
A named container for vectors of a fixed **size** (384) and **distance metric** (COSINE) — like a table. Metric must match what the model was trained for (bge → cosine).

### Points & payload
A stored "point" = ID + vector + **payload** (arbitrary metadata: chunk text, source filename, position).
- The **vector** finds the match (similarity search).
- The **payload** carries the human-meaningful content + source info.
- Payload `source`/`position` are stored *because citations (Phase 2/3) will need them.* The vector locates; the payload is what becomes a citation.

---

## 7. RAG vs. alternatives (THE architectural question)

### RAG's real purpose
Inject relevant, current, private, or authoritative info into the model's context **at query time**, so answers are grounded in *your* source of truth and can be **cited** back to it. Value = grounding + attribution + controllability.

### RAG vs. training/fine-tuning
> **Training changes what the model *is*; RAG changes what the model *sees*.**
> Training = memorization in the weights; RAG = open-book retrieval at query time.

| Dimension | RAG | Training / fine-tuning |
|---|---|---|
| Update knowledge | Re-ingest (minutes, no model change) | Retrain/fine-tune (slow, expensive) |
| Attribution / citations | Knows which chunk → can cite | Knowledge dissolved into weights → **cannot cite** |
| Hallucination control | "Answer only from context, else say so" | Blends your data with everything; confidently invents |
| Cost / access | Laptop + API key | Training a 70B model is out of reach for most |
| Remove / forget data | Delete the points, done | Knowledge smeared across weights — can't cleanly excise |

Citations are **literally impossible** with pure training — and they're DocsRAG's headline differentiator, falling out of the architecture for free.

### Why use an LLM at all (vs. just retrieval)
Retrieval returns *relevant raw passages*, not an *answer*. The LLM does **synthesis**: read the chunks, understand the question, compose a direct fluent answer pulling the relevant thread out of documentation prose. **Retrieval finds; the LLM phrases.** Without the LLM you've built a search engine; with it, something that answers.

### Why not just paste the 15 docs into a chat?
Honest senior framing: **for 15 docs, pasting works — and I'd say so.** RAG is justified by what 15 *becomes*:

- **Context window limits** — 15 docs fit; 15,000 don't, in any model. RAG feeds only the handful of relevant chunks per query → scales to millions.
- **Cost & latency** — pasting processes the whole corpus on *every* question; RAG sends ~5 small chunks regardless of corpus size. Pasting cost scales with corpus; RAG stays flat.
- **Signal-to-noise** — stuffing mostly-irrelevant text *degrades* answer quality (needle lost in haystack). Feeding only relevant chunks often gives *better* answers than dumping everything, even when everything fits.
- **It's a system, not a task** — RAG is an automated, queryable API other software can call; pasting is a one-off human act.
- **Persistence/reuse** — ingest once into a persistent index, reuse across unlimited queries/users; pasting re-sends every conversation.
- **Citations** — retrieval hands you each chunk's source as a structured fact; built-in, not coaxed.

> The senior move is knowing **when *not* to use RAG.** DocsRAG uses 15 docs as a tractable stand-in to build and prove the architecture end-to-end.
