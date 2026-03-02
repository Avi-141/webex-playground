# webex-playground
Fetch Webex space messages, reconstruct threads, and build a RAG index over them.

## Pipeline

```
Webex API ──► SQLite ──► Thread Documents (JSON) ──► Weaviate (vector search)
  fetch.mjs    build_threads.py                       index_rag.py / query.py
```

## Prerequisites

- Node.js 18+
- Python 3.10+
- Docker (for Weaviate)
- Ollama (for local embeddings)

## Setup

```bash
# 1. Install Node deps
npm ci

# 2. Install Python deps
pip install -r requirements.txt

# 3. Pull the embedding model
ollama pull nomic-embed-text

# 4. Start Weaviate
docker compose up -d

# 5. Configure environment
cp .env.example .env
# Edit .env: add your WEBEX_TOKEN and WEBEX_ROOM_IDS
```

### Getting your Webex token

- **Testing**: grab a Personal Access Token from https://developer.webex.com/docs/getting-your-personal-access-token (valid ~12 hours)
- **Production**: use an OAuth Integration or Bot token

### Finding your space (room) IDs

```bash
npm run list-spaces
```

This lists all your group spaces sorted by last activity. Copy the IDs you want into `.env`.

## Usage

### Step 1: Fetch messages

```bash
npm run fetch
```

Pulls all messages from each configured space into `webex.db` (SQLite). Handles pagination via `Link` headers and backs off on 429 rate limits. Also resolves person display names.

### Step 2: Build thread documents

```bash
python build_threads.py
```

Reconstructs message threads using `parentId` relationships:
- **Threaded roots** (messages with replies) become one document per thread
- **Standalone messages** (no thread) are grouped by day

Output: `threads.json`

### Step 3: Index into Weaviate

```bash
python index_rag.py
```

Creates a `SpaceThread` collection in Weaviate with `text2vec-ollama` vectorizer and indexes all thread documents.

### Step 4: Query

```bash
python query.py "what was decided about the API migration?"
python query.py "deployment issues" --space <ROOM_ID> --limit 3
```

### Re-indexing

To re-index from scratch, delete the Weaviate collection first:

```python
import weaviate
client = weaviate.connect_to_local()
client.collections.delete("SpaceThread")
client.close()
```

Then run steps 2-3 again.

## SQLite schema

- **spaces**: room metadata
- **people**: person ID → display name / email
- **messages**: all messages with `parent_id` for threading, `day` in Asia/Kolkata

Query threads directly:

```sql
-- Thread roots and their reply counts
SELECT m.id, m.text, m.day, COUNT(r.id) AS replies
FROM messages m
LEFT JOIN messages r ON r.parent_id = m.id
WHERE m.parent_id IS NULL AND m.space_id = '<ROOM_ID>'
GROUP BY m.id
ORDER BY m.created_at DESC;
```

## Weaviate collection schema

| Property        | Type       | Description                    |
|-----------------|------------|--------------------------------|
| space_id        | TEXT       | Webex room ID                  |
| thread_root_id  | TEXT       | Root message ID or `day-YYYY-MM-DD` |
| day             | TEXT       | Date in Asia/Kolkata           |
| participants    | TEXT[]     | Display names in the thread    |
| content         | TEXT       | Full thread text (vectorized)  |
| message_count   | INT        | Number of messages in thread   |

## Notes on Ollama + Docker

Weaviate runs in Docker and calls Ollama for embeddings. By default it connects to `http://host.docker.internal:11434` which works on macOS/Windows. On Linux, either:
- Run Ollama in Docker too (add to `docker-compose.yml`)
- Or use `--network host` on the Weaviate container
