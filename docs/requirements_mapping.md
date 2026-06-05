# 赛题要求映射

本文按《基于 RAG 的多模态电商智能导购 AI Agent》课题说明逐项映射实现、演示话术和验证命令，便于答辩时快速对照。

## 最小闭环

| 课题要求 | 当前实现 | 证明材料 |
|---|---|---|
| 原生 iOS/Android App | SwiftUI iOS App，非 H5 | `client-ios/ShopGuide.xcodeproj`，`client-ios/ShopGuide/Views/Chat/ChatView.swift` |
| 对话窗口，支持文字 | 聊天输入框 + 历史消息 + 快捷 prompt | `ChatView.swift`，`ChatViewModel.swift` |
| AI 流式回复 | 后端 SSE `token/products/cart/order/done`，iOS 逐 token 渲染 | `server/app/api/routes.py`，`ChatStreamService.swift` |
| 可点击商品卡 | `ProductCarousel` 点击进入商品详情，详情页可选 SKU 加购 | `ProductCarousel.swift`，`ProductDetailView.swift` |
| RAG 基本链路 | 结构化过滤 + BM25 + 向量 + 可信度重排 + GroundingGuard | `ProductRepository.search`，`docs/rag_design.md` |
| 不编造虚假信息 | 商品事实来自 SQLite；Guard 拦截优惠券、虚假价格、库存等 | `server/tests/test_api.py` grounding/guard 测试 |

## 数据工程与特征治理

| 要求 | 当前实现 |
|---|---|
| 50-100 条脱敏电商数据 | 当前 seed 库 321 条商品，覆盖数码、美妆、服饰、食品 |
| 商品名、类目、价格、详情、主图 URL | `products` 表 + `Product` schema 全量暴露 |
| 非结构化数据向量化 | `text_embedding_vectors` 保存真实商品文本 embedding；`VECTOR_STORE_BACKEND=chroma` 时优先同步真实 embedding 到 Chroma；无 key/无向量时回退 `product_vectors` hashing |
| Chunking 策略 | `product_chunks` 表：`identity/detail/faq/review`；商品追问会读取 chunk 证据 |
| 价格/库存一致性 | `base_price`、SKU 价格来自库；`stock_status/inventory_count` 为本地 mock 库存；加购、改数量、下单前都会按当前库存快照校验 |

## Agent 与 RAG 增强

| 场景 | 演示话术 | 实现 |
|---|---|---|
| 单轮模糊推荐 | `推荐一款适合油皮的洗面奶` | 约束解析 + 检索 |
| 条件筛选 | `200 元以下的蓝牙耳机有哪些？` | 类目、预算、子类目过滤 |
| 主动澄清 | `推荐手机` | 信息不足时追问拍照/续航/游戏/预算 |
| 多轮细化 | `推荐手机` -> `游戏，预算9999` | `SessionState.pending_constraints` |
| 反选/排除 | `推荐防晒，不含酒精，不要日系` | `exclude_terms/exclude_brands` |
| 对比决策 | `对比前两款` | `compare` SSE + `CompareCard` |
| 商品追问 | `第一款来源可靠吗` / `第一款差评主要说什么` | 商品级 RAG + chunks + FAQ/评论 |
| 场景组合 | `下周去三亚度假要带的东西` | 旅行场景规则 + 天气 + 跨类目配额 |

## 加分项

| 加分项 | 深度实现 |
|---|---|
| 购物车与下单 | 对话式加购、删除、改数量、SKU 独立行；Agent 引导地址确认、订单汇总、`order` SSE、模拟订单号、清空购物车 |
| 多模态交互 | ASR 语音输入、TTS 朗读、语音连续对话、相机/相册图片找货、VLM + CLIP/轻量视觉 fallback |
| 多轮上下文与反选 | 指代解析、上下文切换、反馈平替/升级/换品牌、长期偏好 |
| 性能优化 | 显式购物 fast-path，商品卡先出；检索缓存；首 token 和 p95 在 `/admin/metrics` 可观测 |
| 工程质量 | FastAPI + SwiftUI 分层，pytest/E2E，Trace，恢复提示，Docker Compose |

## 建议 Demo 顺序

1. `推荐手机` -> 主动澄清。
2. `游戏，预算9999` -> 流式文本 + 商品卡。
3. `对比前两款` -> 结构化对比。
4. `把第一款加到购物车` -> 购物车状态。
5. `我要下单` -> 地址确认；输入 `北京市朝阳区 Demo 路 1 号`；输入 `确认下单` -> 订单卡。
6. 上传 `server/static/product_images/p_anker_001_fc881685.jpg` -> 图片找货。
7. 打开 `/admin/metrics` -> 展示 Trace、延迟、缓存、Guard。

## 验证命令

```bash
PYTHONPATH=server server/.venv/bin/python -m pytest server/tests
PYTHONPATH=server server/.venv/bin/python server/evaluation/run_e2e_smoke.py \
  --cases server/evaluation/cases/e2e_agent_smoke_cases.json \
  --case-timeout 45 \
  --output-dir server/evaluation/output/e2e_smoke_final
```

可选 Chroma：

```bash
source server/.venv/bin/activate
pip install -r server/requirements-optional.txt
VECTOR_STORE_BACKEND=chroma PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
