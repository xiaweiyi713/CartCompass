from __future__ import annotations

import asyncio
import io
import math
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat

from app.config import PRODUCT_IMAGE_DIR
from app.models.schemas import Product
from app.observability import observability
from app.rag.image_understanding import ImageUnderstandingResult, OptionalVisionImageUnderstanding
from app.rag.product_repository import ProductRepository, SearchConstraints
from app.rag.semantic_image import OptionalSemanticImageEncoder
from app.rag.semantic_text import cosine_similarity


@dataclass(frozen=True)
class ImageFeatures:
    histogram: list[float]
    mean: list[float]
    aspect: float
    grid: list[float]
    average_hash: tuple[bool, ...]


class ImageSearchService:
    """Lightweight visual search for the MVP.

    This compares color histograms and average color against local product
    images. A CLIP/UForm embedding implementation can replace this class while
    keeping the API contract unchanged.
    """

    def __init__(self, products: ProductRepository) -> None:
        self.products = products
        self._feature_cache: dict[str, ImageFeatures] = {}
        self.semantic_encoder = OptionalSemanticImageEncoder()
        self.image_understanding = OptionalVisionImageUnderstanding()

    async def search_async(self, image_bytes: bytes, query: str = "", limit: int = 5) -> list[Product]:
        return await asyncio.to_thread(self.search, image_bytes, query=query, limit=limit)

    def search(self, image_bytes: bytes, query: str = "", limit: int = 5) -> list[Product]:
        started_at = time.perf_counter()
        query_image = self._image_from_bytes(image_bytes)
        query_features = self._features(query_image)
        understanding = self.image_understanding.analyze(query_image, query=query)
        # Cross-modal: embed the uploaded image into the shared image-text space
        # and compare against products' cached text vectors. The strongest
        # semantic signal when a multimodal embedding model is configured.
        embed_client = self.products.semantic_store.client
        query_embed = (
            embed_client.embed_image(image_bytes)
            if embed_client.is_configured and embed_client.is_multimodal
            else None
        )
        visual_scores: dict[str, float] = {}
        semantic_scores: dict[str, float] = {}
        embed_scores: dict[str, float] = {}
        semantic_available = self.semantic_encoder.available
        for product in self.products.all():
            image_path = PRODUCT_IMAGE_DIR / f"{product.product_id}.jpg"
            if not image_path.exists():
                continue
            try:
                candidate_features = self._cached_features(product.product_id, image_path)
                if semantic_available:
                    with Image.open(image_path) as candidate_image:
                        semantic = self.semantic_encoder.image_similarity(query_image, candidate_image)
                        if semantic.score is not None:
                            semantic_scores[product.product_id] = semantic.score
            except OSError:
                continue
            visual_scores[product.product_id] = self._similarity(query_features, candidate_features)
            if query_embed is not None:
                product_vec = self.products.semantic_store.cached_vector(product.product_id)
                if product_vec:
                    embed_scores[product.product_id] = max(0.0, cosine_similarity(query_embed, product_vec))

        intent_query = self._intent_query(query, understanding)
        text_ranks = self._text_ranks(intent_query, understanding, limit=max(limit * 4, 20)) if intent_query else {}
        candidate_ids = set(visual_scores)
        candidate_ids.update(text_ranks)
        candidate_ids.update(embed_scores)

        scored: list[tuple[float, Product]] = []
        for product_id in candidate_ids:
            product = self.products.get(product_id)
            if not product:
                continue
            visual_score = visual_scores.get(product_id, 0.0)
            text_score = text_ranks.get(product_id, 0.0)
            semantic_score = semantic_scores.get(product_id)
            embed_score = embed_scores.get(product_id)
            understanding_score = self._understanding_score(product, understanding)
            fused_score = self._fused_score(
                embed_score,
                semantic_score,
                visual_score,
                text_score,
                bool(intent_query),
                understanding_score,
                understanding.available,
            )
            product.reason = self._reason(embed_score, semantic_score, visual_score, text_score, query, understanding, understanding_score)
            product.match_score = int(fused_score * 100)
            product.match_reasons = self._match_reasons(
                semantic_score,
                visual_score,
                text_score,
                query,
                understanding,
                understanding_score,
            )
            if embed_score is not None:
                product.match_reasons.insert(0, f"语义图文匹配 {embed_score * 100:.0f}%（多模态向量,拍照找货)")
            product.risk_flags = [
                self._semantic_status(semantic_available),
                self._understanding_status(understanding),
                "图文融合检索用于缩小候选，仍需核对规格、来源和价格",
            ]
            scored.append((fused_score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [product for _, product in scored[:limit]]
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        observability.increment("image_search_requests")
        observability.record_latency("image_search_latency_ms", elapsed_ms)
        observability.add_current_step(
            "image_search",
            {
                "query": query,
                "candidate_count": len(scored),
                "returned": len(results),
                "semantic_provider": self.semantic_encoder.provider,
                "semantic_available": semantic_available,
                "vision_understanding_provider": understanding.provider,
                "vision_understanding_available": understanding.available,
                "vision_understanding_category": understanding.category,
                "vision_understanding_sub_category": understanding.sub_category,
                "vision_understanding_terms": understanding.terms,
                "top_product_ids": [product.product_id for product in results[:5]],
                "latency_ms": round(elapsed_ms, 2),
            },
        )
        return results

    def _text_ranks(self, query: str, understanding: ImageUnderstandingResult, limit: int) -> dict[str, float]:
        constraints = SearchConstraints(
            category=understanding.category if understanding.available else None,
            sub_category=understanding.sub_category if understanding.available else None,
        )
        results = self.products.search(query, constraints, limit=limit)
        count = max(len(results), 1)
        return {product.product_id: 1.0 - index / count for index, product in enumerate(results)}

    def _fused_score(
        self,
        embed_score: float | None,
        semantic_score: float | None,
        visual_score: float,
        text_score: float,
        has_text_signal: bool,
        understanding_score: float,
        has_understanding: bool,
    ) -> float:
        weighted: list[tuple[float, float]] = []
        if embed_score is not None:
            # Multimodal image-text embedding is the dominant cross-modal signal.
            weighted.append((embed_score, 0.52))
            weighted.append((visual_score, 0.18))
            if semantic_score is not None:
                weighted.append((semantic_score, 0.12))
            if has_text_signal:
                weighted.append((text_score, 0.12))
        elif semantic_score is not None:
            weighted.extend([(semantic_score, 0.42), (visual_score, 0.28)])
            if has_text_signal:
                weighted.append((text_score, 0.16))
        else:
            weighted.append((visual_score, 0.70 if not has_text_signal else 0.52))
            if has_text_signal:
                weighted.append((text_score, 0.26))
        if has_understanding:
            weighted.append((understanding_score, 0.20))
        total_weight = sum(weight for _, weight in weighted) or 1.0
        score = sum(score * weight for score, weight in weighted) / total_weight
        return max(0.0, min(1.0, score))

    def _reason(
        self,
        embed_score: float | None,
        semantic_score: float | None,
        visual_score: float,
        text_score: float,
        query: str,
        understanding: ImageUnderstandingResult,
        understanding_score: float,
    ) -> str:
        intent_query = self._intent_query(query, understanding)
        fused = self._fused_score(
            embed_score,
            semantic_score,
            visual_score,
            text_score,
            bool(intent_query),
            understanding_score,
            understanding.available,
        )
        if embed_score is not None:
            text_part = f"，文本意图 {text_score * 100:.1f}%" if intent_query else ""
            return (
                f"多模态图文向量匹配 {fused * 100:.1f}%："
                f"图文语义 {embed_score * 100:.1f}%，轻量视觉 {visual_score * 100:.1f}%{text_part}。"
            )
        if semantic_score is not None and intent_query:
            label = "CLIP语义+VLM图文融合" if understanding.available else "CLIP语义+图文融合"
            understanding_part = f"，图像理解 {understanding_score * 100:.1f}%" if understanding.available else ""
            return (
                f"{label}匹配 {fused * 100:.1f}%："
                f"语义图像 {semantic_score * 100:.1f}%，轻量视觉 {visual_score * 100:.1f}%"
                f"{understanding_part}，文本 {text_score * 100:.1f}%。"
            )
        if semantic_score is not None:
            return f"CLIP语义+轻量视觉匹配 {fused * 100:.1f}%：语义图像 {semantic_score * 100:.1f}%，颜色轮廓 {visual_score * 100:.1f}%。"
        if intent_query:
            label = "VLM图文融合" if understanding.available else "图文融合"
            understanding_part = f"，图像理解 {understanding_score * 100:.1f}%" if understanding.available else ""
            return (
                f"{label}匹配 {fused * 100:.1f}%："
                f"图片相似度 {visual_score * 100:.1f}%{understanding_part}，文本意图 {text_score * 100:.1f}%。"
            )
        return f"图片综合相似度 {visual_score * 100:.1f}%：颜色、轮廓和主体布局接近上传图片。"

    def _match_reasons(
        self,
        semantic_score: float | None,
        visual_score: float,
        text_score: float,
        query: str,
        understanding: ImageUnderstandingResult,
        understanding_score: float,
    ) -> list[str]:
        reasons = []
        if semantic_score is not None:
            reasons.append(f"CLIP语义图像相似度 {semantic_score * 100:.1f}%")
        else:
            reasons.append("语义图像模型未启用，使用轻量视觉 fallback")
        reasons.append(f"轻量视觉相似度 {visual_score * 100:.1f}%")
        if understanding.available:
            reasons.append(f"VLM图像理解：{' / '.join(understanding.terms[:6])}")
            reasons.append(f"图像理解匹配度 {understanding_score * 100:.1f}%")
        if query:
            reasons.append(f"文本筛选：{query}")
            if text_score > 0:
                reasons.append(f"文本匹配度 {text_score * 100:.1f}%")
        reasons.append("排序融合：VLM图像理解/语义图像/颜色轮廓/文本检索")
        return reasons

    def _semantic_status(self, available: bool) -> str:
        if available:
            return f"已启用语义图像检索：{self.semantic_encoder.provider}"
        return "语义图像模型未安装或未启用，已自动降级到轻量视觉检索"

    def _understanding_status(self, understanding: ImageUnderstandingResult) -> str:
        if understanding.available:
            return f"已启用VLM图像理解：{understanding.provider}"
        return "VLM图像理解未配置或调用失败，已自动降级到视觉相似检索"

    def _intent_query(self, query: str, understanding: ImageUnderstandingResult) -> str:
        terms = [query.strip()] if query.strip() else []
        if understanding.available:
            terms.extend(understanding.terms)
        return " ".join(term for term in terms if term)

    def _understanding_score(self, product: Product, understanding: ImageUnderstandingResult) -> float:
        if not understanding.available:
            return 0.0
        score = 0.0
        if understanding.category and understanding.category == product.category:
            score += 0.42
        if understanding.sub_category:
            product_sub = product.sub_category.lower()
            target_sub = understanding.sub_category.lower()
            haystack = self._product_text(product)
            if target_sub in product_sub or target_sub in haystack:
                score += 0.30
        terms = [term.lower() for term in (understanding.keywords or []) + (understanding.attributes or [])]
        if terms:
            haystack = self._product_text(product)
            matches = sum(1 for term in terms if term in haystack)
            score += 0.28 * matches / max(len(terms), 1)
        confidence = max(0.35, understanding.confidence)
        return max(0.0, min(1.0, score * confidence))

    def _product_text(self, product: Product) -> str:
        return " ".join(
            [
                product.title,
                product.brand,
                product.category,
                product.sub_category,
                " ".join(product.highlights),
                " ".join(product.evidence),
            ]
        ).lower()

    def _image_from_bytes(self, image_bytes: bytes) -> Image.Image:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return image.convert("RGB")

    def _features_from_bytes(self, image_bytes: bytes) -> ImageFeatures:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return self._features(image)

    def _cached_features(self, product_id: str, path: Path) -> ImageFeatures:
        if product_id not in self._feature_cache:
            self._feature_cache[product_id] = self._features_from_path(path)
        return self._feature_cache[product_id]

    def _features_from_path(self, path: Path) -> ImageFeatures:
        with Image.open(path) as image:
            return self._features(image)

    def _features(self, image: Image.Image) -> ImageFeatures:
        rgb = image.convert("RGB")
        thumbnail = rgb.resize((32, 32))
        histogram = thumbnail.histogram()
        total = sum(histogram) or 1
        normalized_histogram = [value / total for value in histogram]
        stat = ImageStat.Stat(thumbnail)
        mean = [channel / 255 for channel in stat.mean[:3]]
        aspect = min(rgb.width / max(rgb.height, 1), 3.0) / 3.0
        grid = [value / 255 for pixel in rgb.resize((8, 8)).getdata() for value in pixel]
        grayscale = rgb.resize((8, 8)).convert("L")
        gray_values = list(grayscale.getdata())
        gray_average = sum(gray_values) / max(len(gray_values), 1)
        average_hash = tuple(value >= gray_average for value in gray_values)
        return ImageFeatures(
            histogram=normalized_histogram,
            mean=mean,
            aspect=aspect,
            grid=grid,
            average_hash=average_hash,
        )

    def _similarity(self, left: ImageFeatures, right: ImageFeatures) -> float:
        histogram_score = sum(min(a, b) for a, b in zip(left.histogram, right.histogram))
        mean_distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(left.mean, right.mean)))
        mean_score = 1.0 - min(1.0, mean_distance / math.sqrt(3))
        aspect_score = 1.0 - min(1.0, abs(left.aspect - right.aspect))
        grid_rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(left.grid, right.grid)) / max(len(left.grid), 1))
        grid_score = 1.0 - min(1.0, grid_rmse * 1.35)
        hash_distance = sum(a != b for a, b in zip(left.average_hash, right.average_hash))
        hash_score = 1.0 - hash_distance / max(len(left.average_hash), 1)
        score = (
            histogram_score * 0.25
            + mean_score * 0.10
            + aspect_score * 0.05
            + grid_score * 0.45
            + hash_score * 0.15
        )
        return max(0.0, min(1.0, score))
