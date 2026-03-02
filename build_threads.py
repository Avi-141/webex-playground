#!/usr/bin/env python3
"""
Reconstruct message threads from SQLite and produce RAG-ready documents.

Chunking strategy (v2 -- with contextual preamble):
  1. THREADS (root + replies) -> single document, always intact.
  2. STANDALONE MESSAGES (no thread) -> one document each.
  3. Every document gets a contextual preamble prepended to the
     embedding content: space name, date, type, participants.
     This ensures embeddings capture WHERE and WHEN, not just WHAT.
"""

import json
import os
import sqlite3
from collections import defaultdict

DB_PATH = os.environ.get("DB_PATH", "./webex.db")
OUT_PATH = os.environ.get("THREADS_PATH", "./threads.json")


def dict_factory(cursor, row):
    return dict(zip((col[0] for col in cursor.description), row))


def sender_label(msg):
    email = msg.get("person_email") or ""
    if email:
        return email.split("@")[0]
    return (msg.get("person_id") or "unknown")[:12]


def format_message(msg, indent=""):
    return f"{indent}[{sender_label(msg)} | {msg['created_at']}]\n{indent}{msg['text'] or ''}"


def build_preamble(space_title, doc_type, day, participants, message_count):
    parts = [f"Space: {space_title}"]
    parts.append(f"Date: {day}")
    if doc_type == "thread":
        parts.append(f"Type: threaded conversation ({message_count} messages)")
    else:
        parts.append("Type: standalone message")
    if participants:
        parts.append(f"Participants: {', '.join(participants)}")
    return " | ".join(parts)


def get_documents_for_space(conn, space_id, space_title):
    messages = conn.execute(
        "SELECT * FROM messages WHERE space_id = ? ORDER BY created_at", (space_id,)
    ).fetchall()

    children_of = defaultdict(list)
    for m in messages:
        if m["parent_id"]:
            children_of[m["parent_id"]].append(m)

    docs = []
    used_ids = set()

    for m in messages:
        if m["parent_id"] is not None:
            continue
        replies = sorted(children_of.get(m["id"], []), key=lambda r: r["created_at"])
        if not replies:
            continue

        lines = [format_message(m)]
        for r in replies:
            lines.append(format_message(r, indent="  \u21b3 "))

        all_senders = {sender_label(m)} | {sender_label(r) for r in replies}
        participants = list(all_senders)
        content = "\n\n".join(lines)
        preamble = build_preamble(space_title, "thread", m["day"], participants, 1 + len(replies))

        docs.append({
            "space_id": space_id,
            "space_title": space_title,
            "type": "thread",
            "thread_root_id": m["id"],
            "day": m["day"],
            "participants": participants,
            "message_count": 1 + len(replies),
            "content": content,
            "content_for_embedding": f"{preamble}\n\n{content}",
        })
        used_ids.add(m["id"])
        used_ids.update(r["id"] for r in replies)

    for m in messages:
        if m["id"] in used_ids:
            continue
        participant = [sender_label(m)]
        content = format_message(m)
        preamble = build_preamble(space_title, "message", m["day"], participant, 1)

        docs.append({
            "space_id": space_id,
            "space_title": space_title,
            "type": "message",
            "thread_root_id": m["id"],
            "day": m["day"],
            "participants": participant,
            "message_count": 1,
            "content": content,
            "content_for_embedding": f"{preamble}\n\n{content}",
        })

    return docs


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory

    spaces = conn.execute("SELECT id, title FROM spaces").fetchall()

    all_docs = []
    for space in spaces:
        title = space["title"] or space["id"]
        docs = get_documents_for_space(conn, space["id"], title)
        threads = [d for d in docs if d["type"] == "thread"]
        standalone = [d for d in docs if d["type"] == "message"]
        print(f"  {title}: {len(threads)} threads, {len(standalone)} standalone")
        all_docs.extend(docs)

    with open(OUT_PATH, "w") as f:
        json.dump(all_docs, f, indent=2, ensure_ascii=False)

    total_threads = sum(1 for d in all_docs if d["type"] == "thread")
    total_standalone = sum(1 for d in all_docs if d["type"] == "message")
    print(f"\nTotal: {len(all_docs)} documents ({total_threads} threads, {total_standalone} standalone) -> {OUT_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
