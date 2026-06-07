<div align="center">

<img src="client-ios/design/app_icon_master_1024.png" width="128" alt="智购罗盘 CartCompass App 图标" />

# 智购罗盘 CartCompass

### 基于 RAG 的多模态电商智能导购 AI Agent

**像豆包一样自然聊天,像资深导购一样精准选品 —— 而且商品事实零幻觉。**

原生 iOS（SwiftUI）· FastAPI 后端 · 可控 Agent · 多模态（文字 / 语音 / 拍照）· 可插拔向量库

![iOS](https://img.shields.io/badge/iOS-17%2B-000000?logo=apple)
![Swift](https://img.shields.io/badge/Swift-5.9-F05138?logo=swift)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)
![Tests](https://img.shields.io/badge/tests-138%20passed-success)
![Eval](https://img.shields.io/badge/能力评测-24%2F24-success)

</div>

---

## 📖 这是什么

**智购罗盘 CartCompass** 是我为「字节 AI 全栈挑战赛 · 基于 RAG 的多模态电商智能导购 AI Agent」从零搭建的端到端作品。它把传统"展示型广告"升级为"交互型导购":用户可以**打字、说话、或拍一张实物照片**,Agent 在一段**正常对话**里无缝地完成模糊需求理解、约束筛选、多轮澄清、商品对比、反选排除、加购下单、售后问答、旅行套装规划等全链路任务。

整个项目我只坚持一条铁律,也是这套架构的灵魂:

> **所有推荐的商品、价格、SKU、库存,只能来自本地商品库工具;大模型负责"怎么说",绝不负责"事实是什么"。**

为此我没有让 LLM 直接吐商品(那样必然幻觉),而是设计了一个 **可控 Agent（controlled agent）**:LLM 只做对话规划与文案生成,所有商品事实由确定性工具从 SQLite 取出,再经过 `GroundingGuard` 逐句校验——任何编造的"满减 / 优惠券 / 库存 / 价格"都会被当场拦截并降级为本地确定性文案。这正面回应了赛题最看重的"严禁 AI 编造不存在的优惠券或功能"。

---

## ✨ 核心亮点

| 亮点 | 一句话说明 |
|---|---|
| 🧠 **可控 Agent（planner-first）** | LLM 规划器决定"做什么",选品/对比/加购/售后全走确定性工具,自然对话与零幻觉兼得 |
| 🛡️ **零幻觉 GroundingGuard** | 商品卡只来自 SQLite;回复经**段级流式校验**,自动拦截编造的促销/库存/价格,失败即降级本地文案 |
| 🖼️ **真·多模态** | 流式语音识别（ASR）+ 可调语速/音色 TTS + **语音连续对话**;拍照用豆包多模态向量做**跨模态语义找货** |
| 🗄️ **可插拔向量层** | 抽象 `VectorStore` 协议,**Chroma / SQLite 双后端**,一行环境变量切换,优雅降级;`/admin/metrics` 实时显示当前后端 |
| ⚡ **首 token < 1s** | 显式购物意图走 fast-path 跳过二次 LLM,确定性前缀先发,**实测首 token ≈ 200ms,商品卡先出** |
| 📊 **生产级可观测** | `/admin/metrics` 实测首 token / p50·p95·p99 / 缓存命中率 / Guard 拦截;每个请求带 `trace_id` 可回放全链路 |
| 🔬 **可复现工程** | 依赖全锁版本、312+9 真实商品种子库随仓提交、克隆即跑、138 单测 + 24/24 能力评测 + GitHub Actions CI |

---

## 🏗️ 系统架构

```text
┌──────────────────── iOS 客户端 (SwiftUI · @Observable · SwiftData) ────────────────────┐
│  全页沉浸式聊天 · 逐 token 流式渲染 · 商品卡/对比卡/购物车/订单卡                          │
│  多模态入口:语音(ASR 流式转写 + TTS 朗读 + 语音连续对话) · 相机/相册拍照找货             │
│  侧栏:偏好画像 · 对话模型(可切换/降级) · 隐私合规 · 历史会话                            │
└───────────────────────────────────────┬────────────────────────────────────────────────┘
                       SSE 长连接：token / products / compare / cart / order / done(+trace_id)
┌───────────────────────────────────────▼────────────────────────────────────────────────┐
│                            FastAPI · AgentOrchestrator（可控 Agent）                      │
│  ① LLM 对话规划器：意图 + 购物强度(0–4) + 闲聊回复            [LLM · 温度 0]              │
│  ② 确定性工具：检索 / 排序 / 对比 / 购物车 CRUD / 追问 / 售后 / 预算套装   [无 LLM]       │
│  ③ grounded 文案生成 + GroundingGuard 段级流式校验            [LLM · 受控]                │
└───────────────────────────────────────┬────────────────────────────────────────────────┘
        混合检索栈：SQL 结构化预过滤 → BM25 → 向量语义(豆包多模态 embedding) → 可信度重排
                                        │                         ▲
                          可插拔向量层 VectorStore                │ 端侧采集预处理
                          ├─ ChromaVectorStore（持久化）          │（图像压缩 / 语音转写）
                          └─ SQLiteHashVectorStore（兜底）        │
                                        │
        SQLite 事实库：products(321) · product_chunks(1976, 4 型) · 向量 · SKU · RAG 知识 · 库存
```

> 详见 [`docs/architecture.md`](docs/architecture.md)、[`docs/llm_architecture.md`](docs/llm_architecture.md)、[`docs/rag_design.md`](docs/rag_design.md)。

---

## 🧩 功能全景（对照赛题基础场景 + 三档加分项）

### 1）对话智能与 RAG 增强
- **单轮模糊推荐**：`推荐一款适合油皮的洗面奶` —— 意图识别 + 属性匹配检索。
- **条件筛选**：`200 元以下的蓝牙耳机有哪些` —— 结构化参数提取 + 范围过滤。
- **主动澄清**：`推荐手机` → Agent 追问拍照/续航/游戏/预算 → `拍照优先,预算4000` 继承上下文继续推荐。
- **多轮上下文记忆**：`再便宜点的呢` / `换个品牌` / `有没有更高端一点的`，渐进收敛需求。
- **反选 / 排除约束**：`推荐防晒,不要含酒精,也不要日系` —— 否定语义解析,回复**确定性复述"已排除酒精相关商品"**。
- **多商品对比决策**：`对比前两款` —— 自动提取关键维度,生成结构化对比卡。
- **商品级追问**：`第一款差评主要说什么` / `这款适合敏感肌吗` / `第一款不同规格怎么选` —— 基于商品分块(FAQ/评论/详情/规格)回答,不重新随机推荐。
- **长期偏好记忆**：`记住我以后护肤品不要含酒精,我是油皮,预算200` → 之后 `推荐防晒` 自动带上画像;可 `查看/清除我的偏好`。

### 2）业务闭环（购物车与下单 · ⭐→⭐⭐⭐）
- **对话式加购**：`把第一款加到购物车,数量改成2`。
- **购物车管理**：增减数量、左滑删除、清空,同商品不同 SKU 独立行项目。
- **下单确认流程**：Agent 引导确认收货地址 → 汇总订单 → `order` 事件返回模拟订单号,**下单前按库存快照校验**。
- **订单后推荐**：模拟下单后自动返回配件 / 补充购买 / 复购候选。

### 3）多模态交互（⭐→⭐⭐⭐）
- **语音输入（ASR）**：`SFSpeechRecognizer` 中文流式识别,**聆听浮层实时转写**(波形动效 + 随说随出)。
- **TTS 语音播报**：`AVSpeechSynthesizer` 朗读导购回复,**语速 0.5–1.5× / 中文音色可调**并本地持久化。
- **语音连续对话**：开启后说完**自动发送并朗读回复**,全程免手动的语音闭环。
- **拍照找货（跨模态）**：相机/相册上传 → 后端用 **豆包 `doubao-embedding-vision` 多模态向量**,在**图文共享空间**做跨模态语义匹配(耳机图召回耳机、防晒图召回防晒),再融合 VLM 图像理解、轻量视觉特征与文本意图重排。

### 4）数据工程与防幻觉
- **非结构化向量化**：商品详情 / 文案 / 评价 → 真实文本 embedding,进 `text_embedding_vectors` / Chroma。
- **Chunking 策略**：`product_chunks` 表按 `identity / detail / faq / review` 四种粒度切分(1976 条),商品追问按 chunk 取证。
- **数据一致性**：价格 / SKU 价来自库;`stock_status / inventory_count` 本地库存,加购、改数量、下单前都按当前快照校验。
- **防幻觉守卫**：`GroundingGuard` 对商品答案做价格越界与风险词(优惠券/满减/库存/全网最低)拦截,并对闲聊/知识/澄清回复做轻量风险词清洗。

### 5）工程质量与性能优化（⭐→⭐⭐⭐）
- **热门查询缓存**：检索结果 + 推荐文案 TTL/LRU 缓存,重复问题延迟显著下降(`/admin/metrics` 可见命中率上升)。
- **首屏极速响应**：显式购物意图 fast-path 跳过二次 LLM,**确定性前缀先发、商品卡先出**,实测首 token ≈ 200ms。
- **端侧体验打磨**：流式逐字、骨架屏占位、轻触觉反馈、深/浅色模式、玻璃质感 UI;聊天 token 40ms 节流减少列表重绘。

---

## 🛠️ 技术栈与实现

| 层次 | 选型 | 关键实现 |
|---|---|---|
| **iOS 客户端** | SwiftUI · `@Observable` · NavigationStack · SwiftData | 全页流式聊天、SSE 解析、`Speech`/`AVFoundation` 多模态采集、`@AppStorage` 偏好持久化、Liquid Glass 设计系统 |
| **后端框架** | FastAPI · Uvicorn · Pydantic v2 | SSE 流式 API、异步编排、结构化输出校验、CORS 白名单可配置 |
| **Agent 编排** | 自研 `AgentOrchestrator` | 规划器 + 确定性工具 + 受控文案生成;意图规则、约束解析、对话模式路由、会话记忆 |
| **RAG 检索** | 结构化过滤 + BM25 + 语义向量 + 可信度重排 | `ProductRepository.search` 混合检索栈;商品/查询向量 + chunk 取证 |
| **向量库** | **Chroma**（持久化）/ **SQLite**（兜底） | `VectorStore` 协议抽象,`VECTOR_STORE_BACKEND` 一键切换,失败优雅降级 |
| **Embedding** | 豆包 `doubao-embedding-vision`（多模态） | 文本检索与拍照跨模态找货**共享同一图文向量空间**;启动预热,检索期不重复调用 |
| **大模型** | 豆包 `Doubao-Seed-2.0-lite`（Ark OpenAI 兼容） | 规划/约束温度 0、文案温度 0.2;`LLMGateway` 可插拔,支持按会话切换提供商并校验回退 |
| **多模态视觉** | VLM 图像理解 + 轻量视觉特征 | 上传图先理解品类/子类目/关键词/外观属性,未配置 key 自动降级 |
| **数据治理** | SQLite + 自研采集管线 | 静态/动态爬虫 → 清洗 → 校验 → curate → 导出;Anker/Soundcore/Apple 真实公开页面采集并溯源 |
| **可观测性** | 自研 observability + Trace | 计数器、p50/p95/p99、首 token、缓存命中率、Guard 拦截、全链路 Trace、`/admin/metrics` Dashboard |
| **工程化** | pytest · GitHub Actions · Docker Compose | 138 单测 + E2E 冒烟 + 能力评测;CI 离线确定性跑测;容器一键起 |

**规模**：后端 Python ≈ 16,300 行 · iOS Swift ≈ 6,100 行 · 文档 17 篇 · 演示商品 321 件。

---

## 🎯 赛题完成度对照

> 完整逐条映射见 [`docs/requirements_mapping.md`](docs/requirements_mapping.md);3 分钟答辩讲解见 [`docs/defense_walkthrough.md`](docs/defense_walkthrough.md)。

**最小闭环（全部达成）**：原生 iOS App ✅ · 对话窗口文字输入 ✅ · AI 流式回复 ✅ · 可点击商品卡 ✅ · 向量库 + RAG 基本链路 ✅ · SSE 流式 API ✅ · 理解模糊需求/库内检索/合理推荐理由/不编造 ✅。

**加分项（四类均有深度实现）**：

| 加分方向 | 实现档位 |
|---|---|
| 业务闭环（购物车/下单） | ⭐⭐⭐ 对话式加购 + 自然语言管理 + 下单确认 + 库存校验 + 订单后推荐 |
| 多模态交互 | ⭐⭐⭐ 流式 ASR + 可调 TTS + 语音连续对话 + 跨模态拍照找货 |
| 对话智能与 RAG | ⭐⭐⭐ 多轮记忆 + 反选排除 + 结构化对比 + 商品级追问 + 长期画像 |
| 工程质量与性能 | ⭐⭐⭐ 缓存 + 首 token<1s + 端侧打磨 + 可观测 + CI + 容器化 |

**评审减分项规避**：零幻觉（GroundingGuard）✅ · 原生非 H5 ✅ · 克隆即跑无需大量手动配置（含 `self_check.py` 自检）✅ · 架构自主可解释（`defense_walkthrough.md`）✅。

---

## 🚀 快速开始

> ⚠️ **后端必须用 Python 3.11（≥3.10）**。系统 / Xcode 自带的 `python3` 常是 3.9,无法解析项目里的 `str | None` 等现代类型注解。

### 1）后端

```bash
cd CartCompass                                  # 项目根目录
python3.11 -m venv server/.venv                 # 务必用 3.11
source server/.venv/bin/activate
python --version                                # 确认输出 Python 3.11.x
pip install -r server/requirements.txt
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

种子库 `server/storage/seed.sqlite3`（321 件演示商品）随仓提交,**首次启动自动建库并补全分块与库存,无需手动入库**。访问 `http://127.0.0.1:8000/api/health` 自检。

**启用大模型 / 多模态能力**：复制 `server/.env.example` 为 `server/.env`,填入豆包/方舟 `ARK_API_KEY` 即可解锁 LLM 文案、多模态向量检索、跨模态拍照找货、VLM 图像理解;未配置则全部自动降级为本地确定性逻辑,服务不中断。

**（可选）启用 Chroma 向量库演示**：

```bash
pip install -r server/requirements-optional.txt
VECTOR_STORE_BACKEND=chroma PYTHONPATH=server python -m uvicorn app.main:app --port 8000
# 打开 /admin/metrics 可见“当前向量库 = chroma”
```

### 2）iOS 客户端

```bash
cd client-ios
open ShopGuide.xcodeproj      # 工程已提交,直接打开;选 iPhone 模拟器 Run
```
模拟器默认连接 `http://127.0.0.1:8000`。只有修改 `project.yml` 时才需要 `xcodegen generate` 重新生成。

### 3）Docker 一键起

```bash
docker compose up --build      # http://127.0.0.1:8000,含健康检查与多模态环境变量透传
```

---

## 📁 项目结构

```text
CartCompass/
├── client-ios/                 # 原生 iOS 客户端（SwiftUI）
│   └── ShopGuide/
│       ├── Views/              # 聊天、商品、购物车、侧栏等视图
│       ├── ViewModels/         # @Observable 视图模型 + 流式处理
│       ├── Services/           # SSE / 购物车 / 图搜 / LLM API 客户端
│       └── Models/             # 数据模型与会话持久化
├── server/                     # FastAPI 后端
│   ├── app/
│   │   ├── agent/              # 可控 Agent：编排器、规划、约束、守卫、购物车、售后、套装…
│   │   ├── rag/                # 混合检索、向量库(Chroma/SQLite)、多模态 embedding、图搜
│   │   ├── llm/                # LLM 网关、模型路由、结构化输出校验
│   │   ├── api/                # 路由（SSE、购物车、结账、画像、可观测）
│   │   ├── checkout/ db/ models/ travel/
│   │   └── observability.py    # 指标 / Trace / Dashboard
│   ├── data_pipeline/          # 采集→清洗→校验→导出 数据管线
│   ├── evaluation/             # 能力评测 + E2E 冒烟用例
│   ├── scripts/                # 自检、性能测量、向量预计算、压力测试
│   ├── tests/                  # 138 项 pytest
│   └── storage/seed.sqlite3    # 随仓种子库（克隆即跑）
└── docs/                       # 17 篇技术 / 演示 / 答辩 / 提交文档
```

---

## ✅ 测试与评测

```bash
# 138 项后端单测（离线确定性，无需 key）
PYTHONPATH=server python -m pytest server/tests -q

# 能力评测（需 key，输出 JSON/HTML 报告）
PYTHONPATH=server python server/evaluation/run_eval.py

# 端到端冒烟
PYTHONPATH=server python server/evaluation/run_e2e_smoke.py \
  --cases server/evaluation/cases/e2e_agent_smoke_cases.json
```

| 指标 | 结果 |
|---|---|
| 后端单测 | **138 passed** |
| 能力评测 | **24 / 24（pass rate 1.0）** |
| Top-3 命中率 / 反选过滤 / 主动澄清 / 加购成功率 / 跨模态图搜 / 预算套装 | 全部 **1.0** |

评测覆盖：意图识别、约束抽取、反选过滤、多轮上下文、长期偏好、闲聊插购物、跨模态图搜、预算套装、订单后推荐、来源 grounding 等。

---

## 📊 可观测性

后端启动后打开 **`http://127.0.0.1:8000/admin/metrics`**：商品覆盖率、公开来源占比、Agent 调用计数、Grounding Guard 通过/拦截、购物车成功率、**首 token 延迟、LLM 首字延迟、检索/拍照延迟、缓存命中率、p50/p95/p99**、当前向量库后端。每个请求 `done` 事件带 `trace_id`,`GET /api/traces/{trace_id}` 可回看意图识别 → 约束解析 → 候选过滤 → 检索 → Guard → 输出的全链路。

---

## 📚 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 系统架构与模块说明 |
| [`docs/llm_architecture.md`](docs/llm_architecture.md) | 可控 Agent、规划器、多模态嵌入与防幻觉 |
| [`docs/rag_design.md`](docs/rag_design.md) | RAG、上下文、反选、Chunking 与防幻觉设计 |
| [`docs/requirements_mapping.md`](docs/requirements_mapping.md) | 赛题要求逐条映射（实现 / 证明 / 话术 / 验证命令） |
| [`docs/defense_walkthrough.md`](docs/defense_walkthrough.md) | 3 分钟核心链路答辩讲解 |
| [`docs/demo_script.md`](docs/demo_script.md) · [`docs/runbook.md`](docs/runbook.md) | 演示脚本与开机 Runbook |
| [`docs/api.md`](docs/api.md) · [`docs/performance_report.md`](docs/performance_report.md) · [`docs/ui_design.md`](docs/ui_design.md) | 接口 / 性能 / UI 设计 |

---

## 💡 几个我刻意做的技术决策

- **为什么不让 LLM 直接出商品？** 因为那是幻觉的根源。我把 LLM 限定在"规划 + 文案",事实全部走工具 + Guard,这样换任何模型、甚至离线降级,商品与价格都不会错——这也是现场可演示的"杀手锏":切换/清空对话模型,Guard 依然拦幻觉。
- **为什么向量库默认 SQLite、Chroma 可选？** 321 条数据量下 SQLite + 余弦足够快且零运维;同时我抽象了 `VectorStore` 协议并接入 Chroma,证明检索层可插拔、能平滑迁移到生产级向量库,一行环境变量切换。
- **为什么不用 LangChain/LlamaIndex？** 为了把 RAG 链路的每一步(预过滤、BM25、向量、重排、Guard)都握在自己手里、可解释、可埋点——答辩时我能指着代码逐段讲清楚。

---

<div align="center">

**智购罗盘 CartCompass** · 字节 AI 全栈挑战赛参赛作品

让"看广告"变成"和懂行的导购聊一聊"。

</div>
