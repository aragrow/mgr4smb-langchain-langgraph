"""Ingest knowledge_base.json into the configured MongoDB collection.

Reads every entry from `knowledge_base.json`, embeds `topic + content`
with the same Gemini embedder the production tool uses, and upserts
documents shaped for MongoDBAtlasVectorSearch into:

    db:         settings.mongodb_db_name
    collection: settings.mongodb_kb_collection

Document shape (matches MongoDBAtlasVectorSearch expectations):
    {
        "_id":      <slugified topic>,      # idempotent upsert key
        "text":     "<content>",            # page_content
        "embedding": [float, ...],          # 768-dim vector
        "topic":    "<topic>",
        "source":   "sandbox-kb-json",
    }

After running, create an Atlas Vector Search index with name
settings.mongodb_kb_index_name (default: `kb_vector_index`) on the
`embedding` field, dimensions = settings.embedding_dimensions (768),
similarity = cosine.

Usage:
    source .venv/bin/activate
    python scripts/ingest_kb_to_mongo.py          # full reingest
    python scripts/ingest_kb_to_mongo.py --dry    # no writes, just log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# Import after path setup
from sandbox.config import PROJECT_ROOT, settings  # noqa: E402
from sandbox.llm import get_embeddings  # noqa: E402
from sandbox.logging_config import setup_logging  # noqa: E402


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "entry"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="Parse + embed but don't write.")
    args = parser.parse_args()

    setup_logging(level="INFO")

    if not settings.use_mongodb:
        print(
            "error: MONGODB_ATLAS_URI is not set in .env — cannot ingest.",
            file=sys.stderr,
        )
        return 2

    kb_file = PROJECT_ROOT / "knowledge_base.json"
    if not kb_file.is_file():
        print(f"error: {kb_file} not found", file=sys.stderr)
        return 2

    corpus = json.loads(kb_file.read_text()).get("entries", [])
    corpus = [e for e in corpus if e.get("content")]
    if not corpus:
        print("error: knowledge_base.json has no entries with content", file=sys.stderr)
        return 2

    print(f"Embedding {len(corpus)} entries with {settings.embedding_model} …")
    embeddings = get_embeddings()
    texts = [
        f"{e.get('topic', '').strip()}\n\n{e['content']}"
        if e.get("topic")
        else e["content"]
        for e in corpus
    ]
    vectors = embeddings.embed_documents(texts)

    docs = [
        {
            "_id": _slug(e.get("topic") or e["content"][:40]),
            "text": e["content"],
            "embedding": v,
            "topic": e.get("topic", ""),
            "source": "sandbox-kb-json",
        }
        for e, v in zip(corpus, vectors)
    ]

    if args.dry:
        print(f"[dry] would upsert {len(docs)} documents to "
              f"{settings.mongodb_db_name}.{settings.mongodb_kb_collection}")
        for d in docs:
            print(f"  _id={d['_id']}  dims={len(d['embedding'])}  "
                  f"chars={len(d['text'])}  topic={d['topic']!r}")
        return 0

    from pymongo import MongoClient
    from pymongo.operations import ReplaceOne

    print(f"Connecting to MongoDB at "
          f"{settings.mongodb_atlas_uri.split('@')[-1].split('/')[0]} …")
    client = MongoClient(settings.mongodb_atlas_uri)
    client.admin.command("ping")
    coll = client[settings.mongodb_db_name][settings.mongodb_kb_collection]

    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
    result = coll.bulk_write(ops, ordered=False)
    print(
        f"Upserted: matched={result.matched_count} "
        f"modified={result.modified_count} "
        f"upserted={len(result.upserted_ids)}"
    )
    print()
    print(
        f"Next step: ensure an Atlas Vector Search index named "
        f"{settings.mongodb_kb_index_name!r} exists on field 'embedding' "
        f"(dims={settings.embedding_dimensions}, similarity=cosine) in "
        f"{settings.mongodb_db_name}.{settings.mongodb_kb_collection}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
