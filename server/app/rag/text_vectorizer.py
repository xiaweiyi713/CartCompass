from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass


ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


class HashingVectorizer:
    """Small dependency-free vectorizer for the MVP local vector store."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        tokens = self._tokens(text)
        counts: Counter[int] = Counter(self._bucket(token) for token in tokens)
        vec = [0.0] * self.dimensions
        for idx, count in counts.items():
            vec[idx] = 1.0 + math.log(count)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm:
            vec = [x / norm for x in vec]
        return vec

    def similarity(self, left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    def _bucket(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dimensions

    def _tokens(self, text: str) -> list[str]:
        cleaned = re.sub(r"\s+", "", text.lower())
        tokens: list[str] = []
        tokens.extend(ASCII_WORD_RE.findall(text.lower()))
        tokens.extend(ch for ch in cleaned if "\u4e00" <= ch <= "\u9fff")
        tokens.extend(cleaned[i : i + 2] for i in range(max(0, len(cleaned) - 1)))
        return [token for token in tokens if token]


@dataclass(frozen=True)
class BM25Document:
    product_id: str
    tokens: list[str]
    length: int


class BM25Scorer:
    """Small in-memory BM25 scorer for hybrid retrieval reranking."""

    def __init__(self, documents: list[tuple[str, str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.documents = [
            BM25Document(product_id=product_id, tokens=self._tokens(text), length=len(self._tokens(text)))
            for product_id, text in documents
        ]
        self.avgdl = sum(document.length for document in self.documents) / max(len(self.documents), 1)
        self.document_frequencies: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequencies.update(set(document.tokens))
        self._document_map = {document.product_id: document for document in self.documents}

    def score(self, query: str, product_id: str) -> float:
        document = self._document_map.get(product_id)
        if not document:
            return 0.0
        query_tokens = self._tokens(query)
        if not query_tokens or not document.tokens:
            return 0.0
        frequencies = Counter(document.tokens)
        total = 0.0
        document_count = max(len(self.documents), 1)
        for token in query_tokens:
            freq = frequencies[token]
            if not freq:
                continue
            df = self.document_frequencies[token]
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = freq + self.k1 * (1 - self.b + self.b * document.length / max(self.avgdl, 1))
            total += idf * (freq * (self.k1 + 1)) / denominator
        return total

    def normalized_scores(self, query: str, product_ids: list[str]) -> dict[str, float]:
        raw = {product_id: self.score(query, product_id) for product_id in product_ids}
        max_score = max(raw.values(), default=0.0)
        if max_score <= 0:
            return {product_id: 0.0 for product_id in product_ids}
        return {product_id: score / max_score for product_id, score in raw.items()}

    def _tokens(self, text: str) -> list[str]:
        return HashingVectorizer()._tokens(text)
