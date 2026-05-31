from __future__ import annotations

import argparse
import csv
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.product_repository import ProductRepository, SearchConstraints


DEFAULT_KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
DEFAULT_CACHE_DIR = Path("server/data_pipeline/output/kaggle_stress")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test ShopGuide retrieval with Kaggle or local ecommerce CSV data.")
    parser.add_argument("--dataset", default=DEFAULT_KAGGLE_DATASET, help="Kaggle dataset slug, e.g. olistbr/brazilian-ecommerce")
    parser.add_argument("--csv-dir", type=Path, help="Use an already downloaded CSV directory instead of Kaggle download")
    parser.add_argument("--sample", type=int, default=1000, help="Number of queries to run")
    parser.add_argument("--concurrency", type=int, default=16, help="Concurrent worker count")
    parser.add_argument("--p95-ms", type=float, default=250.0, help="Fail if p95 latency exceeds this value")
    args = parser.parse_args()

    csv_dir = args.csv_dir or download_kaggle_dataset(args.dataset, DEFAULT_CACHE_DIR / safe_slug(args.dataset))
    repo = ProductRepository()
    queries = build_queries(csv_dir, repo, args.sample)
    random.shuffle(queries)
    queries = queries[: args.sample]

    print(f"stress_dataset={csv_dir}")
    print(f"queries={len(queries)} concurrency={args.concurrency}")

    latencies: list[float] = []
    errors: list[str] = []
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_search, query) for query in queries]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception as exc:  # noqa: BLE001 - stress output should preserve the raw failure.
                errors.append(repr(exc))
    elapsed = time.perf_counter() - start

    if not latencies:
        print("No successful searches were recorded.")
        return 1

    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    print(f"elapsed={elapsed:.2f}s throughput={len(latencies) / max(elapsed, 0.001):.1f} qps")
    print(f"latency_ms p50={p50:.2f} p95={p95:.2f} p99={p99:.2f} max={max(latencies):.2f}")
    print(f"errors={len(errors)}")
    if errors:
        print("first_errors=" + " | ".join(errors[:3]))
        return 1
    if p95 > args.p95_ms:
        print(f"p95 latency {p95:.2f}ms exceeded threshold {args.p95_ms:.2f}ms")
        return 2
    return 0


def download_kaggle_dataset(dataset: str, target_dir: Path) -> Path:
    if target_dir.exists() and any(target_dir.rglob("*.csv")):
        return target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        import kagglehub  # type: ignore

        downloaded = Path(kagglehub.dataset_download(dataset))
        return downloaded
    except Exception:
        pass

    try:
        subprocess.run(
            ["kaggle", "datasets", "download", "-d", dataset, "-p", str(target_dir), "--unzip"],
            check=True,
            text=True,
        )
        if any(target_dir.rglob("*.csv")):
            return target_dir
    except Exception:
        print(
            "Kaggle download was unavailable. Install kagglehub or configure Kaggle API credentials, "
            "or pass --csv-dir /path/to/downloaded/csvs. Falling back to local product-derived queries.",
            file=sys.stderr,
        )
    return target_dir


def build_queries(csv_dir: Path, repo: ProductRepository, sample: int) -> list[str]:
    queries = query_terms_from_csvs(csv_dir)
    for product in repo.all():
        queries.append(product.title)
        queries.append(f"{product.category} {product.sub_category}")
        if product.highlights:
            queries.append(f"{product.sub_category} {product.highlights[0]}")

    clean = [query.strip() for query in queries if len(query.strip()) >= 2]
    if not clean:
        clean = ["推荐手机", "油皮 防晒", "快充 充电器", "咖啡", "三亚 防晒"]
    while len(clean) < sample:
        clean.extend(clean)
    return clean


def query_terms_from_csvs(csv_dir: Path) -> list[str]:
    queries: list[str] = []
    for path in csv_dir.rglob("*.csv"):
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames or []
                useful_columns = [
                    column
                    for column in columns
                    if any(term in column.lower() for term in ["product", "category", "name", "title", "description"])
                ]
                for index, row in enumerate(reader):
                    if index >= 400:
                        break
                    values = [row.get(column, "") for column in useful_columns[:4]]
                    query = " ".join(value for value in values if value)
                    if query:
                        queries.append(query[:120])
        except UnicodeDecodeError:
            continue
    return queries


def run_search(query: str) -> float:
    repo = ProductRepository()
    start = time.perf_counter()
    repo.search(query, SearchConstraints(), limit=5)
    return (time.perf_counter() - start) * 1000


def percentile(values: list[float], percent: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[percent - 1]


def safe_slug(slug: str) -> str:
    return slug.replace("/", "__").replace(" ", "_")


if __name__ == "__main__":
    raise SystemExit(main())
