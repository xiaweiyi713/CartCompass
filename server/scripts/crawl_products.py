from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from data_pipeline.cleaners.normalize_product import write_clean_products
from data_pipeline.crawlers.base_crawler import load_targets
from data_pipeline.crawlers.dynamic_page_crawler import crawl_sync
from data_pipeline.crawlers.static_page_crawler import StaticPageCrawler
from data_pipeline.exporters.export_to_sqlite import export_products_to_sqlite, load_clean_products


SERVER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SERVER_DIR / "data_pipeline" / "configs" / "crawl_targets.example.yaml"
DEFAULT_RAW_OUTPUT = SERVER_DIR / "data_pipeline" / "output" / "products_raw.json"
DEFAULT_CLEAN_OUTPUT = SERVER_DIR / "data_pipeline" / "output" / "products_clean.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl public product pages, normalize them, and optionally import into SQLite.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--clean-output", type=Path, default=DEFAULT_CLEAN_OUTPUT)
    parser.add_argument("--mode", choices=["static", "dynamic", "clean-only", "ingest-only"], default="static")
    parser.add_argument("--product-prefix", default="p_collected")
    parser.add_argument("--usd-cny-rate", type=float, default=6.8, help="USD to CNY rate used during cleaning.")
    parser.add_argument("--ingest", action="store_true", help="Append/replace cleaned products in the local SQLite database.")
    parser.add_argument("--no-replace", action="store_true", help="Use INSERT OR IGNORE instead of INSERT OR REPLACE on import.")
    parser.add_argument("--skip-image-cache", action="store_true", help="Keep remote image URLs instead of caching them under server/static.")
    args = parser.parse_args()

    if args.mode in {"static", "dynamic"}:
        currency_rates = {"USD": args.usd_cny_rate}
        targets = load_targets(args.config)
        if args.mode == "static":
            StaticPageCrawler().crawl_to_file(targets, args.raw_output)
        else:
            crawl_sync(targets, args.raw_output)
        products = write_clean_products(args.raw_output, args.clean_output, args.product_prefix, currency_rates)
    elif args.mode == "clean-only":
        products = write_clean_products(args.raw_output, args.clean_output, args.product_prefix, {"USD": args.usd_cny_rate})
    else:
        products = load_clean_products(args.clean_output)

    if args.ingest or args.mode == "ingest-only":
        count = export_products_to_sqlite(
            products,
            replace_existing=not args.no_replace,
            cache_images=not args.skip_image_cache,
        )
        print(f"ingested {count} collected products into SQLite")
    else:
        print(f"wrote {len(products)} clean products to {args.clean_output}")


if __name__ == "__main__":
    main()
