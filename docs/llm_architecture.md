# LLM Architecture

CartCompass uses a **controlled agent** architecture: an LLM conversation planner
decides *what to do* each turn, but every product fact comes from deterministic
tools over the local catalog, so grounding is preserved.

```text
iOS App
  -> FastAPI AgentOrchestrator
  -> LLM conversation planner (intent + shopping level + chat reply)   [LLM]
  -> deterministic tools: retrieval / ranking / cart / compare / qa    [no LLM]
  -> grounded answer generation + GroundingGuard                       [LLM, guarded]
```

## Conversation planner (the brain)

`LLMGateway.plan_turn` (schema `ConversationPlan`) classifies each turn **in the
context of recent dialogue history** and returns validated JSON:

- `intent`: smalltalk / product_knowledge / weather / recommend / compare / cart /
  product_qa / after_sale / budget_plan / travel_bundle / feedback / clarify.
- `shopping_intent_level` (0–4): 0 = pure chat (never show product cards), 1–2 =
  vague interest (offer help, no cards), 3 = explicit recommendation, 4 = transaction.
- `reply`: a natural Chinese reply for conversational intents only (smalltalk /
  knowledge / weather / clarify). Empty for catalog-backed intents, whose text is
  produced by the grounded answer pipeline.

This is what lets the agent behave like Doubao: it chats naturally, does **not**
hard-sell on emotional/small talk, and pivots into shopping (or resolves
"the second one" / "the one you just mentioned") using the transcript.

### Planner-first, rules as fallback, fast-path for explicit intents

`AgentOrchestrator._route_mode`:

1. If the LLM is **not configured / times out / returns invalid JSON** → fall back
   to the deterministic `ConversationModeRouter`. Offline and evaluation stay stable.
2. If a **high-confidence explicit intent** is detected by cheap rules (cart /
   checkout, explicit compare / product-qa / feedback / after-sale, or a clear
   "recommend + category/price" request) → skip the planner call entirely and route
   by rules. This keeps first-token latency low (one LLM call instead of two).
3. Otherwise (ambiguous turns, where natural chat↔shop disambiguation matters) →
   call the planner.

Conversation history is kept in `SessionState.transcript` (recent turns,
TTL/LRU-bounded) and passed to the planner each turn.

## Product selection stays deterministic

```text
ConstraintParser (+ optional LLM constraint fill) / profile merge
  -> ProductRepository SQL prefilter (category / price / exclusions)
  -> BM25 + semantic vector (Doubao multimodal embedding) + hashing fallback + trust
  -> business ranker
  -> GroundingGuard
  -> programmatic `products` SSE event
```

The model never emits product cards, image URLs, SKU prices, cart mutations, or
checkout state. Those come from backend tools over SQLite.

## Multimodal embedding (text retrieval + cross-modal image search)

`server/app/rag/semantic_text.py` calls `doubao-embedding-vision` via the
`/embeddings/multimodal` endpoint (2048-dim, shared image-text space):

- **Text retrieval**: product `search_text` and the query are embedded; cosine
  similarity feeds the hybrid ranker. Product vectors are precomputed at startup
  and cached in `text_embedding_vectors` (SQLite).
- **Cross-modal photo search** (`image_search.py`): the uploaded image is embedded
  and compared against products' cached text vectors in the same space, so a photo
  of a phone surfaces phones, a sunscreen photo surfaces sunscreens, etc. This is
  the dominant signal, fused with VLM image understanding, light visual features,
  and text intent. Falls back gracefully when embeddings are not configured.

## Grounded answers and guards

Before answer generation the orchestrator builds a `GroundedAnswerPacket` (user
query, merged constraints, selected products, evidence/match-reasons/risk-flags,
and a forbidden-facts list). `generate_grounded_answer` sends only this packet.

- **Streaming** uses segment-level guarded streaming: chunks are buffered to
  punctuation / a short length, checked for unsupported prices and risky claims
  (coupons, stock, discounts), and only safe segments are emitted; otherwise the
  turn switches to the deterministic local fallback.
- **Chat replies** from the planner (`smalltalk` / `product_knowledge` / `clarify`)
  also pass a lightweight risk-word check, so casual replies cannot invent
  promotions, stock, or prices either.

## Structured-output guardrails

Task outputs use Pydantic schemas in `server/app/llm/schemas.py`; provider JSON is
parsed by `server/app/llm/validators/json_validator.py` with a repair retry.
Invalid JSON / schema mismatch returns `None`, so malformed model output never
reaches business logic — the orchestrator falls back to deterministic behavior.

## Model routing

`server/app/llm/router.py` capability registry and per-task temperatures:

- Conversation planning / intent / constraints: temperature `0.0` (deterministic routing)
- Travel planning: `0.1`
- Grounded answers: `0.2`

## Tests & evaluation

- Unit tests (`server/tests`) run with the key blanked, exercising the deterministic
  fallback path (no regressions when offline).
- `server/evaluation/run_eval.py` adds capability-gated cases: chat-pivots-to-shopping
  (works in both modes) and cross-modal image search (`requires: embedding`, skipped
  offline). Skipped cases are excluded from the pass rate.
