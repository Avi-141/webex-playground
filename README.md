# webex-playground

**Open-source RAG pipeline for Cisco Webex spaces** — fetch all messages from your Webex spaces, reconstruct conversation threads, and search them with hybrid retrieval (BM25 keyword + vector semantic search).

> Turn thousands of Webex messages into a searchable knowledge base in minutes. No cloud services required — runs entirely on your machine with local embeddings.

## Why

Webex spaces accumulate valuable knowledge — decisions, links, discussions, solutions — but it's impossible to search effectively. Webex's built-in search is keyword-only and can't understand context. This project fixes that:

- **Full message history** — fetch every message from any space you belong to
- **Thread-aware** — conversations (root + replies) stay together as atomic documents
- **Hybrid search** — BM25 keyword matching + vector semantic similarity, fused with configurable weights
- **Space-aware** — queries automatically resolve space names ("AI Defense" → Ask-AI Defense)
- **Date-aware** — natural language date parsing ("last month", "January 2025")
- **Contextual embeddings** — each document's vector includes space name, date, participants (Anthropic-style contextual retrieval)
- **100% local** — Ollama for embeddings, Weaviate in a container, SQLite for storage

## Pipeline

```
Webex API ──► SQLite ──► Thread Documents ──► Weaviate (hybrid search)
  fetch.mjs    webex.db   build_threads.py    index_rag.py / query.py
```

## Quick Start

### Prerequisites

- Node.js 18+
- [Podman](https://podman.io/) or Docker
- [Ollama](https://ollama.com/) (for local embeddings)

### Setup

```bash
git clone https://github.com/Avi-141/webex-playground.git
cd webex-playground
npm install

# Pull the embedding model
ollama pull nomic-embed-text

# Configure
cp .env.example .env
# Edit .env: add your WEBEX_TOKEN
```

### Get your Webex token

- **Testing**: grab a [Personal Access Token](https://developer.webex.com/docs/getting-your-personal-access-token) (valid ~12 hours)
- **Production**: use an OAuth Integration or Bot token

### Find your spaces

```bash
npm run list-spaces
```

Copy the space IDs you want into `.env` as `WEBEX_ROOM_IDS=id1,id2,id3`.

### Fetch, index, search

```bash
# 1. Fetch all messages into SQLite
npm run fetch

# 2. Reconstruct threads and build documents
npm run build-threads

# 3. Start Weaviate
npm run up

# 4. Index into Weaviate (wait ~10s after step 3)
npm run index

# 5. Search
npm run query -- "what was discussed about evaluation frameworks?"
npm run query -- "MCP servers" --space "GenAI"
npm run query -- "deployment issues" --type thread --alpha 0.3
```

## Query Options

```
query.py "your question" [options]

Options:
  --space NAME    Filter by space (fuzzy matched, e.g. "Defense" → Ask-AI Defense)
  --type TYPE     Filter by document type: "thread" or "message"
  --alpha FLOAT   Hybrid search balance: 0=pure BM25, 1=pure vector (default: 0.5)
  --limit N       Number of results (default: 5)
```

## How It Works

### Message Ingestion
`fetch.mjs` calls the [Webex Messages API](https://developer.webex.com/docs/api/v1/messages) with pagination via `Link` headers and `Retry-After` backoff on 429s. Messages are stored in SQLite with full text, HTML, links, @mentions, and `parentId` for thread reconstruction.

### Thread Reconstruction
`build_threads.py` groups messages by `parentId`:
- **Threads** (root message + all replies) → one document, always kept intact
- **Standalone messages** (no thread) → one document each

Each document gets a contextual preamble prepended to its embedding:
```
Space: Ask-AI Defense | Date: 2025-07-04 | Type: threaded conversation (5 messages) | Participants: user1, user2
```
This follows [Anthropic's Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) pattern — embeddings capture WHERE and WHEN, not just WHAT.

### Hybrid Search
Weaviate indexes each document with:
- **BM25 inverted index** on `content` (2x weight), `space_title`, and `participants` — catches exact terms, proper nouns, tool names
- **Vector embeddings** via `nomic-embed-text` (Ollama) — catches semantic meaning, paraphrases

At query time, both results are fused using Relative Score Fusion with a configurable `alpha` parameter.

### Multi-Phase Retrieval
1. **Space resolution** — fuzzy-match query terms against known space titles
2. **Date parsing** — extract date constraints from natural language
3. **Hybrid search** — BM25 + vector, filtered by resolved space/date/type

## SQLite Schema

```sql
-- All messages with thread structure
SELECT m.text, m.day, COUNT(r.id) AS replies
FROM messages m
LEFT JOIN messages r ON r.parent_id = m.id
WHERE m.space_id = '<ROOM_ID>' AND m.parent_id IS NULL
GROUP BY m.id ORDER BY m.created_at DESC;
```

## Weaviate Collection Schema

| Property | Vectorized | BM25 Searchable | Filterable |
|---|---|---|---|
| space_id | No | No | Yes |
| space_title | No | Yes | Yes |
| doc_type | No | No | Yes |
| day | No | No | Yes |
| participants | No | Yes | Yes |
| content | No | Yes (2x weight) | No |
| content_for_embedding | Yes | No | No |
| message_count | No | — | No |

## Roadmap

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full roadmap, including:

- **Metadata enrichment** — bot filtering, question tagging, link domain extraction
- **GraphRAG + Leiden communities** — entity extraction → Neo4j knowledge graph → community detection → dual local/global retrieval
- **RAPTOR hierarchical summaries** — thread → topic → space summary tree
- **Cross-encoder re-ranking**

## Tech Stack

| Component | Technology |
|---|---|
| Message ingestion | Node.js, Webex REST API |
| Storage | SQLite (WAL mode) |
| Embeddings | nomic-embed-text via Ollama |
| Vector + keyword search | Weaviate (text2vec-ollama + BM25) |
| Thread processing | Python |
| Containers | Podman / Docker Compose |

## License

[GPL-3.0](LICENSE)
