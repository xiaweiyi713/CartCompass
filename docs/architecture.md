# ShopGuide 架构说明

## 目标

ShopGuide 是一个原生 iOS 多模态电商导购 Agent。它把用户的自然语言需求、商品知识库、结构化约束过滤、向量检索、流式回复、商品卡片和购物车操作串成闭环，重点满足赛题里的“基于 RAG 的智能导购”和“所推荐商品必须来自商品库”的要求。

## 端到端链路

1. iOS `ChatView` 发送用户消息到 `POST /api/chat/stream`。
2. FastAPI `AgentOrchestrator` 判断意图：闲聊、推荐、对比、购物车、旅行清单或图片搜索。
3. `ConstraintParser` 抽取预算、类目、子类目、包含偏好、反选排除、品牌排除；配置 LLM 时只补齐确定性解析未覆盖的字段。
4. `ProductRepository` 先用 SQL 按类目、价格和排除商品做候选预筛，再组合 BM25、可选真实 text embedding、hashing fallback 和可信度信号重排；热门检索通过 TTL/LRU 缓存复用结果。
5. 生成回复先尝试 Ark/Doubao 流式输出，缓存命中时直接复用安全文案，失败或不可信时回退到确定性本地文案。
6. `GroundingGuard` 对流式片段和最终文本做 grounding 校验，拦截价格、优惠、库存等未落库的幻觉内容。
7. 后端通过 SSE 返回 `token`、`products`、`compare`、`cart`、`plan`、`weather`、`done` 事件。
8. SwiftUI 将流式文本、商品卡片、对比卡、计划卡、天气卡和购物车状态卡嵌入同一个聊天窗口。

## 关键模块

- `client-ios/ShopGuide/Views/Chat/ChatView.swift`：聊天主界面、快捷提示、图片上传入口、购物车徽标。
- `client-ios/ShopGuide/Views/Product/ProductDetailView.swift`：商品详情、SKU 规格选择、真实规格图切换、可信依据展示。
- `client-ios/ShopGuide/Views/Cart/CartView.swift`：购物车、数量修改、删除、清空、模拟下单。
- `server/app/agent/orchestrator.py`：Agent 调度、上下文、澄清、对比、购物车工具。
- `server/app/agent/session_store.py`：多轮会话状态，带 TTL/LRU 回收，避免长时间演示或压测时无界增长。
- `server/app/agent/constraint_parser.py`：约束解析、反选排除、多轮承接。
- `server/app/rag/product_repository.py`：结构化过滤、BM25、可选 text embedding、hashing fallback、推荐理由和来源事实。
- `server/app/rag/retrieval_cache.py`：检索结果 TTL/LRU 缓存，返回深拷贝商品卡片避免状态污染。
- `server/app/agent/recommendation_cache.py`：推荐回复缓存，减少重复请求的 LLM 延迟。
- `server/app/rag/image_search.py`：多模态图片找货融合排序，组合 VLM 图像理解、CLIP 语义图像和轻量视觉特征。
- `server/app/rag/image_understanding.py`：可选 OpenAI-compatible VLM 适配器，把上传图转为受限购物意图 JSON。
- `server/scripts/crawl_sku_images.py`：真实 SKU 规格图片采集和溯源。

## 数据现状

- 当前商品总数：312。
- 类目分布：服饰运动 110、数码电子 80、美妆护肤 67、食品饮料 55。
- 公开来源商品：217 条。
- 已有真实 SKU 规格图：9 张，来自 Apple 官方公开图片 CDN，并保留 `image_source_url`。

## 可信策略

- 推荐列表只返回数据库里的商品。
- 价格来自 `base_price` 或用户选择的 SKU `price`。
- 详情页展示商品来源、推荐依据和规格图片来源。
- 找不到符合条件的商品时返回放宽条件提示，不编造兜底商品。
- 未配置 LLM 或 LLM 输出不可信时，系统使用确定性模板回复。
