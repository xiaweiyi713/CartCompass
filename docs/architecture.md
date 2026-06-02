# ShopGuide 架构说明

## 目标

ShopGuide 是一个原生 iOS 多模态电商智能导购 Agent。它把用户的自然语言、商品知识库、结构化约束过滤、语义向量检索、流式回复、商品卡片、对比、购物车与下单串成闭环，并支持像豆包那样在**普通聊天中自然插入购物**。核心原则：所有推荐商品、价格、SKU 必须来自本地商品库，模型不得编造。

## 端到端链路（对话）

1. iOS `ChatView` 发送用户消息到 `POST /api/chat/stream`（SSE 长连接）。
2. `AgentOrchestrator` 先做确定性快捷分支（偏好记忆/查看/清除、精确寒暄）。
3. **对话规划器（LLM-first + 规则兜底）**：`_route_mode` 调用 `LLMGateway.plan_turn`，让模型结合**最近对话历史**判断本轮 `intent`、`shopping_intent_level` 和（闲聊类）自然回复，只输出受 Pydantic 校验的 JSON。
   - 规划器**未配置 / 超时 / JSON 非法**，或命中**高置信显式意图**（加购、结算、明确"推荐+类目/预算"等）时，跳过规划器、直接走 `ConversationModeRouter` 确定性规则，保证离线可用与低延迟。
4. 路由结果：
   - 闲聊 / 商品知识 / 天气 / 澄清 → 直接用规划器的自然回复（经轻量风险词检查，见可信策略）；`shopping_intent_level=0` 时**绝不弹商品卡**。
   - 推荐 / 对比 / 购物车 / 商品追问 / 售后 / 预算套装 / 旅行清单 / 反选反馈 → 分发到对应的确定性工具（规划器意图 OR 规则命中均可触发）。
5. `ConstraintParser` 抽取预算/类目/子类目/包含偏好/反选/品牌排除；配置 LLM 时只补齐确定性解析未覆盖的字段。
6. `ProductRepository` 先用 SQL 按类目/价格/排除项预筛候选，再融合 **BM25 + 真语义向量（Doubao 多模态 embedding）+ hashing 兜底 + 可信度信号**重排；热门检索走 TTL/LRU 缓存。
7. 回复用 Ark/Doubao **流式**生成；命中推荐缓存时复用安全文案；失败/不可信时回退确定性本地文案。
8. `GroundingGuard` 对**流式片段**和**最终文本**做 grounding 校验，拦截价格/优惠/库存等未落库内容；闲聊回复也过一道轻量风险词检查。
9. SSE 返回 `token`、`products`、`compare`、`cart`、`plan`、`weather`、`profile`、`fallback`、`done` 事件，`done` 带 `trace_id`。
10. 每轮结束把 user/assistant 文本写入会话 `transcript`，供下一轮规划器与跨轮指代（"第二款""刚才那个"）。

## 端到端链路（拍照找货 / 多模态）

`POST /api/image_search`：上传图 → `doubao-embedding-vision` 把图片 embed 到**图文共享向量空间** → 与商品文本向量做**跨模态余弦相似**（复用启动时预计算并缓存的商品向量），再与 VLM 图像理解、轻量视觉特征、文本意图融合排序。未配置 embedding 时优雅回退到 CLIP/颜色轮廓兜底。iOS 端支持相机拍摄与相册选图，并声明了相机/相册/麦克风/语音识别权限。

## 关键模块

- `client-ios/ShopGuide/Views/Chat/ChatView.swift`：全屏聊天、悬浮玻璃顶/底栏、侧栏入口、流式光标。
- `client-ios/ShopGuide/Views/Chat/SidebarView.swift` + `Models/StoredConversation.swift`：侧栏（偏好/对话模型/隐私 + 明暗切换）与 **SwiftData 持久化历史对话**（沙盒内 SQLite）。
- `client-ios/ShopGuide/Theme.swift`：黑白(ChatGPT 风)设计系统 + Liquid Glass 修饰器 + 明暗模式。
- `server/app/agent/orchestrator.py`：Agent 调度、规划器路由(`_route_mode`)、上下文、各意图工具分发、流式 + 分段 grounding。
- `server/app/llm/gateway.py`：`plan_turn`（对话规划器）、`generate_grounded_answer`/流式、`parse_constraints`、`travel_need_plan`，全部结构化校验 + 兜底。
- `server/app/agent/session_store.py`：会话状态 + 对话历史(transcript)，带 TTL/LRU 回收。
- `server/app/agent/conversation_mode.py`：确定性规则路由（规划器兜底层）。
- `server/app/rag/product_repository.py`：SQL 预筛 + BM25 + 语义向量 + hashing 兜底 + 可信度重排 + 推荐理由/来源事实。
- `server/app/rag/semantic_text.py`：文本/图像 embedding 客户端与缓存（支持 `doubao-embedding-vision` 多模态 `/embeddings/multimodal`）。
- `server/app/rag/image_search.py` + `image_understanding.py`：跨模态语义图搜 + 可选 VLM 图像理解。
- `server/app/rag/retrieval_cache.py` / `agent/recommendation_cache.py`：检索/推荐 TTL+LRU 缓存。
- `server/app/observability.py`：计数器、p50/p95/p99 延迟、缓存命中率、首 Token 延迟、Trace；`/admin/metrics` 看板。

## 数据现状

- 商品库为已提交的种子库（`server/storage/seed.sqlite3`），首启自动落地；当前约 312 条，覆盖美妆护肤、数码电子、服饰运动、食品饮料四大类目，多数带公开来源链接与用户评论。
- 启动时对全部商品文本做一次 embedding 预计算并缓存进 SQLite（`text_embedding_vectors`），之后检索/图搜走真语义向量。

## 可信策略（防幻觉）

- 推荐列表只返回数据库商品；价格来自 `base_price` 或所选 SKU `price`；商品卡片只由后端工具产出，模型不生成。
- `GroundingGuard` 拦截优惠/库存/销量/未落库价格等；流式分段校验，危险片段不发出并回退确定性文案。
- 规划器的闲聊回复同样过一道轻量风险词检查（不得出现优惠/满减/库存等承诺）。
- 规划器只决策"调哪个工具/怎么聊"，不产出商品事实；拿不准时用 `clarify` 礼貌追问。
- 找不到符合条件的商品时给放宽条件提示，不编造兜底商品。
- 未配置 LLM 或输出不可信时，整条链路回退到确定性规则 + 模板文案，离线仍可演示。
