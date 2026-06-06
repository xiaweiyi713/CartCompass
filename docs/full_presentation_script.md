# 智购罗盘 CartCompass 极详细项目介绍稿件

这份稿件是“素材库”，不是要求全部讲完。你可以按视频时长和答辩重点裁剪。建议正式视频只取 20%-30%，答辩问答时再展开细节。

## 0. 一句话版本

智购罗盘 CartCompass 是一个基于 RAG 的多模态电商导购 AI Agent：前端是原生 iOS SwiftUI，后端是 FastAPI；用户可以用文字、语音或图片表达购物需求，系统通过 SQLite 商品事实库、Chroma 向量库、BM25、结构化约束过滤和 GroundingGuard，实现可解释、可追溯、低幻觉的商品推荐、对比、追问、加购和下单闭环。

## 1. 30 秒开场稿

大家好，我的项目叫智购罗盘 CartCompass，是一个基于 RAG 的多模态电商智能导购 Agent。它不是一个普通的商品搜索页面，也不是一个纯聊天机器人，而是把“像豆包一样自然聊天”和“像真实导购一样精准选品”结合起来。

用户可以直接说“推荐手机”“油皮防晒不要酒精”“我 1000 元预算去三亚帮我配一套”，也可以拍照找相似商品，或者用语音输入。系统会先理解意图和约束，再从本地商品库检索真实商品，返回商品卡、对比、追问回答、购物车和订单卡。所有商品价格、SKU、库存和来源都来自本地数据库；LLM 只负责理解和表达，不能编造商品事实。

## 2. 项目定位

这个项目解决的是电商导购里的三个典型问题。

第一，用户的需求往往不是结构化的。真实用户不会一开始就填筛选器，他可能只说“推荐手机”“我去三亚带什么”“这个太贵了有没有平替”。所以系统需要自然语言理解、多轮上下文和主动澄清。

第二，电商推荐不能幻觉。普通大模型很容易编造优惠、库存、销量、价格和售后承诺，但电商场景里这些都是高风险信息。所以我的设计原则是：商品事实必须来自工具和数据库，模型只能基于已给事实生成自然语言，最后还要经过 Guard 校验。

第三，移动端体验很重要。这个项目不是纯 Web Demo，而是原生 iOS 应用，支持流式聊天、商品卡、详情页、购物车、语音识别、TTS、拍照和相册上传。用户体验接近一个真正可用的移动购物助手。

## 3. 技术栈总览

### 客户端

客户端是原生 iOS：

- SwiftUI：实现聊天主界面、商品卡、详情页、购物车、侧栏、Profile 页面。
- Observation / `@Observable`：管理聊天状态、流式 token、购物车、偏好和模型配置。
- SwiftData：保存本地历史会话。
- URLSession + AsyncSequence：消费后端 SSE 流。
- PhotosUI / UIKit：支持相册选择和拍照上传。
- Speech / AVFoundation：实现语音识别和 TTS 朗读。
- SafariServices：用于沙箱 checkout 页面或外部链接展示。

### 后端

后端是 Python FastAPI：

- FastAPI：提供 REST API、SSE 流式聊天、图片搜索、购物车、订单、Profile、metrics。
- Uvicorn：本地服务运行。
- Pydantic：定义请求响应模型、LLM 输出结构、商品卡、订单卡。
- SQLite：本地事实库，保存商品、SKU、库存、chunks、向量、用户画像等。
- Chroma：可选标准向量数据库，演示时通过 `VECTOR_STORE_BACKEND=chroma` 启用。
- BM25 + HashingVectorizer：本地离线可用的文本检索与兜底向量。
- OpenAI-compatible LLM Gateway：支持 Ark/Doubao、DeepSeek、Anthropic 或其它兼容模型。
- Doubao / Ark：用于对话模型、文本/多模态 embedding、可选 VLM 图像理解。
- pytest：覆盖后端能力、RAG、SSE、购物车、Profile、Guard 和评测路径。

### 数据和评测

- 商品库：321 条演示商品，覆盖美妆护肤、数码电子、服饰运动、食品饮料。
- 商品事实：标题、品牌、类目、价格、SKU、库存、图片、来源 URL、FAQ、评论、RAG 文本。
- chunk 表：`identity`、`detail`、`faq`、`review`，用于商品追问和可解释回答。
- 评测脚本：`server/evaluation/run_eval.py` 和 `run_e2e_smoke.py`。
- 可观测性：`/admin/metrics`、`/api/metrics`、`/api/traces/{trace_id}`。

## 4. 总体架构讲稿

智购罗盘 CartCompass 的整体架构可以分成三层。

第一层是 iOS 客户端。用户在 iOS App 里输入文字、语音或图片。文字和语音最终都会进入同一个聊天接口；图片会进入图片搜索接口。App 通过 SSE 接收 token、products、compare、cart、order、plan、weather、profile、fallback、done 等结构化事件，然后渲染成聊天气泡、商品卡、对比卡、购物车卡和订单卡。

第二层是 AgentOrchestrator。它是后端的调度中心，负责判断本轮应该做什么：是闲聊、导购、主动澄清、商品追问、对比、加购、下单、售后问答、长期偏好、旅行套装，还是拍照找货。它不会直接相信大模型的自由输出，而是把任务拆给确定性工具。

第三层是 RAG 和工具层。商品推荐会进入 ProductRepository，先用 SQL 根据类目、价格、排除条件做硬过滤，再用 BM25 处理关键词匹配，再用 Chroma 或本地向量做语义召回，最后根据结构化命中、预算匹配、公开来源、评论和 SKU 完整度做重排。购物车、下单、售后、Profile 都是独立工具。

最后是 GroundingGuard。所有要返回给用户的商品事实都必须经得起校验。模型如果说了不在商品库里的优惠、库存、价格、销量、包邮或官方承诺，会被拦截并回退到确定性本地文案。

## 5. 端到端对话链路

一次普通导购请求的链路是这样的。

用户在 iOS 输入：

```text
推荐适合油皮的防晒，200元以内，不要含酒精
```

App 向后端 `POST /api/chat/stream` 发起 SSE 请求。后端创建一个 `trace_id`，这样后续可以在 `/api/traces/{trace_id}` 里复盘整条链路。

AgentOrchestrator 首先判断这是不是偏好记忆、查看偏好、清除偏好、天气、购物车确认等特殊分支。如果不是，就进入对话路由。

路由有两层：规则和 LLM planner。对于“推荐防晒”这种高置信显式购物请求，系统会走 fast-path，跳过不必要的 planner LLM 调用，降低首 token 延迟。对于更模糊的聊天，比如“今天好累啊不想动”，planner 会判断它是闲聊还是弱购物意图，避免硬推商品。

确定是导购请求后，ConstraintParser 会抽取：

- category：美妆护肤。
- sub_category：防晒。
- max_price：200。
- include_terms：油皮。
- exclude_terms：酒精。

然后 ProductRepository 检索商品。检索结果不是直接丢给模型，而是先生成商品卡。商品卡包含真实 product_id、title、price、SKU、图片、来源、match_score 和 match_reasons。

为了让体验更快，商品卡会先通过 SSE 返回给 iOS；用户先看到可点击的商品，再看到模型或确定性文案继续流式输出。

如果启用了 LLM，后端会构造一个 grounded answer packet，里面只有三类内容：

- 用户原始消息。
- 解析后的 constraints。
- 后端已经选出的 products fact array。

LLM 只能基于这个 packet 润色自然语言，不能自己搜索、定价、选择 SKU 或承诺库存。生成过程中每个流式片段都会过段级校验，最终完整文本还会再过 GroundingGuard。

## 6. RAG 检索设计

检索栈是这个项目的核心。

### 6.1 SQL 预过滤

第一步是 SQL 预过滤。它处理硬事实条件，比如：

- 类目必须是美妆护肤。
- 价格不能超过 200。
- 排除商品 ID。
- 基础库存或商品有效性。

为什么先做 SQL？因为反选和预算是硬约束，不能让后面的向量相似度把违规商品召回。例如用户说“不要小米”，向量层可能觉得小米手机和苹果手机语义相近，但 SQL/规则层已经把小米排除，后面不能再加回来。

### 6.2 BM25

第二步是 BM25。BM25 适合处理精确关键词，例如：

- Anker。
- iPhone 17 Pro Max。
- 不含酒精。
- 快充。
- 防水。

向量相似度适合语义近似，但品牌、型号、成分排除这类精确词不能只靠向量。所以 BM25 是必要的关键词通道。

### 6.3 向量检索

第三步是向量检索。现在项目支持可插拔向量库：

- `SQLiteHashVectorStore`：默认离线兜底，零依赖。
- `ChromaVectorStore`：标准向量数据库，设置 `VECTOR_STORE_BACKEND=chroma` 启用。
- text embedding：如果配置了 `TEXT_EMBEDDING_*` 并预计算，Chroma 会承载真实文本 embedding。
- hashing fallback：如果没有 embedding，Chroma 也可以承载本地 hashing 向量，保证 demo 稳定。

演示时可以打开 `/admin/metrics` 展示当前向量库，或者 `curl /api/health` 看：

```json
"active_backend": "chroma_text_embedding"
```

这说明 Chroma 不只是代码里存在，而是实际参与了检索。

### 6.4 可信度重排

最终排序不是只看向量相似度，还会加上：

- structured score：类目、子类目、品牌、偏好词命中。
- budget fit：是否符合预算。
- trust score：是否有公开来源、评论、SKU、图片。
- review signal：评论数、评分、风险提示。

这一步让推荐更像电商导购，而不是纯语义搜索。

### 6.5 可解释字段

每个商品会带：

- `match_score`：0-100 分。
- `match_reasons`：为什么推荐，例如命中类目、符合预算、有公开来源、提供多个 SKU。
- `risk_flags`：风险提示，例如价格接近预算上限、暂无评论、缺少公开来源。

iOS 商品卡和详情页都会展示这些字段。

## 7. Chroma 接入讲稿

Chroma 是这个项目的标准向量数据库路径。它通过 `VECTOR_STORE_BACKEND` 开关启用。

启动方式：

```bash
source server/.venv/bin/activate
pip install -r server/requirements-optional.txt
export VECTOR_STORE_BACKEND=chroma
export CHROMA_PATH=server/storage/chroma
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端启动时会构建 ProductRepository，ProductRepository 调用 `build_vector_store`。如果配置是 Chroma，就创建 `ChromaVectorStore`。它会优先检查是否有当前 embedding provider/model 对应的 `text_embedding_vectors`。如果有，就同步到 Chroma collection，active backend 会是 `chroma_text_embedding`。如果没有真实 embedding，就同步本地 hashing vectors，active backend 是 `chroma_hashing_vector`。

这里有两个工程设计点。

第一，Chroma 只负责向量相似度，不负责商品事实。最终商品卡、价格、SKU、库存、来源仍然来自 SQLite。这样可以避免向量库返回“看起来相似但不在商品库”的内容。

第二，Chroma 是可选增强，不是单点故障。如果依赖没安装或初始化失败，系统会自动回退到 SQLite hashing vector，并在 observability 里记录 fallback。这保证了 Demo 稳定性。

验证结果是：Chroma 模式下全量后端测试通过，`138 passed`。

## 8. Prompt 构造与可控 LLM

这个项目没有让 LLM 自由决定商品事实。LLM 的角色被限制在两个地方。

第一是 planner。planner 用来判断本轮用户意图，比如 smalltalk、shopping、clarify、cart、weather。planner 输出必须是结构化 JSON，并通过 Pydantic 校验。如果 planner 超时、未配置或输出非法，就回退到规则路由。

第二是 recommendation wording。模型只负责把后端已经选出的商品事实说得更自然。它收到的 prompt 包含：

- system prompt：明确禁止编造商品、价格、库存、优惠、包邮、销量和官方承诺。
- user message：用户当前消息。
- constraints：后端解析出的约束。
- products：后端选中的商品事实。

模型不会收到全量数据库，也不能自己选择商品 ID。商品卡已经由后端工具选好。

如果模型不可用，项目仍然能用确定性本地模板回答。这样既能利用 LLM 的自然语言能力，又不会把商品事实交给模型自由发挥。

## 9. GroundingGuard 防幻觉设计

电商场景最怕幻觉，因为价格、库存、优惠和售后政策都可能影响用户决策。

GroundingGuard 做了几件事。

第一，它维护风险词列表，例如：

- 优惠券。
- 满减。
- 限时折扣。
- 官方补贴。
- 包邮。
- 现货。
- 库存充足。
- 销量第一。
- 全网最低。

如果生成文本里出现这些没有落库支持的词，会被拦截。

第二，它检查价格。允许出现的价格只包括：

- 当前商品 base_price。
- 当前商品 SKU price。
- 用户约束里的预算值。

如果模型生成了一个不在这些集合里的价格，比如“只要 99 元”，而商品库没有这个价格，就会被拦截。

第三，它支持流式分段校验。SSE 最危险的地方是，一旦危险 token 发给用户就收不回来了。所以系统在每个 pending segment flush 前都会做安全判断，危险片段不会发出；如果最终文本不安全，则回退到确定性文案。

第四，对普通闲聊也有轻量风险词清洗。比如用户只是说“你好”，模型不能突然说“今天有满减优惠”。

## 10. 多轮上下文

多轮上下文主要存在 SessionStore 里。

每个 session 保存：

- 最近对话 transcript。
- 当前 constraints。
- pending constraints。
- pending clarification。
- last_product_ids。
- pending checkout。
- 旅行或场景状态。

例如：

用户第一轮说：

```text
推荐手机
```

系统追问预算和偏好。用户第二轮说：

```text
游戏，预算9999
```

这时系统会把第二轮补充合并到上一轮手机上下文里，而不是把“游戏，预算9999”当成一个孤立请求。

再比如用户推荐完防晒后说：

```text
第一款差评主要说什么
```

系统会用 `last_product_ids[0]` 找到上一轮第一款商品，进入 ProductQAService，而不是重新推荐。

如果用户明显切换场景，比如从手机切到“三亚旅行”或“油皮防晒”，系统会重置旧上下文，避免把手机预算错误套到防晒或旅行场景。

## 11. 长期偏好记忆

长期偏好和临时上下文不同。

临时上下文只在当前 session 内有效，用于“第一款”“刚才那个”“预算 9999”等跨轮理解。长期偏好保存在后端 user profile 中，用于未来推荐。

支持保存：

- 类目预算，例如护肤品 200 元。
- 肤质，例如油皮、敏感肌。
- 排除成分，例如酒精、香精。
- 排除品牌。
- 偏好特征，例如拍照、续航、低糖、防水。
- 旅行场景。
- 最近反馈。

用户可以说：

```text
记住我以后护肤品不要含酒精，我是油皮，预算200
```

之后只说：

```text
推荐防晒
```

系统会自动带上这些长期偏好。iOS 端可以查看和清除偏好，保证记忆不是黑盒。

## 12. 商品级追问

商品级追问解决的是“推荐之后继续问细节”的问题。

支持的问题包括：

- 第一款差评主要说什么？
- 这款适合敏感肌吗？
- 有没有酒精？
- 第一款不同规格怎么选？
- 来源可靠吗？
- 能退换货吗？

这些问题不会普通检索，而是读取目标商品的 chunks 和 RAG JSON。

chunks 包括：

- identity：标题、品牌、类目、子类目。
- detail：卖点、规格、公开来源。
- faq：官方 FAQ。
- review：用户评论和评分。

这样回答是可追溯的。如果商品库里没有证据，系统会明确说明没有足够依据，而不是用常识编造。

## 13. 购物车和下单

购物车是完整闭环，不只是“推荐商品”。

能力包括：

- 加入购物车。
- 同商品不同 SKU 独立行项目。
- 修改数量。
- 删除商品。
- 清空购物车。
- 创建沙箱 checkout session。
- Agent 引导式下单。
- mock 库存校验。
- 订单后推荐。

Agent 引导式下单流程是：

1. 用户说“我要下单”。
2. Agent 汇总购物车并要求地址。
3. 用户输入地址。
4. Agent 再次确认商品、金额、地址。
5. 用户说“确认下单”。
6. 后端创建订单，返回 order 事件。
7. iOS 渲染订单卡，购物车清空。
8. 返回配件或复购候选。

这个流程强调两点：

第一，订单是结构化工具输出，不是模型生成一段文字假装下单。

第二，Agent 不会绕过用户确认直接下单。

## 14. 多模态拍照找货

图片搜索是多层融合。

第一层是可选 VLM 图像理解。它把图片转成结构化 JSON，包括 category、sub_category、keywords、attributes 和 confidence。这个 JSON 不能包含商品 ID、价格、库存或优惠，只能用于召回和重排。

第二层是多模态 embedding。图片和商品文本进入同一个图文共享向量空间，计算余弦相似度。这样手机图片可以召回手机，防晒图片可以召回防晒，不需要用户输入关键词。

第三层是轻量视觉特征 fallback，包括颜色直方图、平均颜色、宽高比、8x8 空间网格和感知哈希。即使没有 embedding key 或模型不可用，图片搜索也不会完全失效。

第四层是文本融合。如果用户先输入“油皮防晒”再上传图片，系统会同时考虑文字约束和图片相似度。

最终商品卡仍然来自本地数据库，图片理解只影响召回和排序，不直接生成商品事实。

## 15. 语音能力

iOS 端集成了语音输入和语音输出。

语音输入使用 Apple Speech，把用户语音实时转成文本。转写后的文本进入同一个 `/api/chat/stream` 链路，所以语音和打字的后端能力完全一致。

语音输出使用 AVFoundation TTS。用户可以朗读回答，还可以调节语速和音色。这个能力让导购更像移动端真实助手，而不是桌面文本 Demo。

## 16. iOS 前端实现

iOS 前端的重点是“原生”和“流畅”。

### 16.1 ChatView

ChatView 是主界面，包含：

- 消息列表。
- 商品卡。
- 对比卡。
- 购物车卡。
- 订单卡。
- 旅行计划卡。
- 天气卡。
- fallback 提示。
- 顶部模型/模式状态。
- 底部输入栏。
- 侧栏入口。

### 16.2 ChatViewModel

ChatViewModel 管理：

- 输入文本。
- 消息数组。
- 当前 session。
- 用户 profile id。
- 购物车状态。
- 最新订单。
- LLM 配置状态。
- 图片搜索状态。
- 流式 token。
- TTS 输出文本。

流式 token 做了约 40ms 合并刷新，避免每个 token 都触发 SwiftUI 大范围重绘。这对长回复和模拟器尤其重要。

### 16.3 性能优化

之前侧栏打开时有整屏实时 blur，模拟器上比较容易卡顿。现在改成：

- 主聊天层轻微 brightness 和 scale。
- 暗化遮罩代替整屏 blur。
- `LiquidBackdrop` 使用 `drawingGroup` 合成。
- token 节流减少 UI 更新频率。

正式演示推荐真机 Release，因为模拟器对毛玻璃和语音链路会受 Mac 性能影响。

### 16.4 商品详情

商品详情页展示：

- 主图。
- SKU 选择。
- 价格。
- 库存状态。
- 高亮卖点。
- 推荐决策。
- match score。
- match reasons。
- risk flags。
- 评论、FAQ、来源。

这样用户不仅知道“推荐了什么”，还知道“为什么推荐”。

## 17. 可观测性

项目提供了三层可观测性。

第一层是 `/api/health`，用于确认服务是否启动、商品数、LLM 配置、text embedding 配置和当前向量库。

第二层是 `/api/metrics`，返回 JSON，包括：

- product_stats。
- performance_metrics。
- derived_metrics。
- counters。
- latencies。
- recent_traces。
- vector_store。

第三层是 `/admin/metrics`，是 HTML Dashboard，方便答辩展示。它显示：

- 商品总数。
- 来源覆盖率。
- 评论覆盖率。
- SKU 覆盖率。
- 当前向量库。
- 首 token p50/p95。
- LLM 首字延迟。
- 检索延迟。
- 图片搜索延迟。
- 缓存命中率。
- 最近 Trace。

每次聊天的 done 事件都会带 `trace_id`。打开 `/api/traces/{trace_id}` 可以看到：

- 输入。
- conversation mode。
- constraint parser。
- retrieval。
- recommendation results。
- grounding guard。
- done 状态。

这对答辩很重要，因为评委问“为什么返回这个商品”，可以直接用 Trace 解释。

## 18. 性能设计

性能目标是让用户感觉响应快。

主要优化包括：

第一，显式购物 fast-path。对于“推荐防晒”“把第一款加购物车”这种明确请求，跳过 planner LLM 调用，直接走规则和工具。

第二，商品卡先发。检索结果已经是 grounded 的数据库商品，所以可以先把 products 事件发给 iOS，不必等 LLM 文案生成。

第三，确定性前缀先发。例如“以下信息来自本地商品库”，可以立即作为首 token 返回，降低首 token 延迟。

第四，检索缓存。相同 query、constraints、limit 和 vector backend 会命中 RetrievalCache。

第五，推荐文案缓存。相同商品和模型配置下可以复用已通过 Guard 的安全文案。

第六，embedding 不在锁内做。文本 embedding 可能是网络调用，不能持有 SQLite 检索锁等待。

第七，iOS token 节流。前端不按每个 token 重绘，而是合并刷新。

## 19. 工程质量

工程质量体现在几个方面。

第一，目录清晰：

- `client-ios/`：原生 iOS。
- `server/app/agent/`：Agent、路由、对话、购物车、Profile、天气、售后。
- `server/app/rag/`：商品库、向量、图搜、embedding、检索缓存。
- `server/app/api/`：API routes。
- `server/evaluation/`：评测脚本和用例。
- `docs/`：架构、RAG、API、runbook、演示稿。

第二，依赖分层：

- 必需依赖在 `server/requirements.txt`。
- Chroma 在 `server/requirements-optional.txt`，避免默认环境过重。
- 无 LLM key 也可运行。
- 无 Chroma 也可 fallback。

第三，自动化测试：

- 后端全量 pytest。
- Chroma 模式全量 pytest 已验证。
- API、Agent planner、业务场景、observability、购物车、Profile、图片搜索均有测试。

第四，runbook：

- Python 版本检查。
- self-check。
- Chroma 启动。
- iOS 打开方式。
- 演示前检查清单。
- 回归测试命令。

第五，Git 历史已经按主题分批：

- Chroma/RAG/后端评测。
- iOS 性能和购物 UI。
- runbook 和答辩文档。

## 20. 测试和评测

后端测试命令：

```bash
PYTHONPATH=server python -m pytest server/tests -q
```

Chroma 全量测试：

```bash
VECTOR_STORE_BACKEND=chroma PYTHONPATH=server python -m pytest server/tests -q
```

当前验证结果：

```text
138 passed
```

评测命令：

```bash
PYTHONPATH=server python server/evaluation/run_eval.py
PYTHONPATH=server python server/evaluation/run_e2e_smoke.py --output-dir server/evaluation/output/e2e_goal_smoke
```

性能复现：

```bash
PYTHONPATH=server python server/scripts/measure_performance.py --repeat 2
```

评测覆盖：

- 意图识别。
- 主动澄清。
- 约束抽取。
- 反选过滤。
- 多轮上下文。
- 长期偏好。
- 平替/反馈。
- 商品级追问。
- 售后边界。
- 购物车闭环。
- 订单后推荐。
- 多模态图搜。
- Grounding。

## 21. 和题目要求的对应

基础功能方面：

- 支持商品推荐。
- 支持多轮对话。
- 支持商品对比。
- 支持购物车和模拟下单。
- 支持图片输入。
- 支持语音输入和朗读。

工程质量方面：

- 原生 iOS + FastAPI，不是纯 Web。
- 有 RAG 设计、向量库、SQLite 事实库。
- 有 Chroma 标准向量数据库路径。
- 有测试、评测、runbook、Dashboard。
- 有可解释推荐字段和 Trace。

效果可靠性方面：

- GroundingGuard 防幻觉。
- SQL 硬过滤保证反选。
- fallback 保证无 key / 模型失败也能跑。
- fast-path 和缓存保证响应速度。
- iOS 做了流畅性优化。

加分项方面：

- 多模态图搜。
- 语音 ASR/TTS。
- 长期偏好记忆。
- 预算旅行套装。
- 商品级追问。
- 订单后推荐。
- 可观测 metrics。
- Chroma 向量库。

## 22. 关键演示话术

### 22.1 讲 Chroma

> 这里我显式设置了 `VECTOR_STORE_BACKEND=chroma`。后端启动后会把商品向量同步到 Chroma collection。Dashboard 和 health 接口都能看到 active backend，所以它不是代码里写了但没启用。Chroma 负责语义相似度，SQLite 仍负责商品事实，这是为了避免向量库返回无法追溯的内容。

### 22.2 讲 RAG

> 我的 RAG 不是单一向量检索，而是混合检索。SQL 先做硬过滤，保证预算、类目、排除品牌和排除成分不会被违反；BM25 处理精确关键词；Chroma/text embedding 处理语义相似；最后再用来源、评论、SKU 和预算适配做可信度重排。

### 22.3 讲防幻觉

> 商品卡完全由后端工具生成，模型不能生成商品 ID、价格、SKU 或库存。LLM 只收到后端选好的 products fact array 和 constraints，用来润色回答。生成过程中每个流式片段都会做安全检查，最终文本还会再过 GroundingGuard。如果出现未落库价格、优惠、库存或销量承诺，就回退确定性文案。

### 22.4 讲 iOS

> 客户端是原生 SwiftUI，不是 WebView。它通过 SSE 消费后端结构化事件，分别渲染 token、商品卡、对比卡、购物车卡和订单卡。语音识别、TTS、相机和相册都是 iOS 原生能力。

### 22.5 讲工程可靠性

> 我专门做了 self-check、runbook、health、metrics 和测试。明天在另一台机器上，最小路径就是创建 venv、安装依赖、跑 self-check、启动后端、打开 Xcode。Chroma 是可选增强，即使不可用也会 fallback，Demo 不会因为向量库依赖失败而跑不起来。

## 23. 可能被问的问题和回答

### Q1：你为什么不用纯 LLM 直接推荐？

因为电商商品事实必须可信。纯 LLM 可能编造商品、价格、库存和优惠。我的设计是 LLM 负责理解和表达，商品事实由 SQLite、检索工具和购物车工具提供，最后 GroundingGuard 校验。

### Q2：为什么还要 BM25，有向量不够吗？

向量适合语义近似，但品牌、型号、成分、排除词是精确条件。比如“不含酒精”“不要小米”“Anker 100W”，这些需要 BM25 和结构化过滤保证准确。

### Q3：Chroma 在项目里到底做了什么？

Chroma 是向量相似度后端。启动时商品向量会同步到 Chroma collection，检索时 query vector 进入 Chroma 查询相似商品，再和 BM25、结构化分、可信度分融合。`/api/health` 和 `/admin/metrics` 可以看到实际 active backend。

### Q4：如果没有 API key 怎么办？

系统仍然可用。没有 LLM key 时，路由和推荐会走确定性规则和模板；没有 embedding 时走 hashing vector；没有 VLM 时走轻量视觉 fallback。目标是 demo 稳定，而不是所有能力都强依赖外部模型。

### Q5：怎么保证不幻觉？

四层保证：商品卡只由数据库生成；Prompt 只给模型已选商品事实；流式片段发送前校验；最终文本再过 GroundingGuard。风险词和 unsupported price 会直接拦截。

### Q6：为什么是原生 iOS？

题目强调全栈和真实产品体验。原生 iOS 可以展示语音、相机、相册、TTS、流式 UI、购物车和商品详情，而不是只做一个网页壳。移动导购本身也更符合手机使用场景。

### Q7：orchestrator 很长，是不是不好维护？

赛前没有做大重构，是为了控制风险。它虽然长，但职责边界是清楚的：负责意图路由和工具编排；具体能力拆到了 ProductRepository、CartService、UserProfileService、ProductQAService、BudgetPlanner、GroundingGuard、LLMClient 等模块。核心路径已经用文档和注释说明，后续可以按意图 handler 进一步拆分。

### Q8：你怎么测试？

后端有 pytest 覆盖 API、Agent planner、业务场景、购物车、Profile、Guard、observability 等；Chroma 模式也跑过全量测试。评测脚本覆盖意图识别、反选、多轮、图搜、预算套装、订单后推荐和 grounding。

## 24. 一分钟压缩版

如果只能讲一分钟：

> 智购罗盘 CartCompass 是一个原生 iOS + FastAPI 的多模态电商导购 Agent。用户可以打字、说话或拍照表达购物需求，系统通过 Agent 路由判断是闲聊、导购、追问、购物车还是图片搜索。商品推荐走 SQL 预过滤、BM25、Chroma 向量检索和可信度重排，返回可解释商品卡。LLM 只负责理解和润色，商品事实全部来自 SQLite 本地库；生成文本还会经过 GroundingGuard，拦截未落库价格、库存、优惠和售后承诺。项目支持主动澄清、反选过滤、多轮追问、长期偏好、平替、对比、购物车、模拟下单、订单后推荐、语音和拍照找货。工程上有 Chroma 标准向量库、可观测 Dashboard、Trace、self-check、runbook 和自动化测试，Chroma 模式全量测试已通过。

## 25. 三分钟压缩版

如果讲三分钟：

> 我的项目智购罗盘 CartCompass 是一个基于 RAG 的多模态电商导购 Agent。前端是原生 iOS SwiftUI，后端是 FastAPI。它支持文字、语音和图片输入，可以完成推荐、澄清、反选、对比、追问、加购和下单。
>
> 核心架构是：iOS 通过 SSE 连接后端；AgentOrchestrator 负责路由本轮意图；ProductRepository 负责 RAG 检索；CartService、ProfileService、ProductQAService 等负责确定性工具；GroundingGuard 负责防幻觉。
>
> RAG 不是单纯向量搜索。第一步 SQL 按类目、预算和排除条件做硬过滤；第二步 BM25 处理品牌、型号、成分等精确词；第三步 Chroma 或 text embedding 做语义召回；第四步根据结构化命中、预算适配、公开来源、评论和 SKU 完整度做重排。商品会带 match_score、match_reasons 和 risk_flags，所以推荐是可解释的。
>
> LLM 被严格限制。它可以做 planner 判断意图，也可以基于后端选好的 products fact array 润色回答，但不能自己生成商品、价格、库存或优惠。回答流式输出前会做段级校验，完整文本还会过 GroundingGuard。如果出现未落库价格、优惠、库存或官方承诺，就回退确定性文案。
>
> 多模态方面，图片会通过多模态 embedding 进入图文共享向量空间，与商品文本向量匹配；同时融合 VLM 图像理解和轻量视觉特征。iOS 还支持语音识别和 TTS。工程质量方面，项目有 Chroma 向量库、SQLite 种子库、Dashboard、Trace、self-check、runbook、Docker 和 pytest。Chroma 模式全量测试已通过。

## 26. 十分钟详细版提纲

1. 项目定位：多模态电商导购 Agent。
2. 用户痛点：自然语言非结构化、电商事实不能幻觉、移动端体验。
3. 架构：iOS + FastAPI + Agent + RAG + tools + Guard。
4. iOS：SwiftUI、SSE、商品卡、购物车、语音、图片、SwiftData。
5. 后端：FastAPI、Pydantic、SQLite、Chroma、LLM Gateway。
6. RAG：SQL、BM25、Chroma、rerank、可解释字段。
7. LLM：planner 和 grounded wording。
8. GroundingGuard：风险词、价格校验、段级校验、fallback。
9. 多轮：session、last_product_ids、pending constraints。
10. Profile：长期偏好和清除。
11. 购物闭环：加购、SKU、库存、订单。
12. 多模态：图片 embedding、VLM、fallback、语音。
13. 可观测性：health、metrics、trace。
14. 性能：fast-path、商品卡先发、缓存、前端节流。
15. 测试和工程质量：pytest、e2e、runbook、Chroma 全量测试。
16. 总结：基础功能、工程质量、可靠性、加分项。

## 27. 最后总结稿

整体来说，智购罗盘 CartCompass 的重点不是“调用一个大模型回答购物问题”，而是把大模型放进一个可控的电商工程系统里。商品事实来自数据库，检索来自 RAG 和向量库，业务动作来自确定性工具，模型负责自然语言理解和表达，Guard 负责最后的可靠性边界。

这个项目覆盖了题目里的基础导购、多轮对话、购物车、多模态和工程质量要求，也额外做了 Chroma 向量库、语音、拍照找货、长期偏好、预算套装、可解释推荐、Trace 和自动化评测。我的目标是让它不仅能演示，而且能解释、能测试、能观测、能在干净环境里跑起来。
