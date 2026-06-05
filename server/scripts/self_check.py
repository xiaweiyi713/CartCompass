from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_DIR / "server"
DB_PATH = Path(os.getenv("SHOPGUIDE_DB", SERVER_DIR / "storage" / "shopguide.sqlite3"))
SEED_DB_PATH = SERVER_DIR / "storage" / "seed.sqlite3"


def main() -> int:
    parser = argparse.ArgumentParser(description="ShopGuide local demo self-check")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Running backend URL")
    parser.add_argument("--require-server", action="store_true", help="Fail if /api/health is not reachable")
    args = parser.parse_args()

    failures: list[str] = []
    warnings: list[str] = []

    _check_python(failures)
    _check_imports(failures, warnings)
    _check_database(failures)
    _check_health(args.url.rstrip("/"), failures if args.require_server else warnings)

    print("\nShopGuide self-check")
    print("====================")
    if warnings:
        print("\nWarnings:")
        for item in warnings:
            print(f"- {item}")
    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("OK: local environment is ready for the demo path.")
    return 0


def _check_python(failures: list[str]) -> None:
    version = sys.version_info
    print(f"Python: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 10):
        failures.append("Python 3.10+ is required. Recreate server/.venv with python3.11.")


def _check_imports(failures: list[str], warnings: list[str]) -> None:
    required = ["fastapi", "uvicorn", "pydantic"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        failures.append(f"Missing required packages: {', '.join(missing)}. Run pip install -r server/requirements.txt.")

    if os.getenv("VECTOR_STORE_BACKEND", "").strip().lower() == "chroma":
        if importlib.util.find_spec("chromadb") is None:
            failures.append("VECTOR_STORE_BACKEND=chroma but chromadb is missing. Run pip install -r server/requirements-optional.txt.")
        else:
            print("Chroma package: installed")


def _check_database(failures: list[str]) -> None:
    db_path = DB_PATH if DB_PATH.exists() else SEED_DB_PATH
    if not db_path.exists():
        failures.append("No runtime DB or seed DB found under server/storage.")
        return
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    except sqlite3.Error as exc:
        failures.append(f"Cannot read product database {db_path}: {exc}")
        return
    finally:
        if conn is not None:
            conn.close()
    print(f"Database: {db_path} ({product_count} products)")
    if product_count < 100:
        failures.append(f"Product database looks incomplete: only {product_count} products.")


def _check_health(base_url: str, issues: list[str]) -> None:
    url = f"{base_url}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        issues.append(f"Backend health check is not reachable at {url}: {exc}")
        return
    vector = payload.get("vector_store", {})
    if not vector:
        issues.append("Backend is reachable but /api/health has no vector_store field. Restart uvicorn to load current code.")
        return
    print(f"Backend: ok, products={payload.get('product_count')}, vector_store={vector.get('active_backend')}")


if __name__ == "__main__":
    raise SystemExit(main())
