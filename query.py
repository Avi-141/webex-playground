#!/usr/bin/env python3
"""
Multi-phase RAG query against the SpaceThread collection in Weaviate.

Phase 1: Space resolution — fuzzy match query terms against known space titles
Phase 2: Hybrid search — BM25 keyword + vector similarity, fused with alpha
Phase 3: Metadata filtering — apply resolved space IDs, date ranges, doc_type
"""

import argparse
import os
import re
import sqlite3
from difflib import SequenceMatcher

import weaviate
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery

COLLECTION = "SpaceThread"
DB_PATH = os.environ.get("DB_PATH", "./webex.db")


def load_space_titles(db_path):
    """Load space id->title mapping from SQLite."""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT id, title FROM spaces").fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows if row[1]}
    except Exception:
        return {}


def resolve_space(query_text, space_map):
    """
    Fuzzy match query text against known space titles.
    Returns (space_id, cleaned_query) if a match is found, else (None, query).
    """
    if not space_map:
        return None, query_text

    query_lower = query_text.lower()
    best_id = None
    best_score = 0.0
    best_title = ""

    for sid, title in space_map.items():
        title_lower = title.lower()
        clean_title = re.sub(r"\s*[|].*$", "", title_lower).strip()

        if clean_title in query_lower or title_lower in query_lower:
            if len(clean_title) > len(best_title):
                best_id = sid
                best_score = 1.0
                best_title = clean_title
            continue

        ratio = SequenceMatcher(None, query_lower, clean_title).ratio()
        for word in clean_title.split():
            if len(word) > 3 and word in query_lower:
                ratio = max(ratio, 0.6)

        if ratio > best_score and ratio >= 0.5:
            best_id = sid
            best_score = ratio
            best_title = clean_title

    if best_id and best_score >= 0.5:
        return best_id, query_text

    return None, query_text


def parse_date_filter(query_text):
    """Extract date hints from query text. Returns (day_gte, day_lte) or (None, None)."""
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
    }

    query_lower = query_text.lower()

    match = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})", query_lower)
    if match:
        month = month_map[match.group(1)]
        year = match.group(2)
        day_gte = f"{year}-{month}-01"
        if month == "12":
            day_lte = f"{int(year) + 1}-01-01"
        else:
            day_lte = f"{year}-{int(month) + 1:02d}-01"
        return day_gte, day_lte

    if "last month" in query_lower:
        from datetime import datetime, timedelta
        now = datetime.now()
        first_of_this = now.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.strftime("%Y-%m-%d"), first_of_this.strftime("%Y-%m-%d")

    return None, None


def build_filters(space_id=None, doc_type=None, day_gte=None, day_lte=None):
    """Build a Weaviate filter chain from resolved constraints."""
    parts = []

    if space_id:
        parts.append(Filter.by_property("space_id").equal(space_id))
    if doc_type:
        parts.append(Filter.by_property("doc_type").equal(doc_type))
    if day_gte:
        parts.append(Filter.by_property("day").greater_or_equal(day_gte))
    if day_lte:
        parts.append(Filter.by_property("day").less_than(day_lte))

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]

    combined = parts[0]
    for p in parts[1:]:
        combined = combined & p
    return combined


def main():
    parser = argparse.ArgumentParser(description="Multi-phase RAG query over Webex threads")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument("--space", help="Filter to a specific space (name or ID)")
    parser.add_argument("--type", choices=["thread", "message"], help="Filter by document type")
    parser.add_argument("--alpha", type=float, default=0.5,
                        help="Hybrid search balance: 0=pure BM25, 1=pure vector (default: 0.5)")
    parser.add_argument("--limit", type=int, default=5, help="Number of results (default: 5)")
    args = parser.parse_args()

    space_map = load_space_titles(DB_PATH)

    resolved_space_id = None
    if args.space:
        space_query = args.space.lower().strip()
        best_match = None
        best_score = 0.0
        for sid, title in space_map.items():
            if space_query == sid:
                best_match = sid
                best_score = 1.0
                break
            title_lower = title.lower()
            clean = re.sub(r"\s*[|].*$", "", title).strip().lower()
            if space_query == clean or space_query == title_lower:
                best_match = sid
                best_score = 1.0
                break
            if space_query in clean or clean in space_query:
                score = len(space_query) / max(len(clean), 1)
                if score > best_score:
                    best_match = sid
                    best_score = score
                continue
            for word in space_query.split():
                if len(word) > 3 and word in title_lower:
                    score = 0.4
                    if score > best_score:
                        best_match = sid
                        best_score = score
        if best_match:
            resolved_space_id = best_match
            print(f"[space filter: {space_map.get(resolved_space_id, resolved_space_id)}]")
        else:
            resolved_space_id = args.space

    if not resolved_space_id:
        auto_id, _ = resolve_space(args.query, space_map)
        if auto_id:
            resolved_space_id = auto_id
            print(f"[space resolved: {space_map.get(resolved_space_id, resolved_space_id)}]")

    day_gte, day_lte = parse_date_filter(args.query)
    if day_gte:
        print(f"[date filter: {day_gte} to {day_lte}]")

    filters = build_filters(
        space_id=resolved_space_id,
        doc_type=args.type,
        day_gte=day_gte,
        day_lte=day_lte,
    )

    weaviate_host = os.environ.get("WEAVIATE_HOST", "localhost")
    client = weaviate.connect_to_local(host=weaviate_host)

    try:
        collection = client.collections.get(COLLECTION)

        results = collection.query.hybrid(
            query=args.query,
            alpha=args.alpha,
            fusion_type=HybridFusion.RELATIVE_SCORE,
            query_properties=["content^2", "space_title", "participants"],
            filters=filters,
            limit=args.limit,
            return_metadata=MetadataQuery(score=True, explain_score=True),
            return_properties=["space_id", "space_title", "doc_type", "day",
                               "participants", "message_count", "content"],
        )

        if not results.objects:
            print("No results found.")
            return

        for i, obj in enumerate(results.objects):
            p = obj.properties
            score = obj.metadata.score
            print(f"\n{'=' * 72}")
            print(f"Result {i + 1}  |  score: {score:.4f}  |  {p.get('doc_type', '?')}  |  day: {p['day']}")
            print(f"space: {p.get('space_title', p['space_id'])}")
            print(f"participants: {', '.join(p.get('participants') or [])}")
            print(f"messages: {p.get('message_count', '?')}")
            print("-" * 72)

            content = p.get("content", "")
            if len(content) > 1200:
                content = content[:1200] + "\n  ... (truncated in display)"
            print(content)
    finally:
        client.close()


if __name__ == "__main__":
    main()
