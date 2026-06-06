from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin_router, products, router
from app.config import (
    CORS_ALLOW_ORIGINS,
    STATIC_DIR,
    TEXT_EMBEDDING_PRECOMPUTE_LIMIT,
    TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP,
)
from app.observability import observability


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP and products.semantic_store.is_configured:
        limit = TEXT_EMBEDDING_PRECOMPUTE_LIMIT or None
        try:
            written = await asyncio.to_thread(products.semantic_store.precompute_missing, limit=limit)
            observability.increment("text_embedding_precompute_startup_runs")
            observability.increment("text_embedding_precompute_vectors_written", written)
            logger.info("precomputed %s text embedding vectors on startup", written)
        except Exception:
            observability.increment("text_embedding_precompute_startup_failures")
            logger.exception("text embedding startup precompute failed")
    yield


app = FastAPI(title="CartCompass AI Agent", version="0.1.0", lifespan=lifespan)

# A wildcard origin cannot be combined with credentialed requests per the CORS
# spec, so only enable credentials once an explicit whitelist is configured.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=CORS_ALLOW_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
