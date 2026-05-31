from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from PIL import Image

from app.config import (
    VISION_UNDERSTANDING_API_KEY,
    VISION_UNDERSTANDING_BASE_URL,
    VISION_UNDERSTANDING_IMAGE_DETAIL,
    VISION_UNDERSTANDING_JSON_MODE,
    VISION_UNDERSTANDING_MAX_IMAGE_SIDE,
    VISION_UNDERSTANDING_MAX_TOKENS,
    VISION_UNDERSTANDING_MODEL,
)
from app.rag.image_search import ImageSearchService
from app.rag.image_understanding import ImageUnderstandingResult, OptionalVisionImageUnderstanding
from app.rag.product_repository import ProductRepository


DEFAULT_IMAGE = Path("server/static/product_images/p_anker_001_fc881685.jpg")


class CachedUnderstanding:
    def __init__(self, provider: str, result: ImageUnderstandingResult) -> None:
        self.provider = provider
        self.result = result

    def analyze(self, image, query: str = "") -> ImageUnderstandingResult:  # noqa: ANN001
        return self.result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the real VLM image-understanding endpoint and fused image search.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--query", default="", help="Optional text query fused with image-understanding terms.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--base-url", default=VISION_UNDERSTANDING_BASE_URL)
    parser.add_argument("--model", default=VISION_UNDERSTANDING_MODEL)
    parser.add_argument("--api-key-env", default="VISION_UNDERSTANDING_API_KEY")
    parser.add_argument("--detail", default=VISION_UNDERSTANDING_IMAGE_DETAIL, choices=["low", "high", "auto", "none"])
    parser.add_argument("--max-image-side", type=int, default=VISION_UNDERSTANDING_MAX_IMAGE_SIDE)
    parser.add_argument("--max-tokens", type=int, default=VISION_UNDERSTANDING_MAX_TOKENS)
    parser.add_argument("--json-mode", action="store_true", default=VISION_UNDERSTANDING_JSON_MODE)
    args = parser.parse_args()

    api_key = os.getenv(args.api_key_env) or VISION_UNDERSTANDING_API_KEY
    print("vision_probe_config")
    print(f"  image={args.image}")
    print(f"  base_url={args.base_url}")
    print(f"  model={args.model}")
    print(f"  api_key_present={bool(api_key)}")
    print(f"  detail={args.detail}")
    print(f"  max_image_side={args.max_image_side}")
    print(f"  max_tokens={args.max_tokens}")
    print(f"  json_mode={args.json_mode}")
    if not args.model or not api_key:
        print("missing_config=Set VISION_UNDERSTANDING_MODEL and VISION_UNDERSTANDING_API_KEY, or export ARK_API_KEY.")
        return 2
    if not args.image.exists():
        print(f"missing_image={args.image}")
        return 2

    detail = "" if args.detail == "none" else args.detail
    adapter = OptionalVisionImageUnderstanding(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        image_detail=detail,
        max_image_side=args.max_image_side,
        max_tokens=args.max_tokens,
        json_mode=args.json_mode,
    )

    started = time.perf_counter()
    with Image.open(args.image) as image:
        understanding = adapter.analyze(image, query=args.query)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print("vision_understanding_result")
    print(f"  available={understanding.available}")
    print(f"  provider={understanding.provider}")
    print(f"  latency_ms={elapsed_ms:.2f}")
    print(f"  category={understanding.category}")
    print(f"  sub_category={understanding.sub_category}")
    print(f"  keywords={understanding.keywords or []}")
    print(f"  attributes={understanding.attributes or []}")
    print(f"  confidence={understanding.confidence:.2f}")
    if not understanding.available:
        return 1

    service = ImageSearchService(ProductRepository())
    service.image_understanding = CachedUnderstanding(adapter.provider, understanding)
    products = service.search(args.image.read_bytes(), query=args.query, limit=args.limit)
    print("fused_image_search_top")
    for index, product in enumerate(products, start=1):
        print(
            f"  {index}. {product.product_id} | {product.title} | "
            f"{product.category}/{product.sub_category} | score={product.match_score}"
        )
        print(f"     reason={product.reason}")
        print(f"     match_reasons={' ; '.join(product.match_reasons[:5])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
