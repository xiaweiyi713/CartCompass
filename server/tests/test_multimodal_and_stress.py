from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.rag.image_search import ImageSearchService
from app.rag.image_understanding import ImageUnderstandingResult, OptionalVisionImageUnderstanding
from app.rag.product_repository import ProductRepository, SearchConstraints


class FakeImageUnderstanding:
    provider = "fake_vlm"

    def analyze(self, image, query: str = "") -> ImageUnderstandingResult:  # noqa: ANN001
        return ImageUnderstandingResult(
            category="数码电子",
            sub_category="充电设备",
            keywords=["快充", "充电器"],
            attributes=["白色"],
            confidence=0.9,
            provider=self.provider,
            available=True,
        )


def test_vlm_understanding_parser_validates_shopping_taxonomy() -> None:
    adapter = OptionalVisionImageUnderstanding(base_url="http://example.test", model="vision", api_key="key")

    result = adapter._parse(
        """```json
        {"category":"数码充电配件","sub_category":"双口USB-C PD快充墙充","keywords":["快充","库存充足"],"attributes":["白色"],"confidence":1.7}
        ```"""
    )

    assert result.available
    assert result.category == "数码电子"
    assert result.sub_category == "充电设备"
    assert result.keywords == ["快充"]
    assert result.attributes == ["白色"]
    assert result.confidence == 1.0


def test_image_search_fuses_text_query() -> None:
    service = ImageSearchService(ProductRepository())
    image_path = Path("server/static/product_images/p_digital_016.jpg")
    products = service.search(image_path.read_bytes(), query="手机 续航", limit=5)

    assert products
    assert products[0].match_score > 0
    assert any("视觉相似度" in reason for reason in products[0].match_reasons)
    assert any("语义图像" in reason or "CLIP" in reason for reason in products[0].match_reasons)
    assert any("文本筛选" in reason for reason in products[0].match_reasons)
    assert products[0].risk_flags


def test_image_search_uses_vlm_understanding_terms_without_text_query() -> None:
    service = ImageSearchService(ProductRepository())
    service.image_understanding = FakeImageUnderstanding()
    image_path = Path("server/static/product_images/p_digital_016.jpg")

    products = service.search(image_path.read_bytes(), query="", limit=5)

    assert products
    assert any(product.sub_category == "充电设备" for product in products)
    assert any("VLM图像理解" in reason for reason in products[0].match_reasons)
    assert any("已启用VLM图像理解" in flag for flag in products[0].risk_flags)


def test_concurrent_retrieval_stays_stable() -> None:
    queries = [
        "推荐手机",
        "油皮 防晒 不含酒精",
        "Anker 100W 快充",
        "三亚 海边 防晒",
        "低糖 咖啡",
        "运动裤 户外",
    ] * 20

    def run(query: str) -> int:
        repo = ProductRepository()
        return len(repo.search(query, SearchConstraints(), limit=5))

    with ThreadPoolExecutor(max_workers=12) as pool:
        counts = list(pool.map(run, queries))

    assert len(counts) == len(queries)
    assert max(counts) > 0
