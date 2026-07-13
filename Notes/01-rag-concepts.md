# DocsRAG — RAG Concepts (through Phase 5 — build complete)

> Personal study notes. Goal: be able to defend every concept cold in an interview.
> Scope: the full DocsRAG build — ingestion (P1), retrieval + generation (P2), streaming API (P3), eval harness (P4), polish + deployment (P5).

---

## 1. The end-to-end mental model

RAG = **Retrieval-Augmented Generation**. Two halves:

- **Retrieval** (search engineering): find the text relevant to a question.
- **Generation** (LLM orchestration): turn that retrieved text into a written answer.

One-line definition: _"Search, then summarize the results with an LLM that's been told to stay grounded in them."_

**Query-path flow (5 steps):**

1. **Embed the question** — same embedding model as ingestion → a 384-dim vector.
2. **Vector search** — Qdrant does approximate-nearest-neighbor, returns top-k chunks by cosine similarity.
3. **Assemble the prompt** — top-k chunks + question + instruction ("answer only from this context, cite sources").
4. **Generate** — send to the LLM (Groq / Llama 3.3 70B), stream the response.
5. **Return answer + citations** — relay tokens with inline markers tying claims back to chunk sources.

**The key split:** ingestion is **offline** (runs once, ahead of time, builds the index); retrieval is **online** (runs live on each query, reads the index). Phase 1 built the offline half; Phases 2–3 built the online query path (retrieve → generate → stream).

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

1. **Embeddings are fixed-size regardless of input length.** Embed a whole 5000-word doc into one vector and it becomes a blurry _average_ of every topic — it won't sit close to any specific question. Smaller, focused chunks = sharper vectors.
2. **Retrieval feeds chunks into the prompt.** You want to retrieve a relevant _passage_, not a whole document — to stay within context limits and keep the prompt focused.

### The core tradeoff

- **Too small** → precise vectors, but a single chunk may lack enough context to answer.
- **Too large** → plenty of context, but blurry vectors (averaging problem), less precise retrieval, wasted prompt space.
- **1000 chars** = middle-ground default. _Not a tuned value_ — a starting point you'd adjust based on eval results.

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

It captures _meaning_, not words: "feline" lands near "cat" despite zero shared letters. The trick: converts the fuzzy human notion of "relevant" into the precise mathematical notion of "nearby."

### Model: `BAAI/bge-small-en-v1.5`

- `bge` = model family, `small` = size variant (smaller = faster, less accurate; base/large exist), `en` = English.
- Run **locally** via `fastembed` (model downloaded + cached on disk; embedding happens on-machine, no API call).
- **Why local:** embeddings are computed constantly (every chunk at ingest, every query at retrieval) → no per-embedding cost, no network latency, no rate limits, text never leaves the machine. Tradeoff: smaller/less powerful than a paid embedding API; fine here, tunable later.

### 384 dimensions

- A **property of the model** — bge-small always emits 384 floats. You don't choose it; the model dictates it.
- **Hard coupling:** the Qdrant collection was created with vector size 384 _because_ that's what this model emits. If they disagree, **upserts fail outright**. Swapping to a different-dimension model means recreating the collection.

### Same model on both sides — non-negotiable

Embed chunks (ingest) and queries (retrieval) with the **same** model. Two **independent** reasons:

1. **Dimensions must match (mechanical constraint).** Collection expects 384-dim; a 512-dim vector is rejected. **Fails loud** — you notice instantly.
2. **Geometric space must match (semantic constraint).** Each model learns its _own_ arrangement of meaning during training. Two _different_ models can both output 384 dims (constraint 1 satisfied, no error) and still be incompatible — each dimension _means_ something different, so the same concept lands at different coordinates. Cosine distance across them is comparing two unrelated maps: the math runs, the number is meaningless. **Fails silent** — no error, just quietly wrong results.

> Critical insight: matching dimensions does NOT mean matching spaces. The silent failure (reason 2) is the dangerous one.

### Query vs. document embedding

bge-style models sometimes embed _queries_ slightly differently from _documents_ (small instruction prefix on the query). That's why having distinct `embed_query()` vs `embed_texts()` functions is good design — separate by intent, both routing through the same underlying model.

---

## 5. Cosine similarity

### What it measures

The **angle** between two vectors, ignoring magnitude. Meaning is encoded in **direction**, so "how similar?" = "how close are the directions?" = "how small is the angle?"

- angle 0° → cos = **1.0** (identical direction, max similar)
- angle 90° → cos = **0.0** (perpendicular, unrelated)
- angle 180° → cos = **−1.0** (opposite)

A score of **0.83** = small angle (~34°), directions nearly aligned, meanings nearly the same. Higher = more relevant. The _ranking_ and _gaps between scores_ matter more than the absolute number.

### Why direction, not magnitude

For text embeddings, meaning lives in direction. You don't want a longer chunk to score higher just because its vector happens to be longer. Cosine asks the question you care about ("same meaning?") and ignores the one you don't ("same length?").

### Why "similar direction = similar meaning" is true

**Training.** The model is optimized on huge text corpora with a signal like "similar-meaning texts → push vectors to point the same way; unrelated → push apart." Over billions of examples it learns an arrangement where direction encodes meaning. So it's not a coincidence cosine exploits — it's the property the model was _built_ to produce. The model arranges meaning as direction; cosine reads it back.

### The formula

```
cos(θ) = (A · B) / (|A| × |B|)
```

Numerator (dot product) is large when vectors point the same way. Denominator (product of magnitudes) **divides length back out** → magnitude-independent. Literally "dot product, then strip away length."

### Normalization nuance

bge embeddings are **normalized** (every vector scaled to length 1). When all vectors are length 1, the denominator = 1×1 = 1, so **cosine collapses to the dot product** — identical ranking. Hence "cosine vs dot product doesn't matter here" _for normalized vectors_.

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
- Payload `source`/`position` are stored _because citations (Phase 2/3) will need them._ The vector locates; the payload is what becomes a citation.

---

## 7. RAG vs. alternatives (THE architectural question)

### RAG's real purpose

Inject relevant, current, private, or authoritative info into the model's context **at query time**, so answers are grounded in _your_ source of truth and can be **cited** back to it. Value = grounding + attribution + controllability.

### RAG vs. training/fine-tuning

> **Training changes what the model _is_; RAG changes what the model _sees_.**
> Training = memorization in the weights; RAG = open-book retrieval at query time.

| Dimension               | RAG                                     | Training / fine-tuning                                  |
| ----------------------- | --------------------------------------- | ------------------------------------------------------- |
| Update knowledge        | Re-ingest (minutes, no model change)    | Retrain/fine-tune (slow, expensive)                     |
| Attribution / citations | Knows which chunk → can cite            | Knowledge dissolved into weights → **cannot cite**      |
| Hallucination control   | "Answer only from context, else say so" | Blends your data with everything; confidently invents   |
| Cost / access           | Laptop + API key                        | Training a 70B model is out of reach for most           |
| Remove / forget data    | Delete the points, done                 | Knowledge smeared across weights — can't cleanly excise |

Citations are **literally impossible** with pure training — and they're DocsRAG's headline differentiator, falling out of the architecture for free.

### Why use an LLM at all (vs. just retrieval)

Retrieval returns _relevant raw passages_, not an _answer_. The LLM does **synthesis**: read the chunks, understand the question, compose a direct fluent answer pulling the relevant thread out of documentation prose. **Retrieval finds; the LLM phrases.** Without the LLM you've built a search engine; with it, something that answers.

### Why not just paste the 15 docs into a chat?

Honest senior framing: **for 15 docs, pasting works — and I'd say so.** RAG is justified by what 15 _becomes_:

- **Context window limits** — 15 docs fit; 15,000 don't, in any model. RAG feeds only the handful of relevant chunks per query → scales to millions.
- **Cost & latency** — pasting processes the whole corpus on _every_ question; RAG sends ~5 small chunks regardless of corpus size. Pasting cost scales with corpus; RAG stays flat.
- **Signal-to-noise** — stuffing mostly-irrelevant text _degrades_ answer quality (needle lost in haystack). Feeding only relevant chunks often gives _better_ answers than dumping everything, even when everything fits.
- **It's a system, not a task** — RAG is an automated, queryable API other software can call; pasting is a one-off human act.
- **Persistence/reuse** — ingest once into a persistent index, reuse across unlimited queries/users; pasting re-sends every conversation.
- **Citations** — retrieval hands you each chunk's source as a structured fact; built-in, not coaxed.

> The senior move is knowing **when _not_ to use RAG.** DocsRAG uses 15 docs as a tractable stand-in to build and prove the architecture end-to-end.

---

## 8. Retrieval — the online query path (Phase 2)

`retrieve(query, k)` is three conceptual moves:

1. **Embed the query** — via `embed_query()`, the _same model_ as ingestion (non-negotiable rule). One vector out.
2. **Vector search** — hand that vector to Qdrant, ask for top-k by cosine similarity.
3. **Reconstruct chunks** — turn Qdrant's hits back into objects carrying **text** + **source metadata** (filename, position) from the payload. The vector found the match; the payload is what you'll cite.

**Deferred capability:** we discard the retrieval **score** (`for chunk, _ in results`). Fine for now, but it means we can't threshold ("drop hits below 0.5"), can't tell the user how confident retrieval was, and generation has no signal about match quality. The score is the one _mechanical_ backstop for "docs don't cover this" — a low top score = probably not covered → could refuse _before_ the LLM call. Deferred, not free.

**`k` choice:** default `k=5`. Small enough to keep the prompt focused and cheap, large enough to likely contain the answer. Tunable via eval.

---

## 9. Generation — grounding + citation stitching (Phase 2)

Two distinct sub-problems inside `generate.py`:

### Grounding (prompt construction)

Assemble: retrieved chunks (context) + question + an instruction constraining the model to answer _only_ from the provided context and to say "I don't know" when the answer isn't there. **This instruction is what makes RAG grounded** rather than free-associating from training. The line "answer only from the context below; if it's not present, say you don't know" is the primary hallucination lever.

### Citation stitching (attribution — the differentiator made concrete)

- Label each chunk in the prompt with an identifier (`[1]`, `[2]`, …) tied to its source.
- Instruct the model to cite those identifiers inline when it uses a chunk.
- Map identifiers back to real source filenames when displaying.
- **Subtlety:** the model only knows the sources you _show it_ in the prompt. The labels you inject + the mapping you keep are what make citations trustworthy. Sloppy stitching = citations pointing at the wrong source = worse than none.

### The citation-alignment guarantee (structural, not the model's cooperation)

The `[2]` the model writes inline maps to the right file because **the same list, in the same order, is used in both the prompt and the sources display**. `format_context` numbers `chunks[i]` as `[i+1]`; the sources footer numbers the _same list_ the same way. The prompt _instructs_ the model to cite by number (model's job); the numbers _map to real files_ because both sides walk one ordered list (your code's guarantee). The second is the load-bearing part.

---

## 10. Grounded refusal — the "I don't know" property

Two failure modes, kept strictly separate:

- **Semantic case ("chunks don't contain the answer"):** retrieval succeeds, but no chunk actually answers the question. The system prompt makes the model respond "I don't know" — **by design, not a bug.** This is the single most important property of a grounded RAG system: **it refuses rather than hallucinates.** Graceful degradation. Frame "I don't know" as an _engineered feature_.
- **Mechanical case (API returns `None` content):** the response object's `content` can be `None` as a response-shape edge case (empty completion, certain finish reasons) — _regardless of answer presence_. Fixed with `content or ""`. In the semantic case above, content is a normal string that happens to say "I don't know"; it is NOT `None`. Don't conflate the two.

### Prompt instructs → eval verifies → score could enforce (three layers)

The prompt _instructs_ refusal but does **not enforce** it — a weaker model or cleverly-worded question can still make it lean on training knowledge. So "did it correctly refuse?" is something we **trust the model to self-assess**, which is exactly why the **Phase 4 eval harness exists** — to measure whether refusal actually holds, not just whether we asked for it. The discarded retrieval **score** is the mechanical lever that could _enforce_ a refusal before the LLM is even called.

---

## 11. `temperature=0.0` — an engineering choice, not a default

Two reasons, both worth stating:

1. **Grounding, not creativity, is the job.** There's a correct answer in the context; we want it reported, not embellished. Temperature is a creativity dial turned to zero because this task has no use for creativity.
2. **Reproducibility for evals.** The Phase 4 harness judges correctness. If the same question yields different answers per run, eval scores become noisy and you can't tell whether a score moved because retrieval improved or because the model rolled differently. Temperature 0 makes the pipeline's output a **stable function of its input** — which is what makes evaluation meaningful.

---

## 12. Streaming & citation timing (Phase 3 — conceptual)

In Phase 2, sources came as a footer _after_ the full answer. Streaming breaks that — the answer arrives over time. Solution: a **stream of typed events**, `sources` first, then many `token`, then `done`.

**Why sources up front (not in the `done` event):** the inline `[n]` markers appear _in the token stream_ as the model emits them. If the client already has the `sources` event, every `[n]` is resolvable the instant it appears. Sources at the _end_ would mean streaming an answer full of `[2]` markers pointing to nothing until completion. Up-front sources = citations resolvable immediately.

**Retrieved vs. used (honest limitation):** the sources event currently lists _all `k` retrieved_ passages, not only the ones the answer actually _cited_. For a citation system the ideal is "show what was used." Interim fix: name it "retrieved passages," or later parse which `[n]` markers actually appear in the answer and filter to those. Owning this gap (and naming the mechanism to fix it) is the senior move.

(The transport-level details — SSE vs WebSocket, POST, sync-vs-async streaming — live in the architecture doc.)

---

## 13. Evaluation — the eval harness (Phase 4)

The second headline differentiator (alongside citations). Turns "I think it works" into "here's a repeatable measurement."

### What "LLM-as-judge" is

For each golden Q&A pair: run the question through the real pipeline → get an answer → ask an LLM to grade that answer against a **human-written reference** ("PASS if factually consistent, FAIL if it contradicts / misses the key point / is wrong"). The judge is a _fuzzy-matching mechanism_ against curated truth.

### Why an LLM judge, not keyword/substring matching

You're grading **semantic correctness, not string similarity.** Keyword matching fails in _both directions_:

- **False FAIL** — a correct answer using different words ("wrap the name in braces") contains none of the expected literal tokens → a right answer fails.
- **False PASS** — a wrong answer that happens to contain the right tokens ("you do NOT use curly braces") passes a substring check. **Keyword matching can't detect negation/contradiction** because it reads presence, not meaning.
  The LLM judge grades _meaning_, which is the entire point. Deliberately calibrated to PASS on different wording / extra detail / omitted code, FAIL only on contradiction / missing key point / wrong.

### What a passing eval PROVES — and its two limits

- **Proves:** end-to-end answer correctness — retrieval found relevant chunks AND generation produced a correct grounded answer — against a human-curated set.
- **Limit 1 — system-level, not component-level.** A failure doesn't tell you _whether_ it was a retrieval miss (wrong chunks) or a generation miss (right chunks, bad answer). No per-stage diagnostic.
- **Limit 2 — small sample.** 12 questions = smoke-test size. Catches regressions and proves the concept; **not** enough for statistical confidence. "11/12 = 92%" is a directional signal, NOT a quotable accuracy number.
- **Senior instinct:** an eval that honestly states its scope beats one quoting a confident number it can't support.

### The self-grading circularity critique (THE question)

Same model generates _and_ judges → risk of self-bias + shared blind spots. **Concede it openly.** Why it still works, and the fix:

1. **Verification is narrower than generation** — the judge has the reference in hand, doing comparison not open-ended recall. (Same reason reviewing a PR is easier than writing it.)
2. **The golden references are the anchor** — the judge grades against _human-written truth_, not in a vacuum; that constrains what "correct" means even given model blind spots.
3. **Fix:** use a _different, ideally stronger_ judge model than the generator — breaks the loop. The provider-agnostic layer makes this a config change.
   > Posture: concede → explain → name the fix. That's what separates "I understand LLM-as-judge" from "I copied a tutorial."

### The untested safety property (the highest-value gap)

The golden set is 12 _answerable_ questions. The property we're proudest of — **"it refuses rather than hallucinates"** — is **untested**. No case where the answer isn't in the docs and expected behavior is "I don't know." This closes the Phase 2 loop: _prompt instructs refusal → eval must verify it._

- **Why highest-value:** refusal is the _safety property_; its failure mode (confident hallucination) is exactly what erodes trust. An untested safety property is worse than an untested feature.
- **Subtlety:** refusal cases need their own judge rubric — "correct refusal = PASS, confident fabrication = FAIL" — which is a _different_ rubric than "matches the reference technique." A judge told to check "same core technique" may get confused when the correct behavior is _declining to state a technique_.

### How you'd make it diagnose the failing stage (follow-up)

Add a **retrieval-only eval** keyed on expected source file: "did the right source doc appear in top-k?" — checkable _mechanically_, no LLM judge needed, because you know each golden answer's source. That isolates retrieval quality from generation quality (and is where the discarded retrieval **score** + stored **source metadata** would earn their keep).

---

## 14. Ingestion quality & index freshness (Phase 5)

### Cleaning the corpus (data quality > model tolerance)

The FastAPI docs embed build-time artifacts that aren't real content:

- `{* ../../docs_src/... *}` — MkDocs code-include macros.
- `{ #some-anchor }` — heading anchor tags.

Phase 1 judged these "harmless"; Phase 5 **stripped them at ingest** (`clean_markdown()`, regex, before chunking). Why it's the right call: **cleaning the data once is more robust than hoping the model ignores noise on every query.** Noise in a chunk dilutes its embedding (the vector partly encodes junk) and wastes prompt space at generation. Fix the data, not the symptom.

Effect: corpus shrank **138 → 124 chunks** (less junk text → fewer chunks).

### The orphan problem — why upsert wasn't enough (KEY INSIGHT)

The chunk ID is `uuid5(NAMESPACE_URL, f"{filename}:{position}")` — keyed on **filename + position**, _not_ content.

- **Upsert overwrites points with matching IDs.** It does **not** delete points whose IDs stop being produced.
- When cleaning shrank the corpus, some files now yield **fewer** chunks. Old high-position IDs (e.g. `body.md:9` when `body.md` now only reaches position 7) become **orphans** — stale points upsert never revisits and never removes.
- Result: the index silently contains chunks that no longer reflect the source. **Silent staleness**, the worst kind of bug.

> **Corrected Phase 1 story:** deterministic IDs + upsert prevents **duplicates**, but doesn't **garbage-collect orphans** when the chunk set changes. A **full reset** (drop + recreate, `reset_collection()`) guarantees the index exactly matches the current corpus.

### The cost of reset — and the production answer

- **Downside: a downtime window.** The collection is briefly gone during rebuild → a live system serving traffic would fail queries mid-reingest.
- **Production-grade alternative: blue-green.** Build a _new_ collection alongside the old, then atomically **swap the alias**. Zero downtime.
- **Trade made here:** reset is the right simplicity/robustness choice for a portfolio project. Knowing _why it wouldn't fly under live traffic_ is the depth signal.

### The eval regression story (LEAD WITH THIS)

Eval went **12/12 (P4) → 11/12 (P5)** after the pipeline changed; the miss traces to a **recall gap on rephrased queries**.

> **The eval caught a regression I'd otherwise have shipped blind.** An eval that _catches_ something is far stronger evidence you built a real eval than one that only ever reports green. This is one of the best talking points in the whole project — don't hide it, lead with it.

Fix direction (roadmap): structure-aware chunking, reranking / hybrid search — i.e. **retrieval-quality** upgrades, which is exactly where the RAG doc §1 claim ("most RAG failures live in retrieval") predicts the problem would be.
