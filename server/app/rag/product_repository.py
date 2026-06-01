from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from app.config import PRODUCT_IMAGE_DIR
from app.db.database import connect
from app.models.schemas import Product, SKU
from app.observability import observability
from app.rag.retrieval_cache import RetrievalCache
from app.rag.semantic_text import TextEmbeddingStore, cosine_similarity
from app.rag.text_vectorizer import BM25Scorer, HashingVectorizer


@dataclass
class SearchConstraints:
    category: str | None = None
    sub_category: str | None = None
    max_price: float | None = None
    min_price: float | None = None
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    exclude_brands: list[str] = field(default_factory=list)
    exclude_product_ids: list[str] = field(default_factory=list)


class ProductRepository:
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or connect()
        self.vectorizer = HashingVectorizer()
        self.semantic_store = TextEmbeddingStore(self.conn)
        self.retrieval_cache = RetrievalCache()
        self._lock = threading.RLock()

    def all(self) -> list[Product]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
        return [self._row_to_product(row) for row in rows]

    def get(self, product_id: str) -> Product | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
        return self._row_to_product(row) if row else None

    def get_rag(self, product_id: str) -> dict:
        with self._lock:
            row = self.conn.execute("SELECT rag_json FROM products WHERE product_id=?", (product_id,)).fetchone()
        if not row:
            return {}
        payload = json.loads(row["rag_json"])
        return payload if isinstance(payload, dict) else {}

    def search(self, query: str, constraints: SearchConstraints, limit: int = 5) -> list[Product]:
        with self._lock:
            return self._search_locked(query, constraints, limit)

    def _search_locked(self, query: str, constraints: SearchConstraints, limit: int) -> list[Product]:
        started_at = time.perf_counter()
        cache_key = self.retrieval_cache.key(
            query=query,
            constraints=constraints,
            limit=limit,
            retrieval_identity=self._retrieval_identity(),
        )
        cached = self.retrieval_cache.get(cache_key)
        if cached:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            observability.increment("retrieval_requests")
            observability.increment("retrieval_cache_hits")
            observability.record_latency("retrieval_latency_ms", elapsed_ms)
            observability.add_current_step(
                "retrieval",
                {
                    "query": query,
                    "constraints": self._constraints_payload(constraints),
                    "returned": len(cached.products),
                    "top_product_ids": [product.product_id for product in cached.products[:5]],
                    "retrieval_stack": cached.retrieval_stack,
                    "cache_hit": True,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            return cached.products

        observability.increment("retrieval_cache_misses")
        rows = self._candidate_rows(constraints)
        query_vector = self.vectorizer.embed(self._query_text(query, constraints))
        semantic_query_vector = self.semantic_store.embed_query(self._query_text(query, constraints))
        candidate_rows: list[sqlite3.Row] = []
        for row in rows:
            if not self._matches_constraints(row, constraints):
                continue
            candidate_rows.append(row)
        bm25 = BM25Scorer([(row["product_id"], row["search_text"]) for row in candidate_rows])
        bm25_scores = bm25.normalized_scores(query, [row["product_id"] for row in candidate_rows])
        vector_scores: dict[str, float] = {}
        semantic_vector_hits = 0
        structured_scores: dict[str, float] = {}
        scored: list[tuple[float, sqlite3.Row, dict[str, float | str]]] = []
        for row in candidate_rows:
            vector = json.loads(row["vector_json"])
            hashing_vector_score = self.vectorizer.similarity(query_vector, vector)
            semantic_vector = (
                self.semantic_store.vector_for_product(row["product_id"], row["search_text"])
                if semantic_query_vector is not None
                else None
            )
            if semantic_query_vector is not None and semantic_vector is not None:
                vector_score = cosine_similarity(semantic_query_vector, semantic_vector)
                semantic_vector_hits += 1
                vector_backend = "text_embedding"
            else:
                vector_score = hashing_vector_score
                vector_backend = "hashing_vector"
            structured_score = self._structured_boost(row, query, constraints)
            vector_scores[row["product_id"]] = vector_score
            structured_scores[row["product_id"]] = structured_score
            score_parts: dict[str, float | str] = {
                "bm25": bm25_scores.get(row["product_id"], 0.0),
                "vector": vector_score,
                "hashing_vector": hashing_vector_score,
                "structured": structured_score,
                "trust": self._trust_score(row),
                "vector_backend": vector_backend,
            }
            score = self._hybrid_score(score_parts)
            scored.append((score, row, score_parts))
        scored.sort(key=lambda item: item[0], reverse=True)
        products = [self._row_to_product(row) for score, row, parts in scored[:limit]]
        for product, (score, row, parts) in zip(products, scored[:limit]):
            product.reason = self._reason(product, query, constraints, score)
            product.match_score = self._match_score(product, query, constraints, score)
            product.match_reasons = self._match_reasons(product, query, constraints)
            product.match_reasons.append(self._hybrid_reason(parts))
            product.risk_flags = self._risk_flags(product, constraints)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        retrieval_stack = self._retrieval_stack(semantic_vector_hits, len(candidate_rows))
        self.retrieval_cache.set(cache_key, products, retrieval_stack)
        observability.increment("retrieval_requests")
        observability.record_latency("retrieval_latency_ms", elapsed_ms)
        observability.add_current_step(
            "retrieval",
            {
                "query": query,
                "constraints": self._constraints_payload(constraints),
                "total_candidates": len(rows),
                "matched_candidates": len(candidate_rows),
                "returned": len(products),
                "top_product_ids": [product.product_id for product in products[:5]],
                "retrieval_stack": retrieval_stack,
                "semantic_vector_hits": semantic_vector_hits,
                "cache_hit": False,
                "latency_ms": round(elapsed_ms, 2),
            },
        )
        return products

    def alternatives(
        self,
        product_id: str,
        mode: str,
        query: str = "",
        excluded_brands: list[str] | None = None,
        limit: int = 3,
    ) -> list[Product]:
        base = self.get(product_id)
        if not base:
            return []
        max_price = None
        min_price = None
        exclude_brands = list(excluded_brands or [])
        if mode == "cheaper":
            max_price = max(1, base.base_price * 0.82)
        elif mode == "premium":
            min_price = base.base_price * 1.08
        elif mode == "brand_excluded" and base.brand not in exclude_brands:
            exclude_brands.append(base.brand)
        constraints = SearchConstraints(
            category=base.category,
            sub_category=base.sub_category,
            max_price=max_price,
            min_price=min_price,
            include_terms=self._alternative_terms(base, query),
            exclude_brands=exclude_brands,
            exclude_product_ids=[base.product_id],
        )
        results = self.search(f"{query} {base.title} {base.sub_category}", constraints, limit=limit)
        if not results and constraints.sub_category:
            relaxed = SearchConstraints(
                category=base.category,
                max_price=max_price,
                min_price=min_price,
                include_terms=self._alternative_terms(base, query),
                exclude_brands=exclude_brands,
                exclude_product_ids=[base.product_id],
            )
            results = self.search(f"{query} {base.category}", relaxed, limit=limit)
        for product in results:
            if mode == "cheaper":
                if product.sub_category == base.sub_category:
                    product.reason = f"作为平替：保留 {base.sub_category} 类目，价格从 {base.base_price:.0f} 元降到约 {product.base_price:.0f} 元。"
                else:
                    product.reason = f"作为平替：保留 {base.category} 类目和核心偏好，价格从 {base.base_price:.0f} 元降到约 {product.base_price:.0f} 元。"
            elif mode == "premium":
                product.reason = f"作为升级款：保留 {base.sub_category} 类目，价格更高，优先看匹配度和来源证据。"
            else:
                product.reason = f"作为换品牌替代：已避开 {base.brand}，仍保持 {base.sub_category} 类目。"
            product.match_reasons.insert(0, "替代品逻辑：同类目/同子类目 + 预算/品牌约束 + 混合检索重排")
        observability.increment(f"alternative_{mode}_requests")
        observability.add_current_step(
            "alternatives",
            {
                "base_product_id": product_id,
                "mode": mode,
                "returned": len(results),
                "product_ids": [product.product_id for product in results],
            },
        )
        return results

    def _candidate_rows(self, constraints: SearchConstraints) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[object] = []
        if constraints.category:
            clauses.append("p.category = ?")
            params.append(constraints.category)
        if constraints.max_price is not None:
            clauses.append("p.base_price <= ?")
            params.append(constraints.max_price)
        if constraints.min_price is not None:
            clauses.append("p.base_price >= ?")
            params.append(constraints.min_price)
        if constraints.exclude_product_ids:
            placeholders = ",".join("?" for _ in constraints.exclude_product_ids)
            clauses.append(f"p.product_id NOT IN ({placeholders})")
            params.extend(constraints.exclude_product_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.conn.execute(
            f"""
            SELECT p.*, v.vector_json
            FROM products p
            JOIN product_vectors v ON p.product_id = v.product_id
            {where}
            ORDER BY p.product_id
            """,
            tuple(params),
        ).fetchall()

    def _matches_constraints(self, row: sqlite3.Row, c: SearchConstraints) -> bool:
        text = row["search_text"].lower()
        brand = row["brand"].lower()
        if c.category and c.category != row["category"]:
            return False
        if row["product_id"] in c.exclude_product_ids:
            return False
        title = row["title"].lower()
        if c.sub_category and not self._matches_sub_category(row, c.sub_category, title, text):
            return False
        if c.max_price is not None and row["base_price"] > c.max_price:
            return False
        if c.min_price is not None and row["base_price"] < c.min_price:
            return False
        if any(term.lower() not in text for term in c.include_terms):
            return False
        if any(self._contains_excluded(text, term.lower()) for term in c.exclude_terms):
            return False
        if any(ex.lower() in brand or ex.lower() in text for ex in c.exclude_brands):
            return False
        return True

    def _matches_sub_category(self, row: sqlite3.Row, sub_category: str, title: str, text: str) -> bool:
        normalized = sub_category.lower()
        row_sub = row["sub_category"].lower()
        strict_aliases = {
            "手机": ["智能手机", "手机"],
            "智能手机": ["智能手机", "手机"],
            "耳机": ["蓝牙耳机", "真无线耳机", "耳机"],
            "蓝牙耳机": ["蓝牙耳机", "真无线耳机", "耳机"],
            "充电器": ["充电器", "快充充电器", "充电设备", "charger"],
            "充电设备": ["充电设备"],
            "充电宝": ["充电宝", "移动电源", "power bank"],
            "防晒": ["防晒"],
            "面霜": ["面霜"],
            "精华": ["精华"],
            "帽子": ["帽子", "遮阳帽", "棒球帽", "鸭舌帽"],
            "背包": ["背包", "双肩包", "通勤包"],
            "徒步鞋": ["徒步鞋", "登山鞋"],
            "速干t恤": ["速干t恤", "速干T恤", "速干短袖", "t恤", "T恤"],
            "运动服饰": ["运动服饰", "防晒衣", "运动裤", "瑜伽裤", "短裤"],
            "运动鞋": ["运动鞋", "跑步鞋", "跑鞋", "篮球鞋"],
            "功能饮料": ["功能饮料", "维生素饮料"],
            "咖啡": ["咖啡"],
            "坚果/零食": ["坚果/零食", "坚果", "零食", "肉松饼"],
            "方便食品": ["方便食品", "方便面", "泡面", "速食"],
        }
        aliases = strict_aliases.get(normalized)
        if aliases:
            row_only_aliases = {
                "充电设备",
                "防晒",
                "面霜",
                "精华",
                "帽子",
                "背包",
                "徒步鞋",
                "速干t恤",
                "功能饮料",
                "咖啡",
                "坚果/零食",
                "方便食品",
            }
            if normalized in row_only_aliases:
                return any(alias.lower() in row_sub for alias in aliases)
            return any(alias in row_sub or alias in title for alias in aliases)
        return normalized in row_sub or normalized in title or normalized in text

    def _hybrid_score(self, parts: dict[str, float | str]) -> float:
        return (
            float(parts["bm25"]) * 0.32
            + float(parts["vector"]) * 0.34
            + float(parts["structured"]) * 0.22
            + float(parts["trust"]) * 0.12
        )

    def _trust_score(self, row: sqlite3.Row) -> float:
        rag = json.loads(row["rag_json"])
        reviews = rag.get("user_reviews") if isinstance(rag.get("user_reviews"), list) else []
        marketing = str(rag.get("marketing_description") or "")
        score = 0.0
        if self._source_url(marketing):
            score += 0.45
        if reviews:
            score += min(0.35, 0.07 * len(reviews))
        if json.loads(row["skus_json"]):
            score += 0.2
        return min(1.0, score)

    def _hybrid_reason(self, parts: dict[str, float | str]) -> str:
        vector_label = "语义向量" if parts.get("vector_backend") == "text_embedding" else "本地向量"
        return (
            "混合检索："
            f"BM25 {float(parts['bm25']) * 100:.0f} / "
            f"{vector_label} {max(0, float(parts['vector'])) * 100:.0f} / "
            f"结构化 {float(parts['structured']) * 100:.0f} / "
            f"可信度 {float(parts['trust']) * 100:.0f}"
        )

    def _retrieval_stack(self, semantic_vector_hits: int, candidate_count: int) -> str:
        if semantic_vector_hits and semantic_vector_hits == candidate_count:
            provider, model = self.semantic_store.identity
            return f"structured_filter + BM25 + text_embedding({provider}/{model}) + trust_reranker"
        if semantic_vector_hits:
            provider, model = self.semantic_store.identity
            return f"structured_filter + BM25 + hybrid_text_embedding({provider}/{model}) + hashing_fallback + trust_reranker"
        return "structured_filter + BM25 + hashing_vector + trust_reranker"

    def _retrieval_identity(self) -> dict:
        provider, model = self.semantic_store.identity
        semantic_configured = self.semantic_store.is_configured
        return {
            "hashing_dimensions": self.vectorizer.dimensions,
            "semantic_configured": semantic_configured,
            "semantic_provider": provider if semantic_configured else None,
            "semantic_model": model if semantic_configured else None,
        }

    def _contains_excluded(self, text: str, term: str) -> bool:
        if not term:
            return False
        if term not in text:
            return False
        safe_phrases = [
            f"不含{term}",
            f"无{term}",
            f"没有{term}",
            f"未添加{term}",
            f"不添加{term}",
            f"0{term}",
        ]
        if any(phrase in text for phrase in safe_phrases):
            return False
        return True

    def _structured_boost(self, row: sqlite3.Row, query: str, c: SearchConstraints) -> float:
        score = 0.0
        text = row["search_text"]
        for term in c.include_terms:
            if term and term in text:
                score += 0.12
        if row["sub_category"] and row["sub_category"] in query:
            score += 0.2
        if row["brand"] and row["brand"] in query:
            score += 0.2
        return score

    def _query_text(self, query: str, c: SearchConstraints) -> str:
        parts = [query]
        if c.category:
            parts.append(c.category)
        if c.sub_category:
            parts.append(c.sub_category)
        parts.extend(c.include_terms)
        return " ".join(parts)

    def _constraints_payload(self, c: SearchConstraints) -> dict:
        return {
            "category": c.category,
            "sub_category": c.sub_category,
            "max_price": c.max_price,
            "min_price": c.min_price,
            "include_terms": c.include_terms,
            "exclude_terms": c.exclude_terms,
            "exclude_brands": c.exclude_brands,
            "exclude_product_ids": c.exclude_product_ids,
        }

    def _alternative_terms(self, product: Product, query: str) -> list[str]:
        terms = []
        for term in ["油皮", "防晒", "敏感肌", "拍照", "续航", "快充", "低糖", "轻量", "控油"]:
            if term in query or term in self._product_text(product):
                terms.append(term)
        return terms[:4]

    def _row_to_product(self, row: sqlite3.Row) -> Product:
        rag = json.loads(row["rag_json"])
        marketing = rag.get("marketing_description", "")
        highlights = [part.strip(" ，。") for part in marketing.split("，")[:3] if part.strip()]
        source_url = self._source_url(marketing)
        source_name = self._source_name(source_url)
        reviews = rag.get("user_reviews") if isinstance(rag.get("user_reviews"), list) else []
        ratings = [float(review["rating"]) for review in reviews if isinstance(review, dict) and review.get("rating")]
        evidence = self._evidence(rag, highlights, source_url)
        skus: list[SKU] = []
        for raw_sku in json.loads(row["skus_json"]):
            payload = dict(raw_sku)
            if not payload.get("image_url"):
                sku_image = self._sku_image_path(raw_sku["sku_id"])
                if sku_image:
                    payload["image_url"] = f"/static/product_images/{sku_image.name}"
            if not payload.get("image_url"):
                payload["image_url"] = row["image_url"]
                payload["image_source_url"] = source_url or row["image_url"]
            skus.append(SKU(**payload))
        return Product(
            product_id=row["product_id"],
            title=row["title"],
            brand=row["brand"],
            category=row["category"],
            sub_category=row["sub_category"],
            base_price=row["base_price"],
            image_url=row["image_url"],
            skus=skus,
            highlights=highlights,
            source_url=source_url,
            source_name=source_name,
            evidence=evidence,
            average_rating=round(sum(ratings) / len(ratings), 1) if ratings else None,
            review_count=len(reviews),
        )

    def _reason(self, product: Product, query: str, c: SearchConstraints, score: float) -> str:
        facts = [f"{product.brand} {product.sub_category}", f"到手参考价约 {product.base_price:.0f} 元"]
        if c.max_price:
            facts.append(f"符合 {c.max_price:.0f} 元以内预算")
        if product.highlights:
            facts.append(product.highlights[0])
        return "；".join(facts)

    def _match_score(self, product: Product, query: str, c: SearchConstraints, retrieval_score: float) -> int:
        score = 42 + min(24, max(0, int(retrieval_score * 22)))
        text = self._product_text(product)
        if c.category and c.category == product.category:
            score += 8
        if c.sub_category and (c.sub_category in product.sub_category or c.sub_category.lower() in text.lower()):
            score += 8
        if c.max_price is not None and product.base_price <= c.max_price:
            score += 8
        if c.min_price is not None and product.base_price >= c.min_price:
            score += 4
        score += min(12, 4 * sum(1 for term in c.include_terms if term and term.lower() in text.lower()))
        if c.exclude_terms or c.exclude_brands:
            score += 5
        if product.source_url:
            score += 3
        if product.review_count:
            score += 3
        return max(0, min(98, score))

    def _match_reasons(self, product: Product, query: str, c: SearchConstraints) -> list[str]:
        reasons: list[str] = []
        text = self._product_text(product).lower()
        if c.category:
            reasons.append(f"命中类目：{product.category}")
        if c.sub_category and (c.sub_category in product.sub_category or c.sub_category.lower() in text):
            reasons.append(f"命中子类目/标签：{c.sub_category}")
        if c.max_price is not None:
            reasons.append(f"价格 {product.base_price:.0f} 元，符合 {c.max_price:.0f} 元以内预算")
        if c.min_price is not None:
            reasons.append(f"价格 {product.base_price:.0f} 元，符合 {c.min_price:.0f} 元以上要求")
        for term in c.include_terms[:3]:
            if term and term.lower() in text:
                reasons.append(f"包含偏好：{term}")
        query_terms = [
            term
            for term in ["快充", "充电器", "充电宝", "多设备", "油皮", "防晒", "敏感肌", "拍照", "续航", "游戏", "低糖", "咖啡"]
            if term in query and term.lower() in text
        ]
        for term in query_terms[:3]:
            reasons.append(f"命中查询词：{term}")
        excluded = list(dict.fromkeys(c.exclude_terms + c.exclude_brands))
        if excluded:
            reasons.append("已过滤排除项：" + "、".join(excluded[:3]))
        if product.source_url:
            reasons.append(f"有公开来源：{product.source_name}")
        elif product.source_name:
            reasons.append(f"来源：{product.source_name}")
        if product.average_rating and product.review_count:
            reasons.append(f"评论均分 {product.average_rating:.1f}，共 {product.review_count} 条")
        if product.skus:
            reasons.append(f"提供 {len(product.skus)} 个可选 SKU")
        if not reasons and product.highlights:
            reasons.extend(product.highlights[:2])
        return reasons[:6]

    def _risk_flags(self, product: Product, c: SearchConstraints) -> list[str]:
        risks: list[str] = []
        if c.max_price is not None and product.base_price > c.max_price * 0.9:
            risks.append("价格接近预算上限")
        if not product.source_url:
            risks.append("缺少公开页面链接，主要依据本地商品库")
        if product.review_count == 0:
            risks.append("暂无用户评论，口碑证据不足")
        if product.average_rating is not None and product.average_rating < 3.6:
            risks.append(f"评论均分 {product.average_rating:.1f}，需关注负反馈")
        if not product.skus:
            risks.append("暂无可选规格")
        return risks[:4]

    def _product_text(self, product: Product) -> str:
        parts = [
            product.title,
            product.brand,
            product.category,
            product.sub_category,
            product.reason,
            " ".join(product.highlights),
            " ".join(product.evidence),
        ]
        return " ".join(part for part in parts if part)

    def _sku_image_path(self, sku_id: str):
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            path = PRODUCT_IMAGE_DIR / f"{sku_id}{suffix}"
            if path.exists():
                return path
        return None

    def _source_url(self, marketing: str) -> str | None:
        match = re.search(r"公开来源链接[：:]\s*(https?://[^\s，。]+)", marketing)
        return match.group(1) if match else None

    def _source_name(self, source_url: str | None) -> str:
        if not source_url:
            return "赛题示例商品库"
        host = re.sub(r"^www\.", "", source_url.split("/")[2])
        return host

    def _evidence(self, rag: dict, highlights: list[str], source_url: str | None) -> list[str]:
        evidence = [item for item in highlights[:2] if item]
        faqs = rag.get("official_faq") if isinstance(rag.get("official_faq"), list) else []
        for faq in faqs[:2]:
            if not isinstance(faq, dict):
                continue
            answer = str(faq.get("answer") or "").strip()
            if answer:
                evidence.append(answer[:90])
        if source_url:
            evidence.append(f"公开页面采集：{source_url}")
        return list(dict.fromkeys(evidence))[:4]
