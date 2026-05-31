from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.database import connect, init_schema
from app.rag.semantic_text import TextEmbeddingStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Precompute real text embeddings for ShopGuide product retrieval.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of missing product vectors to write.")
    args = parser.parse_args()

    conn = connect()
    init_schema(conn)
    store = TextEmbeddingStore(conn)
    if not store.is_configured:
        raise SystemExit(
            "Text embedding is not configured. Set TEXT_EMBEDDING_MODEL and TEXT_EMBEDDING_API_KEY "
            "(TEXT_EMBEDDING_BASE_URL defaults to ARK_BASE_URL)."
        )
    written = store.precompute_missing(limit=args.limit)
    provider, model = store.identity
    print(f"wrote {written} text embedding vectors using {provider}/{model}")


if __name__ == "__main__":
    main()
