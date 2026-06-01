# ShopGuide Server

FastAPI backend for the challenge MVP. It imports the provided ecommerce dataset,
stores structured product facts in SQLite, builds a small local vector index, and
serves grounded SSE chat responses with product cards.

## Setup

Requires Python 3.10+; Python 3.11 is recommended. Older macOS system Python
builds may fail to evaluate the modern type annotations used by the server.

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/ingest_products.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The app intentionally does not commit the shared challenge API key. Copy
`.env.example` to `.env` or export `ARK_API_KEY` later when enabling live LLM
generation.

## Docker

From the repository root, Docker Compose pins the runtime to Python 3.11 and
starts the same FastAPI service:

```bash
docker compose up --build shopguide-api
```

The service mounts `./server/storage` and `./server/static`, so the local SQLite
database and cached product images remain outside the container. Export
`ARK_API_KEY`, `VISION_UNDERSTANDING_API_KEY`, or other model variables before
running Compose when you want live Doubao/Ark responses.

## Optional LLM Gateway

The RAG retrieval path works without an LLM key. The server exposes an LLM
Gateway so the Agent can use Doubao/Ark, DeepSeek, or any OpenAI-compatible
model without changing the shopping tools. Returned text is checked by the
Grounding Guard before it is streamed to the client. If the LLM times out or
mentions unsupported prices, coupons, discounts, stock, or other ungrounded
claims, the server falls back to the deterministic local response.

Default Ark/Doubao mode can be configured through `.env`:

```bash
cp .env.example .env
# edit .env and set ARK_API_KEY
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Runtime Bring-Your-Own-Key mode is in-memory by default:

```bash
curl http://127.0.0.1:8000/api/llm/status
curl -X POST http://127.0.0.1:8000/api/llm/config \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"ios-demo","provider":"deepseek","model":"deepseek-chat","api_key":"YOUR_KEY"}'
curl -X POST http://127.0.0.1:8000/api/llm/test \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"ios-demo"}'
```

The API key is never returned by status endpoints; only a masked hint is shown.
The iOS "Model Brain" sheet uses the same gateway and does not call model
vendors directly.

## Optional CLIP Image Semantics

Image search works out of the box with lightweight visual features. To enable
CLIP-compatible semantic image reranking, install the optional dependency and
set a model name:

```bash
pip install sentence-transformers
export SHOPGUIDE_CLIP_MODEL=clip-ViT-B-32
```

If the dependency or model is unavailable, the server starts normally and image
search falls back to the lightweight visual pipeline.

## Optional Vision Image Understanding

Image search can also call an OpenAI-compatible vision model before ranking.
The model output is constrained to shopping-safe JSON: category, sub-category,
keywords, attributes, and confidence. Those terms are fused with text retrieval
and visual similarity; product cards, prices, and URLs still come only from the
local product database.

```bash
export VISION_UNDERSTANDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export VISION_UNDERSTANDING_MODEL=doubao-seed-2-0-lite-260428
export VISION_UNDERSTANDING_API_KEY=YOUR_KEY
```

The default model is `doubao-seed-2-0-lite-260428`; with `ARK_API_KEY` present
the service enables it automatically. If no key is set or the call fails, image
search keeps using CLIP when available and then the lightweight visual fallback.

For endpoint tuning, run a local product image through the probe script:

```bash
PYTHONPATH=server python3 server/scripts/probe_vision_understanding.py \
  --image server/static/product_images/p_anker_001_fc881685.jpg \
  --detail low \
  --max-image-side 768 \
  --max-tokens 240
```

The current Doubao demo default is `detail=low`, longest side `768`, and
`max_tokens=240`: it recognized the Anker charger as `数码电子/充电设备` and
kept the original product as Top 1 in fused ranking. Use `--detail high` only
for images where text, labels, or small product details matter.
For `doubao-seed-2-0-lite-260428`, keep `VISION_UNDERSTANDING_JSON_MODE=false`
because the model returns a 400 error for `response_format=json_object`.

## Optional Text Embedding Retrieval

Text retrieval works out of the box with BM25, structured filters, and local
hashing vectors. To enable real semantic text embeddings, configure an
OpenAI-compatible embeddings endpoint:

```bash
export TEXT_EMBEDDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export TEXT_EMBEDDING_MODEL=YOUR_TEXT_EMBEDDING_MODEL_OR_ARK_ENDPOINT
export TEXT_EMBEDDING_API_KEY=YOUR_KEY
PYTHONPATH=server python3 server/scripts/build_text_embeddings.py
```

Request-time product vector writes are disabled by default, so a search will use
existing `text_embedding_vectors` and fall back to local hashing for missing
rows. For small demos you can precompute on server startup:

```bash
export TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP=true
export TEXT_EMBEDDING_PRECOMPUTE_LIMIT=50
```

Set `TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT=true` only when you explicitly want
search requests to fill missing product vectors.

When configured, traces show `text_embedding(...)` in `retrieval_stack`; when it
is unavailable, the server automatically falls back to `hashing_vector`.

## Useful Endpoints

- `GET /api/health`
- `GET /api/llm/status`
- `POST /api/llm/config`
- `POST /api/llm/test`
- `DELETE /api/llm/config/{session_id}`
- `GET /api/products`
- `GET /api/products/{product_id}/alternatives?mode=cheaper`
- `GET /api/products/{product_id}/after_sale`
- `POST /api/chat/stream`
- `POST /api/chat/stream` with `对比前两款` returns a structured `compare` event.
- `POST /api/chat/stream` with broad requests like `推荐手机` returns a clarification question before product cards.
- `POST /api/chat/stream` with feedback like `第一款太贵了，有没有平替` returns cheaper alternatives.
- `POST /api/chat/stream` with after-sale questions like `第一款售后和保修怎么说` returns grounded Demo policy boundaries.
- `GET /api/products/{product_id}`
- `POST /api/cart/add`
- `POST /api/cart/update`
- `DELETE /api/cart/{session_id}`
- `GET /api/cart/{session_id}`
- `POST /api/cart/checkout`
- `POST /api/image_search` accepts multipart `file` and returns visually similar products.

Checkout responses include `post_purchase_recommendations`, which the iOS app
uses for accessory, replenishment, or repurchase suggestions after simulated
checkout.

## Tests

```bash
cd ..
PYTHONPATH=server python3 -m pytest server/tests -q
```
