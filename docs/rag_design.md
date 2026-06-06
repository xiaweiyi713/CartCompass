# RAG 与 Agent 设计

## 商品知识构建

商品数据被写入 SQLite 的 `products` 表，核心字段包括标题、品牌、类目、价格、主图、SKU、RAG 知识和搜索文本。`product_vectors` 保存本地 Hashing 向量，用于离线兜底检索；`text_embedding_vectors` 可选保存真实文本 embedding，用于语义向量检索。

为了让 Chunking 策略可审计，启动时还会自动维护 `product_chunks` 表：

- `identity` chunk：标题、品牌、类目、子类目，适合精确识别商品身份。
- `detail` chunk：`marketing_description`，用于卖点、规格、材质、公开来源等详情证据。
- `faq` chunk：官方 FAQ 的问答拼接，适合“适不适合”“怎么选”“来源可靠吗”等追问。
- `review` chunk：用户评论和评分，适合差评、口碑、风险提示。

`ProductQAService` 在商品级追问中会读取 `ProductRepository.get_chunks(product_id)`，优先返回命中的 chunk 片段；如果没有直接命中，再回退到原始 `rag_json` 和商品 evidence。这样答辩时可以展示从“商品原始资料 → chunk 表 → grounded answer”的路径。

搜索文本由以下内容拼接：

- 商品标题、品牌、类目、子类目。
- `marketing_description`。
- 官方 FAQ。
- 用户评论。
- 爬虫清洗得到的属性标签。

## 检索流程

1. `ConstraintParser` 解析结构化约束。
2. `ProductRepository._candidate_rows` 先在 SQLite 层按类目、价格和排除商品 ID 缩小候选集，避免 cache miss 时总是把全表商品和向量都搬进内存。
3. `ProductRepository._matches_constraints` 对候选行继续做硬过滤：
   - 子类目
   - 包含偏好
   - 排除词、排除品牌
4. 对剩余商品做向量相似检索：优先使用 `TEXT_EMBEDDING_*` 配置的真实 embedding；未配置时可选走本地 Chroma 向量库；如果 Chroma 未启用或不可用，自动回退到 SQLite 中的本地 Hashing 向量。
5. 使用结构化命中进行加权，例如品牌、子类目、包含偏好。
6. 返回前 N 个商品，并生成 grounded reason。

## 可解释推荐评分

推荐和搜索返回的每个商品都会附带一份轻量决策报告：

- `match_score`：结合向量相似度、类目命中、子类目/标签命中、预算满足、包含偏好、排除过滤、公开来源和评论数量计算的 0-100 分。
- `match_reasons`：说明该商品为什么被推荐，例如“命中类目”“符合预算”“包含偏好”“有公开来源”“提供多个 SKU”。
- `risk_flags`：提醒用户做二次核对，例如“价格接近预算上限”“缺少公开页面链接”“暂无用户评论”“评分偏低”。

iOS 商品卡展示匹配分和首条命中依据，详情页展示完整“推荐决策”区块。这样推荐结果不只是列表，而是可审计、可解释、可答辩的导购决策。

## 多轮上下文

会话状态保存：

- `constraints`：已确认约束。
- `pending_constraints`：待澄清约束。
- `pending_clarification`：上一轮追问。
- `last_product_ids`：上一轮商品列表，用于“第一款”“对比前两款”等指代。

模糊请求如“推荐手机”会先追问拍照、续航、游戏性能、性价比和预算；用户回复“9999”“游戏”“随便”时会承接上一轮手机上下文。

当新消息明显切换话题，例如“推荐去三亚要带的东西”或“油皮防晒”，系统会重置旧手机上下文，避免把旧约束错误套到新场景。

## 商品级追问问答

推荐完成后，`last_product_ids` 会让 Agent 理解“第一款”“这款”“它”等指代。用户不需要重新描述商品，可以直接追问：

- `第一款差评主要说什么`
- `这款适合敏感肌吗，有没有酒精`
- `第一款不同规格怎么选`
- `第一款来源可靠吗`

这类问题不会重新跑普通推荐，而是读取目标商品的 `marketing_description`、`official_faq`、`user_reviews`、SKU 和公开来源字段，生成商品级 grounded 回答。评论问题会优先归纳 3 星及以下反馈；成分/属性问题会返回命中的 FAQ、详情和评论片段；规格问题会汇总可选属性、价格区间和真实规格图数量；来源问题会展示公开来源和可核验片段。

## 反选排除

支持表达：

- `不要小米`
- `不含酒精`
- `除了耐克`
- `排除苹果`

解析器只排除负向前缀后的实体。例如“苹果手机不要小米”会保留苹果意图，只排除小米。

## 多模态检索

当前实现为三层图文融合检索：

1. 可选 VLM 图像理解：调用 OpenAI-compatible vision model，把上传图转换为 `category`、`sub_category`、`keywords`、`attributes` 和 `confidence`。
2. 可选 CLIP 语义图像重排：本地安装 `sentence-transformers` 且配置 `SHOPGUIDE_CLIP_MODEL` 后启用。
3. 默认轻量视觉 fallback：不依赖模型，保证演示和测试环境稳定可用。

轻量视觉侧特征包括：

- 颜色直方图
- 平均颜色
- 宽高比
- 8x8 空间网格
- 感知哈希

如果用户上传图片前在输入框里补充文本，例如“油皮防晒”“黑色手机”“通勤背包”，后端会把图片理解词、视觉相似度和文本检索排名融合，并把融合依据写入 `reason`、`match_score` 和 `match_reasons`。这比纯图片找货更接近真实电商场景：用户经常会同时给出“看起来像这张图，但要某个预算/肤质/品类”的约束。

启用 VLM 图像理解时，`OptionalVisionImageUnderstanding` 会把上传图压缩为 JPEG data URI 并发送到 `/chat/completions`。模型只能输出受限 JSON，不允许生成商品 ID、价格、优惠、库存、销量或平台政策。解析后的品类/关键词只用于召回和重排；最终商品卡片、图片 URL、SKU 和价格仍来自本地 SQLite 商品库。

当前方舟演示配置使用官方图片理解示例同类接口：

```bash
VISION_UNDERSTANDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VISION_UNDERSTANDING_MODEL=doubao-seed-2-0-lite-260428
VISION_UNDERSTANDING_IMAGE_DETAIL=low
VISION_UNDERSTANDING_MAX_IMAGE_SIDE=768
VISION_UNDERSTANDING_MAX_TOKENS=240
VISION_UNDERSTANDING_JSON_MODE=false
```

真实调参通过 `server/scripts/probe_vision_understanding.py` 完成。当前实测 `detail=low`、最长边 768、`max_tokens=240` 能把 Anker 充电器图识别为 `数码电子/充电设备`，并让融合排序 Top 1 命中原商品；512px 版本识别仍稳定但该次延迟更高，因此默认保留 768px。若商品标签、接口文字、小规格图识别不足，再升到 `detail=high`。`doubao-seed-2-0-lite-260428` 当前不支持 Chat Completions 的 `response_format=json_object`，因此默认关闭 JSON mode，依靠提示词输出 JSON 后在本地解析和归一化。

图片找货同时提供可选 CLIP 语义层：`OptionalSemanticImageEncoder` 会尝试加载 `sentence-transformers` 的 CLIP 兼容模型，默认模型名由 `SHOPGUIDE_CLIP_MODEL` 控制。如果模型可用，融合公式会优先使用语义图像相似度，并按可用信号动态归一：

```text
fused_score = semantic_image_score
            + lightweight_visual_score
            + text_score
            + vlm_understanding_score
```

如果 VLM 或 CLIP 未配置，系统不会阻塞启动，而是自动 fallback 到下一层，并在 `match_reasons`、`risk_flags` 和 Trace 中说明“VLM图像理解未配置”“语义图像模型未启用”。这样答辩时可以明确表达“三阶段视觉检索：VLM 图像理解 + CLIP 语义重排 + 轻量特征 fallback”。

## 混合检索与 Reranker

文本检索已从单一 hashing vector 升级为可配置双通道：

```text
结构化过滤 -> BM25 -> Chroma/text embedding(可选) -> hashing fallback -> 可信度 reranker
```

如果评审要求看到标准向量数据库，可启用本地 Chroma 后端：

```bash
pip install -r server/requirements-optional.txt
export VECTOR_STORE_BACKEND=chroma
export CHROMA_PATH=server/storage/chroma
export CHROMA_COLLECTION=cartcompass_products
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Chroma 是可选增强，不是单点依赖。启动时 `ChromaVectorStore` 会优先读取当前 `TEXT_EMBEDDING_PROVIDER/MODEL` 对应的 `text_embedding_vectors`，同步到独立的 `cartcompass_products_text_*` collection；检索时用同一 embedding 模型编码用户 query，再由 Chroma 返回语义相似度。结构化过滤、BM25、可信度 reranker 和商品事实仍由 SQLite 控制，避免向量库返回非商品库事实。

如果没有配置 embedding、没有预计算真实向量，或 `chromadb` 未安装，系统会自动降级到 hashing collection / `SQLiteHashVectorStore`，本地演示不受影响。Trace 的 `retrieval_stack` 会显示 `Chroma text_embedding(...)`、`Chroma vector DB` 或 `hashing_vector`；商品 `match_reasons` 会显示 `Chroma语义向量`、`Chroma向量库`、`语义向量` 或 `本地向量`。

启用真实语义检索时，设置：

```bash
export TEXT_EMBEDDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export TEXT_EMBEDDING_MODEL=你的文本向量模型或 Ark endpoint
export TEXT_EMBEDDING_API_KEY=你的 Key
PYTHONPATH=server python3 server/scripts/build_text_embeddings.py
```

默认情况下，检索请求只读取已存在的商品 embedding，不会在一次用户请求里为大量商品逐个补向量；缺失商品会自动走 hashing fallback。可用 `server/scripts/build_text_embeddings.py` 离线预计算，或设置 `TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP=true` 让服务启动时补齐缺失向量；`TEXT_EMBEDDING_PRECOMPUTE_LIMIT` 可限制启动期写入数量。只有明确设置 `TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT=true` 时，才允许请求期写入缺失商品向量。

运行时 Trace 会把 `retrieval_stack` 标成 `Chroma text_embedding(...)`、`text_embedding(...)`、`hybrid_text_embedding(...)` 或 `hashing_vector`，商品 `match_reasons` 也会区分“Chroma语义向量”“语义向量”和“本地向量”。这样答辩时可以展示生产级路径和离线 fallback：有 embedding 服务时语义召回更强，无 key 或模型不可用时仍保证本地演示稳定。

热门检索还有一层 TTL/LRU 缓存：相同 query、结构化约束、limit 和向量后端身份会命中 `RetrievalCache`，直接返回深拷贝商品卡片，避免重复候选预筛、BM25 和向量重排。`/api/traces/{trace_id}` 的 `retrieval.cache_hit` 会标记命中状态，`/api/metrics` 和 `/admin/metrics` 会展示 `retrieval_cache_hit_rate`。可复现性能报告可以运行：

```bash
PYTHONPATH=server python3 server/scripts/measure_performance.py --repeat 2
```

脚本会输出 `server/evaluation/output/performance_report.json`，包含首 Token p50/p95、总耗时 p50/p95、检索缓存命中率和每轮 Trace。

结构化过滤先处理类目、子类目、预算、排除词、排除品牌和排除商品 ID；BM25 负责关键词精确匹配；hashing vector 负责语义近似；可信度 reranker 会把公开来源、评论和 SKU 完整度计入排序。每个商品的 `match_reasons` 会追加类似 `混合检索：BM25 100 / 向量 42 / 结构化 20 / 可信度 65` 的解释，便于 Trace 和前端展示。

## 替代品与反馈闭环

`ProductRepository.alternatives` 支持三种替代品模式：

- `cheaper`：平替，优先降价并保留同类目/核心偏好。
- `premium`：升级款，保留类目并提高价格区间。
- `brand_excluded`：换品牌，排除当前品牌或用户指定品牌。

Agent 会识别 `第一款太贵了`、`有没有平替`、`更高端一点`、`换个品牌`、`喜欢这款`、`不喜欢` 等反馈。反馈会写入用户画像 `last_feedback`，并即时触发替代品检索或保存正向偏好。这让系统从一次性推荐变成有反馈闭环的导购。

## 压力测试

`server/scripts/stress_test_retrieval.py` 用于验证检索层在并发查询下不会轻易崩溃。脚本优先使用 Kaggle 数据集 `olistbr/brazilian-ecommerce` 生成压力查询；如果本机没有 Kaggle 凭证或网络不可用，也可以通过 `--csv-dir` 指向已下载的 CSV 目录，或者回退到当前商品库生成查询。

示例：

```bash
python3 server/scripts/stress_test_retrieval.py --sample 1000 --concurrency 16 --p95-ms 800
```

输出包括总耗时、QPS、p50/p95/p99/max 延迟和错误数。当前轻量回归测试还包含 120 次并发检索，确保多线程 SQLite 读取和检索排序稳定。

## 自动化评测与 Trace

`server/evaluation/run_eval.py` 提供一套可重复运行的导购能力评测。用例按场景拆到 `server/evaluation/cases/`，覆盖：

- 意图识别与主动澄清：模糊手机请求必须先追问拍照、续航、预算等偏好。
- 约束抽取：油皮、防晒、预算、酒精排除、Anker 快充等条件必须进入检索。
- 反选过滤：例如“苹果手机不要小米”不能返回小米品牌。
- 多轮上下文：上一轮的商品候选可被“第一款差评”追问引用。
- 长期偏好：用户保存肤质、预算、排除成分后，后续模糊推荐自动继承偏好。
- 预算套装：把“三亚旅行 1000 元预算”拆成防晒、衣物、充电、补能等类目并返回结构化方案。
- 反馈闭环：太贵/平替/换品牌等反馈会触发替代品检索。
- 售后政策：售后/退换货/保修问题必须说明 Demo 边界，不编造平台承诺。
- 订单后推荐：模拟下单后需要返回配件、补充购买或复购候选。
- 购物车闭环：加购、SKU、结算流程可自动验证。
- 图片找货：上传真实商品图后 Top-K 需要命中目标商品。
- Grounding：来源追问必须回到公开来源和本地商品库证据。

运行后会生成 `server/evaluation/output/evaluation_report.json` 和 `server/evaluation/output/evaluation_report.html`。报告给出 case pass rate、Top-3 命中率、反选过滤准确率、主动澄清准确率、购物车成功率、图片 Top-K 命中率、预算套装成功率、订单后推荐成功率和 p95 延迟。

运行期可观测性由 `app.observability` 提供。每次聊天会创建 `trace_id`，`done` 事件返回该 ID；`/api/traces/{trace_id}` 可查看本轮 Agent 的意图、约束解析、候选过滤、检索结果、Grounding Guard 和 SSE 输出。`/admin/metrics` 提供 HTML Dashboard，汇总商品覆盖、公开来源覆盖、评论/SKU/规格图覆盖、缓存命中率、调用计数和延迟分布。

## 长期偏好与预算套装

`UserProfileService` 会把用户画像持久化到 `server/storage/user_profiles.json`。当前画像字段包括类目预算、偏好特征、排除品牌、排除成分、肤质、旅行场景和最近反馈。普通推荐会在约束解析后调用 `apply_to_constraints`，把长期偏好合并进本轮检索条件，例如“推荐防晒”会自动补上“油皮、200 元以内、不含酒精”。

`BudgetPlanner` 用启发式约束优化生成套装方案：先按场景拆分必需类目，再给每个类目分配预算，从结构化过滤 + 向量检索候选中选最高匹配商品；如果总价超预算，会优先移除可选项；如果有剩余预算，则生成升级项。输出的 `plan` 事件包含 `items`、`upgrade_options`、`total_price`、`remaining_budget` 和 `notes`，iOS 端渲染为 Shopping Plan 卡片。

## 售后政策与订单后推荐

`AfterSalePolicyService` 用确定性规则回答售后/退换货/保修问题。系统会明确说明本项目是导购 Demo，不产生真实支付、物流、库存或平台售后承诺；真实退换货政策应以商品来源平台和商家页面为准。不同类目会补充不同核对重点，例如数码类关注激活状态、序列号和保修主体，美妆类关注拆封和过敏举证，食品类关注保质期和破损漏液。

`PostPurchaseRecommender` 会在 `CartService.checkout` 生成订单后，根据已购商品类目检索配件、补充购买或复购候选，并写入 `OrderState.post_purchase_recommendations`。iOS 端收到订单后会自动把这些候选渲染为商品卡片，形成下单后的继续导购链路。

## 防幻觉

如果 Ark/Doubao 生成文本包含未落库的价格、库存、优惠等高风险事实，`GroundingGuard` 会拒绝该回复，系统回退到确定性文案。无论是否配置 LLM，`products` 事件始终来自商品库。
