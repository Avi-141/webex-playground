#!/usr/bin/env python3
"""Index thread documents into Weaviate with Ollama embeddings and BM25."""

import json
import os

import weaviate
from weaviate.classes.config import Configure, DataType, Property, Tokenization

THREADS_PATH = os.environ.get("THREADS_PATH", "./threads.json")
OLLAMA_URL_FOR_WEAVIATE = os.environ.get(
    "OLLAMA_URL_WEAVIATE", "http://host.docker.internal:11434"
)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
COLLECTION = "SpaceThread"

MAX_EMBED_CHARS = 12000


def ensure_collection(client, fresh=False):
    if client.collections.exists(COLLECTION):
        if fresh:
            print(f"Deleting existing collection '{COLLECTION}' for fresh index...")
            client.collections.delete(COLLECTION)
        else:
            print(f"Collection '{COLLECTION}' already exists. Adding to it.")
            return client.collections.get(COLLECTION)

    print(f"Creating collection '{COLLECTION}' with Ollama vectorizer ({EMBED_MODEL})...")
    return client.collections.create(
        name=COLLECTION,
        vectorizer_config=Configure.Vectorizer.text2vec_ollama(
            model=EMBED_MODEL,
            api_endpoint=OLLAMA_URL_FOR_WEAVIATE,
        ),
        properties=[
            Property(
                name="space_id",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_filterable=True,
                index_searchable=False,
            ),
            Property(
                name="space_title",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_filterable=True,
                index_searchable=True,
                tokenization=Tokenization.WORD,
            ),
            Property(
                name="doc_type",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_filterable=True,
                index_searchable=False,
            ),
            Property(
                name="thread_root_id",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_filterable=False,
                index_searchable=False,
            ),
            Property(
                name="day",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_filterable=True,
                index_searchable=False,
            ),
            Property(
                name="participants",
                data_type=DataType.TEXT_ARRAY,
                skip_vectorization=True,
                index_filterable=True,
                index_searchable=True,
                tokenization=Tokenization.WORD,
            ),
            Property(
                name="message_count",
                data_type=DataType.INT,
                skip_vectorization=True,
            ),
            Property(
                name="content",
                data_type=DataType.TEXT,
                skip_vectorization=True,
                index_searchable=True,
                tokenization=Tokenization.WORD,
            ),
            Property(
                name="content_for_embedding",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        ],
    )


def main():
    with open(THREADS_PATH) as f:
        docs = json.load(f)

    print(f"Loaded {len(docs)} documents from {THREADS_PATH}")

    weaviate_host = os.environ.get("WEAVIATE_HOST", "localhost")
    client = weaviate.connect_to_local(host=weaviate_host)

    try:
        collection = ensure_collection(client, fresh=True)

        with collection.batch.dynamic() as batch:
            for i, doc in enumerate(docs):
                embed = doc.get("content_for_embedding", doc["content"])
                if len(embed) > MAX_EMBED_CHARS:
                    embed = embed[:MAX_EMBED_CHARS]

                batch.add_object(
                    properties={
                        "space_id": doc["space_id"],
                        "space_title": doc.get("space_title", ""),
                        "doc_type": doc.get("type", "message"),
                        "thread_root_id": doc["thread_root_id"],
                        "day": doc["day"],
                        "participants": doc["participants"],
                        "content": doc["content"],
                        "content_for_embedding": embed,
                        "message_count": doc["message_count"],
                    },
                )
                if (i + 1) % 500 == 0:
                    print(f"  Queued {i + 1}/{len(docs)}...")

        failed = collection.batch.failed_objects
        if failed:
            print(f"\n  {len(failed)} objects failed.")

        total = collection.aggregate.over_all(total_count=True).total_count
        print(f"\nDone. '{COLLECTION}' has {total} objects.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
