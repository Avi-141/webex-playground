# Webex Playground — Architecture & Roadmap

## Current Pipeline (v1)

```
Webex API ──► SQLite (28,741 messages) ──► Thread Documents ──► Weaviate (vector search)
  fetch.mjs    webex.db                    build_threads.py      index_rag.py / query.py
```

### Data Model (SQLite)

- **spaces**: room ID, title, fetched_at
- **messages**: full message content with `parent_id` for threading, `day` in Asia/Kolkata

### Chunking Strategy (v2)

1. **Threads** (root + all replies): always kept as a single document. Threads are the natural unit of conversation and always stay intact.
2. **Standalone messages** (no thread): one document per message.
3. **Contextual preamble**: every document's embedding content is prepended with metadata — space name, date, type (thread vs standalone), participants. This follows Anthropic's Contextual Retrieval pattern so embeddings capture WHERE and WHEN, not just WHAT.

### Embedding

- Model: `nomic-embed-text` (8192 token context, running locally via Ollama)
- Vectorizer: `text2vec-ollama` module in Weaviate
- Content over 12k chars is truncated for embedding only; full content is stored separately and returned in query results.
- Schema splits `content` (full, stored, not vectorized) from `content_for_embedding` (with preamble, vectorized).

### Spaces Indexed

| Space | Messages |
|---|---|
| New AI/ML Research and News | 1,266 |
| Ask-AI Canvas | 1,713 |
| Ask-AI Defense | 4,992 |
| GenAI + Agentic AI | 1,101 |
| Cisco Investments Startup Showcase | 351 |
| Generative AI Explorers | 17,070 |
| Artificial Intelligence and Machine Learning | 2,248 |
| **Total** | **28,741** |

---

## Known Limitations

### Short/noisy standalone messages
Most standalone messages are short ("thanks!", a shared link, a quick question). They embed poorly — not enough semantic signal for meaningful vector similarity. They create noise in retrieval.

### Unthreaded conversations
People in Webex often don't use threading. Someone posts a question, 3 people respond as standalone messages within 5 minutes. To a human, that's a conversation. To our pipeline, those are 4 unrelated documents.

### Flat retrieval can't answer global questions
"What has the team been working on this quarter?" requires synthesizing across hundreds of messages. Pure vector similarity retrieval can't do this — it only finds individual chunks that are similar to the query.

### 80 documents failed indexing
Some individual messages contain very dense content (code, URLs, non-English text) that tokenizes to more than 8192 tokens even under 12k chars. These are skipped during indexing.

---

## Roadmap

### Phase 1: Intelligent Standalone Message Grouping

**Problem**: Standalone messages posted minutes apart about the same topic are disconnected.

**Approaches considered**:

| Approach | Pros | Cons |
|---|---|---|
| **Temporal windowing** — group messages within N minutes | Simple, no LLM | Lumps unrelated messages that happen to be posted at the same time |
| **Temporal + heuristic signals** — window + shared URLs, @mentions, keyword overlap | Better precision, no LLM | Still misses semantic connections |
| **LLM-based conversation segmentation** — feed sequence of messages, ask LLM to draw boundaries | Most accurate | Expensive (LLM calls on 28k messages) |
| **Skip and go straight to GraphRAG** | Solves the deeper problem | More complex to build |

**Current thinking**: Skip this phase and go directly to GraphRAG. Grouping standalone messages is putting a bandaid on flat retrieval. GraphRAG solves the underlying problem — it connects messages through shared entities, topics, and people regardless of whether they were threaded.

### Phase 2: GraphRAG + Leiden Community Detection

**Approach**: Microsoft's GraphRAG pattern adapted for conversational data.

**Pipeline**:
```
Messages (SQLite)
  → Entity/Relationship extraction (LLM)
  → Knowledge Graph (Neo4j)
  → Leiden community detection (hierarchical clustering)
  → Community summaries (LLM)
  → Dual retrieval: local (entity-level) + global (community-level)
```

**Graph Model**:
- **Nodes**: Person, Space, Message, Topic (LLM-extracted), Entity (tools, models, repos, tickets)
- **Edges**: SENT, IN_SPACE, REPLIES_TO, MENTIONS, RELATED_TO (co-occurrence/semantic similarity)

**Why it fits this data**:
- Chat messages naturally form communities — "evaluation framework" discussions, "deployment incident" clusters, etc.
- Leiden/Louvain discovers these organically from entity co-occurrence across messages.
- Community summaries provide the "global view" that flat RAG completely misses.
- Doesn't care whether messages were threaded or not — connects them through shared entities.

**Cost**: Heavy on LLM calls during indexing (entity extraction + community summarization for 28k messages). But indexed once, queried many times.

**Stack**: Neo4j for the graph, existing Weaviate for vector retrieval, Ollama for LLM extraction.

### Phase 3: RAPTOR-style Hierarchical Summaries

**Approach**: Recursive Abstractive Processing for Tree-Organized Retrieval (Stanford, ICLR 2024).

Build a summary tree bottom-up:
```
Individual messages / threads
  → Thread summaries
    → Topic-level summaries (cluster related threads)
      → Space-level summaries
```

**Why**: Enables retrieval at different levels of abstraction. A query like "what was decided about the API migration?" hits thread-level, while "what has the team been working on?" hits space-level summaries.

**Synergy with GraphRAG**: The Leiden communities from Phase 2 provide natural clusters for the RAPTOR tree's mid-levels. Thread summaries → community summaries → space summaries.

### Phase 4 (future): Additional Enhancements

**Late Chunking (Jina)**: Embed entire conversations with a long-context model, then chunk. Each chunk's embedding preserves awareness of surrounding context. Requires jina-embeddings-v3 (API, not local).

**PageIndex (Vectify)**: Vectorless RAG — hierarchical tree index with LLM-based agentic reasoning for navigation. 98.7% accuracy on benchmarks but slow/expensive per query. Better for structured documents than chat data.

---

## Multi-Phase Retrieval (v2 — current)

Pure vector similarity fails for queries referencing specific space names, people, or exact terms.
The retrieval pipeline now has three phases:

### Phase 1: Space Resolution
Parse the query for space name references. Fuzzy-match against known space titles from SQLite.
- "Tell me about AI Defense" → resolves to Ask-AI Defense space → applies as filter
- Uses `difflib.SequenceMatcher` + substring matching
- Also supports explicit `--space` flag with name or ID

### Phase 2: Hybrid Search (BM25 + Vector)
Weaviate `hybrid` query combining:
- **BM25 keyword search** on `content` (2x weight), `space_title`, `participants`
- **Vector similarity** on `content_for_embedding` (via Ollama nomic-embed-text)
- Fused with `Relative Score Fusion`, default `alpha=0.5` (tunable)
- `alpha=0` → pure keyword, `alpha=1` → pure vector

### Phase 3: Metadata Filtering
Hard constraints applied on top of hybrid results:
- `--space` → filter by space ID (resolved from name)
- `--type thread|message` → filter by document type
- Date parsing from natural language ("last month", "January 2025") → day range filter

### Example Query Flow
```
Input: "What was discussed about evaluation frameworks in AI Defense last month?"

Phase 1: "AI Defense" → space_id filter (Ask-AI Defense)
Phase 2: Hybrid search with query "What was discussed about evaluation frameworks"
         BM25 catches "evaluation frameworks" as exact keywords
         Vector catches semantic meaning of the question
Phase 3: day >= 2026-02-01, day < 2026-03-01
```

### Weaviate Collection Schema (v2)

| Property | Type | Vectorized | BM25 Searchable | Filterable |
|---|---|---|---|---|
| space_id | TEXT | No | No | Yes |
| space_title | TEXT | No | Yes (WORD) | Yes |
| doc_type | TEXT | No | No | Yes |
| thread_root_id | TEXT | No | No | No |
| day | TEXT | No | No | Yes |
| participants | TEXT[] | No | Yes (WORD) | Yes |
| message_count | INT | No | — | No |
| content | TEXT | No | Yes (WORD, 2x weight) | No |
| content_for_embedding | TEXT | Yes | No | No |

---

## Future Enhancements

**Late Chunking (Jina)**: Embed entire conversations with a long-context model, then chunk. Each chunk's embedding preserves awareness of surrounding context. Requires jina-embeddings-v3 (API, not local).

**PageIndex (Vectify)**: Vectorless RAG — hierarchical tree index with LLM-based agentic reasoning for navigation. 98.7% accuracy on benchmarks but slow/expensive per query. Better for structured documents than chat data.

**Re-ranking (Phase 4)**: Take top-N candidates from hybrid search and re-rank with a cross-encoder or LLM for final precision.

---

## Design Decisions Log

| Decision | Rationale |
|---|---|
| SQLite for raw storage | Portable, zero-ops, handles tree structure with `parent_id` |
| Threads as atomic chunks | Conversations are the natural unit; splitting loses context |
| Standalone = 1 doc each | Clean, no artificial grouping; easy to re-chunk later |
| Contextual preamble in embeddings | Space name + date + participants baked into vectors improves retrieval precision |
| `content` vs `content_for_embedding` split | Store full text, only vectorize a context-enriched version (with truncation safety) |
| `nomic-embed-text` via Ollama | Local, free, 8192 token context, good quality for the cost |
| Podman over Docker | User's environment; compose compatibility via `extra_hosts` |
| `request` npm library for Webex API | Node.js built-in `fetch` and `node:https` hang on this machine; `request` works reliably |
