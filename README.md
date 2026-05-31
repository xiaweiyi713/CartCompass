# ShopGuide iOS 多模态智能导购

这是基于赛题 PDF 和 `project_plan_ios.md` 搭建的端到端原生 iOS 多模态智能导购应用：

- FastAPI 后端：商品入库、SQLite 事实库、本地向量检索、SSE 流式回复、购物车接口。
- SwiftUI iOS 客户端：聊天页、流式回复、商品卡片、商品详情、购物车入口。
- 数据：当前 SQLite 商品库共 312 条商品，包含赛题示例数据、真实公开页面采集数据和真实 SKU 规格图片溯源。

## 启动后端

后端需要 Python 3.10 或更高版本；推荐 Python 3.11。macOS 系统自带的旧版 `python3` 可能无法解析项目里的现代类型注解。

```bash
cd server
python3 --version
python3 -m pip install -r requirements.txt
python scripts/ingest_products.py
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 启动 iOS

```bash
cd client-ios
xcodegen generate
open ShopGuide.xcodeproj
```

在 iOS Simulator 里运行 `ShopGuide`，确保后端保持在 `http://127.0.0.1:8000`。

## 已验证链路

- `GET /api/health` 返回当前商品数量。
- `POST /api/chat/stream` 支持 SSE token + products + cart 事件。
- `POST /api/chat/stream` 支持 `compare` 事件，可渲染结构化商品对比。
- `POST /api/image_search` 支持图片上传和图文融合找货，会融合可选 VLM 图像理解、可选 CLIP 语义图像、轻量视觉特征和文本检索排名。
- 图片找货可选接入 OpenAI-compatible VLM：配置 `VISION_UNDERSTANDING_MODEL` 后会先把上传图理解成品类、子类目、关键词和外观属性；未配置时不中断服务，继续使用 CLIP/轻量视觉 fallback。
- 本地 VLM 演示配置已采用已开通的方舟视觉模型 `doubao-seed-2-0-lite-260428`；补上 `VISION_UNDERSTANDING_API_KEY` 或 `ARK_API_KEY` 后可用 `server/scripts/probe_vision_understanding.py` 跑真实图片理解调参。
- 图片找货支持可选 CLIP 语义图像检索层：安装 `sentence-transformers` 并配置 `SHOPGUIDE_CLIP_MODEL` 后会自动启用；未安装时会在不中断服务的情况下降级到轻量视觉特征。
- 文本检索已升级为结构化过滤 + BM25 + 可选真实 text embedding + hashing fallback + 可信度 reranker，推荐理由会展示混合检索分量，并带 TTL/LRU 热门查询缓存。
- 支持平替/升级款/换品牌：例如推荐后说 `第一款太贵了，有没有平替`、`换个品牌`、`有没有更高端一点的`。
- 支持用户反馈闭环：`喜欢这款`、`不喜欢`、`太贵`、`换品牌` 会记录到用户画像的 `last_feedback`，并即时触发重排或替代品检索。
- 支持售后/退换货政策问答：例如 `第一款售后和保修怎么说`，系统会基于 Demo 边界、商品来源和类目风险回答，不编造平台承诺。
- 支持订单后推荐：模拟下单后返回配件、补充购买或复购候选，iOS 会自动展示为商品卡片。
- 商品详情页展示数据来源、推荐依据、SKU 规格和真实规格图片来源。
- 推荐结果包含 `match_score`、`match_reasons`、`risk_flags`，iOS 卡片和详情页会展示匹配分、命中依据和注意点。
- iOS 已接入 AppIcon 资源，图标用对话气泡、搜索镜和商品包表达智能导购核心功能。
- iPhone 17 Pro Max 的不同颜色 SKU 图片通过 `server/scripts/crawl_sku_images.py` 从 Apple 官方公开页面采集，本地只缓存真实图片，不生成伪造图。
- 可选配置 `ARK_API_KEY` 启用豆包/Ark 文案生成；返回前会经过 Grounding Guard，风险回复自动降级到本地确定性文案。
- 反选示例：`推荐适合油皮的防晒，200元以内，不要含酒精`。
- 主动澄清示例：先问 `推荐手机`，Agent 会追问拍照/续航/性能/性价比和预算；再答 `拍照优先，预算4000` 会继承手机上下文继续推荐。
- 长期偏好示例：说 `记住我以后护肤品不要含酒精，我是油皮，预算200`，之后再说 `推荐防晒` 会自动带上油皮、200 元预算和酒精排除条件；也可说 `查看我的偏好` 或 `清除我的偏好`。
- 预算套装示例：`我1000元预算，下周去三亚，帮我配一套防晒和出行用品` 会返回结构化 Shopping Plan，包含必需项、可升级项、总价、剩余预算和每件商品的选择理由。
- 替代品示例：推荐后说 `第一款太贵了，有没有平替` 会保持核心类目/偏好并降低价格；说 `换个品牌` 会避开当前品牌找同类替代。
- 售后示例：推荐后问 `第一款能退换货吗`，Agent 会说明 Demo 不产生真实支付/物流/平台售后承诺，并提示核对公开来源页面。
- 商品追问示例：推荐后继续问 `第一款差评主要说什么`、`这款适合敏感肌吗，有没有酒精`、`第一款不同规格怎么选`，Agent 会基于商品详情、FAQ、评论、SKU 和来源字段回答。
- 购物车示例：先推荐手机，再说 `把第一款加到购物车，数量改成2`。
- 购物车页支持增减数量、左滑删除、清空购物车和默认地址模拟下单。
- iOS 模拟器已成功展示流式回复、商品卡片图片、卡片/详情页加购、对比卡片和图片找货。

## 测试

```bash
PYTHONPATH=server python3 -m pytest server/tests -q
PYTHONPATH=server python3 server/evaluation/run_eval.py
```

当前后端测试覆盖健康检查、SSE 推荐、主动澄清、反选排除、上下文切换、旅行场景推荐、预算套装方案、长期偏好记忆、替代品/平替、用户反馈闭环、售后政策问答、订单后推荐、混合检索评分、可解释推荐评分、商品级追问问答、SKU 购物车、真实 SKU 图片溯源、模拟下单和图片搜索。

自动化评测会运行 `server/evaluation/cases/` 下的意图识别、约束抽取、反选过滤、多轮上下文、长期偏好、预算套装、反馈闭环、售后政策、订单后推荐、购物车、图片找货和来源 grounding 用例，并生成：

- `server/evaluation/output/evaluation_report.json`
- `server/evaluation/output/evaluation_report.html`

## 可观测性 Dashboard

后端运行后打开：

```text
http://127.0.0.1:8000/admin/metrics
```

Dashboard 展示商品覆盖率、公开来源占比、评论/SKU/规格图覆盖、Agent 调用计数、Grounding Guard 拦截、购物车成功率、图片检索延迟、SSE 首 token 延迟、p50/p95/p99 延迟和最近 Trace。单轮请求的 `done` 事件会带 `trace_id`，可通过 `GET /api/traces/{trace_id}` 查看意图识别、约束解析、候选过滤、检索结果、Grounding Guard 和输出事件。

## 压力测试

```bash
python3 server/scripts/stress_test_retrieval.py --sample 1000 --concurrency 16 --p95-ms 800
```

脚本会优先使用 Kaggle `olistbr/brazilian-ecommerce` 数据集生成查询；如果没有 Kaggle 凭证，也可以传入 `--csv-dir` 使用已下载的 CSV 文件夹。输出包含 QPS、p50/p95/p99/max 延迟和错误数。

## 文档

- `docs/architecture.md`：系统架构与模块说明。
- `docs/api.md`：接口文档。
- `docs/rag_design.md`：RAG、上下文、反选和防幻觉设计。
- `docs/ui_design.md`：UI 和交互设计说明。
- `docs/demo_script.md`：答辩演示脚本。
