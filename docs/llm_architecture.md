# LLM Architecture

ShopGuide uses a controlled Agent architecture:

```text
iOS App
  -> FastAPI AgentOrchestrator
  -> deterministic state / retrieval / ranking / tools / guard
  -> task-scoped LLMGateway
```

The LLM is not the product recommender. It is used only for bounded language tasks:

- `travel_need_plan`: convert free-form travel needs into structured shopping slots.
- `generate_grounded_answer`: turn a backend-selected product evidence packet into natural Chinese.
- `parse_constraints`: when a session LLM is configured, validated JSON output fills fields the deterministic parser missed; deterministic parsing remains the source of truth for already detected category, budget, exclusions, and offline fallback.
- `classify_intent`: available as a validated JSON task for future router experiments, while the production router stays deterministic for latency and stability.

Product selection remains deterministic:

```text
ConstraintParser / optional LLM constraint fill / profile merge
  -> ProductRepository structured filters
  -> BM25 + optional text embedding + hashing fallback hybrid retrieval
  -> business ranker / trust signals
  -> GroundingGuard
  -> programmatic products SSE event
```

The model never generates product cards, image URLs, SKU prices, cart mutations, or checkout state. Those are produced by backend tools from the local product database.

## Grounded Answer Packet

Before answer generation, the orchestrator constructs a `GroundedAnswerPacket`:

- user query
- merged constraints
- selected backend products
- evidence, match reasons, risk flags
- forbidden facts, such as coupons, stock, sales rank, or unsupported parameters

`LLMGateway.generate_grounded_answer` sends only this packet to the provider. Non-streaming responses are checked by `GroundingGuard` before they are returned.

For live streaming, the orchestrator uses segment-level guarded streaming: chunks are buffered until punctuation or a short length threshold, checked for unsupported prices and risky claims, then emitted to iOS. If a segment contains ungrounded terms such as coupons, stock, discounts, or unsupported prices, the unsafe segment is never sent and the response switches to the deterministic local fallback.

## Structured Output Guardrails

Task outputs use Pydantic schemas in `server/app/llm/schemas.py`.

JSON text from providers is parsed by `server/app/llm/validators/json_validator.py`. Invalid JSON or schema mismatches return `None`, allowing the orchestrator to fall back to deterministic logic instead of letting malformed model output affect business behavior.

## Model Routing

`server/app/llm/router.py` keeps a small capability registry. Current defaults:

- Intent / constraints: temperature `0.0`
- Travel planning: temperature `0.1`
- Grounded answers: temperature `0.2`

This keeps recommendation behavior stable while still allowing DeepSeek or another OpenAI-compatible model to improve language understanding and explanations.
