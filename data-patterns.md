Here's the full analysis:

---

## Data Patterns & Retrieval Opportunities

### 1. Content Coverage
| Field | Count | % of N |
|---|---|---|
| Has text |
| Has HTML |
| Has markdown |
| Empty (file-only) |
| Has links |
| Has @mentions |

**Actionable**: 528 messages have no text -- they're file-only messages (images, attachments). Currently these index as empty docs. We should either skip them or tag them as `file_share`.

### 2. Link Richness
Top domains shared across spaces:
- **github.com** (454 links) — repos, tools, SDKs
- **huggingface.co** (276) — models
- **arxiv.org** (155) — papers
- **cisco.sharepoint.com** (405) — internal docs
- **youtube.com + youtu.be** (434) — talks/demos
- **openai.com** (95), **anthropic.com** (63) — vendor pages

**Actionable**: Extract link domains as metadata. A query about "papers shared" or "GitHub repos" can filter by link domain. ArXiv paper IDs could be extracted for reference linking.

### 3. Threading Patterns Vary Wildly by Space

| Space | Thread Roots | Standalone | Thread % |
|---|---|---|---|
| New AI/ML Research and News | 10 | 1,229 | **0.8%** |
| Ask-AI Canvas | 357 | 169 | **68%** |
| Ask-AI Defense | 1,018 | 434 | **70%** |
| Generative AI Explorers | 2,996 | 3,125 | **49%** |

**Key insight**: "New AI/ML Research and News" is 97% standalone messages — it's a broadcast/news-sharing space (mostly AI paper summaries). Ask-AI Canvas and Defense are conversational (heavy threading). This means different spaces need different treatment.

### 4. Bot Noise
`eurl@webex.bot` posts 228 messages across all 7 spaces — all identical "Only users in the domain(s) cisco.com can join" messages. Pure noise.

**Actionable**: Filter out bot messages from indexing entirely.

### 5. Question Detection
- 2,857 messages end with `?`
- 718 messages start with question words (how/what/why/does anyone/etc.)

**Actionable**: Tag messages as `is_question`. Questions are high-value retrieval targets — someone asking "does anyone know how to deploy X?" is exactly what RAG should surface.

### 6. Message Length Distribution
| Bucket | Count | % |
|---|---|---|
| Empty | 528 | 1.8% |
| Tiny (<50 chars) | 5,278 | 18.4% |
| Short (50-200) | 13,011 | 45.3% |
| Medium (200-500) | 6,310 | 22.0% |
| Long (500-2000) | 2,509 | 8.7% |
| Very long (2000+) | 1,105 | 3.8% |

493 standalone messages under 30 chars with no links — these are noise ("thanks!", "+1", reactions). Currently each becomes its own Weaviate doc with a meaningless vector.

**Actionable**: Skip standalone messages under 30 chars with no links from indexing.

### 7. Cross-Space Participants
15+ people post across 4+ spaces. Top: annhardy (4 spaces, 2,096 msgs), sujjosep (4 spaces, 1,399 msgs). These are key connectors for the future knowledge graph.

### 8. People Resolution
2,990 people in the DB, 2,551 have display names resolved. Good enough for participant labels.

---

## Recommended Metadata Additions to `build_threads.py`

Based on this analysis, here's what should be added to each document:

1. **`has_links`** (bool) + **`link_domains`** (string[]) — extracted from the links JSON
2. **`is_question`** (bool) — ends with `?` or starts with question words
3. **`is_bot`** (bool) — filter these out of indexing entirely
4. **`content_length`** ("tiny"/"short"/"medium"/"long") — helps filter noise
5. **`has_mentions`** (bool) + **`mention_count`** (int) — messages with @mentions tend to be more directed/actionable
6. **`space_type`** — derived: "broadcast" for New AI/ML Research, "conversational" for the rest

And two filtering rules:
- **Skip** `eurl@webex.bot` messages
- **Skip** standalone messages < 30 chars with no links
