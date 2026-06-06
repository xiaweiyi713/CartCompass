# 智购罗盘 CartCompass · 基于 RAG 的多模态电商导购 AI Agent

> 字节 AI 全栈挑战赛参赛作品 · 原生 iOS(SwiftUI)+ FastAPI 后端
> **像豆包一样自然聊天,像导购一样精准选品,且商品事实零幻觉。**

用户可以**打字、说话或拍照**,Agent 在正常对话里无缝插入选品、对比、加购、售后问答和旅行套装规划。所有商品事实(价格、SKU、库存、卖点)只来自本地商品库工具,经 GroundingGuard 校验——**模型不编造任何促销、价格或库存**。

## ✨ 核心亮点

| 亮点 | 说明 |
|---|---|
| 🧠 **可控 Agent(planner-first)** | LLM 对话规划器决定"做什么",选品/对比/加购/售后全部走确定性工具,兼得自然对话与零幻觉 |
| 🛡️ **零幻觉 GroundingGuard** | 商品卡片只来自 SQLite;回复经段级流式校验,自动拦截编造的满减/优惠券/库存/价格,失败降级到本地确定性文案 |
| 🖼️ **多模态:语音 + 跨模态图搜** | 流式语音识别 + 可调语速/音色 TTS + 语音连续对话;拍照用豆包多模态向量在**图文共享空间**里跨模态匹配同类商品 |
| ⚡ **首 token < 1s 流式** | 显式购物意图走 fast-path 跳过二次 LLM 调用,确定性前缀先发,实测显式推荐首 token ~210ms |
| 📊 **实测可观测 Dashboard** | `/admin/metrics` 展示首 token 延迟、p50/p95/p99、缓存命中率、Guard 拦截、全链路 Trace |
| 🗂️ **真实数据 + 溯源** | 321 条商品(赛题示例 + Anker/Soundcore 公开页面采集 + Apple 官方 SKU 图),带来源、SKU、mock 库存与 chunk 证据 |

## 🏗️ 架构

```text
┌──────────────── iOS 客户端 (SwiftUI, @Observable) ────────────────┐
│  聊天流式 UI · 语音(ASR/TTS)· 拍照/相册 · 商品卡片/对比/购物车   │
│  侧栏:偏好 · 模型大脑 · 隐私合规 · 历史会话(SwiftData)          │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ SSE (token / products / cart / done+trace_id)
┌───────────────────────────────▼───────────────────────────────────┐
│                     FastAPI · AgentOrchestrator                     │
│  ① LLM 对话规划器(意图 + 购物强度 + 闲聊回复)        [LLM]        │
│  ② 确定性工具:检索 / 排序 / 对比 / 购物车 / 追问      [无 LLM]     │
│  ③ grounded 回复生成 + GroundingGuard(段级流式)     [LLM, 受控]  │
└───────────────────────────────┬───────────────────────────────────┘
       SQL 预过滤 + BM25 + Chroma/豆包向量(可选) + hashing 兜底 + 可信度重排
                                 │
                    SQLite 事实库(321 商品 · chunks · SKU · 库存 · RAG 知识)
```

详见 `docs/architecture.md` 与 `docs/llm_architecture.md`。

## 🚀 快速开始

### 后端(必须 Python 3.11,≥3.10)

```bash
cd "字节AI全栈挑战赛"                        # 项目根目录
python3.11 -m venv server/.venv             # 必须用 3.11;系统默认 python3 常是 3.9,无法解析 str|None 等现代注解
source server/.venv/bin/activate
python --version                            # 确认输出 Python 3.11.x(≥3.10),不是 3.9
pip install -r server/requirements.txt
PYTHONPATH=server python server/scripts/self_check.py
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> ⚠️ 一定要确认 `python --version` 是 3.11.x。macOS / Xcode 自带的 `python3` 往往是 3.9,直接用它建 venv 会在启动时报 `unsupported operand type(s) for |`(代码用了 3.10+ 的 `str | None` 注解)。
>
> DB / 静态目录路径由代码位置解析为绝对路径,**从项目根或 `server/` 目录启动都不会找错库**(`.env` 不要用相对路径覆盖 `CARTCOMPASS_DB`;旧的 `SHOPGUIDE_DB` 仍兼容)。
>
> **开箱即用**:312+9=321 条演示商品库已作为种子快照提交在 `server/storage/seed.sqlite3`。首次启动检测不到运行库时会自动复制种子库,无需手动入库(Docker 同理)。
>
> **启用豆包/方舟能力**:复制 `server/.env.example` 为 `server/.env` 并填入 `ARK_API_KEY`,即可解锁 LLM 文案生成、多模态向量检索、跨模态拍照找货与 VLM 图像理解;未配置时全部自动降级到本地确定性逻辑,服务不中断。
>
> **可选 Chroma 向量库**:如果评审需要看到标准向量数据库，可执行 `pip install -r server/requirements-optional.txt` 并设置 `VECTOR_STORE_BACKEND=chroma`。有 `TEXT_EMBEDDING_*` 和预计算向量时，Chroma 存真实商品文本 embedding；否则 Chroma 承载本地 hashing 向量；如依赖不可用再自动回退 SQLite。`/api/health`、`/api/metrics` 和 `/admin/metrics` 会显示当前实际 backend。

### Docker

```bash
docker compose up --build cartcompass-api  # http://127.0.0.1:8000
```

Compose 已透传 `ARK_*`、`VISION_UNDERSTANDING_*`、`TEXT_EMBEDDING_*`(多模态语义/图搜)和 `CORS_ALLOW_ORIGINS`,并挂载 `storage` / `static`、内置健康检查。

### iOS

工程已提交,**直接打开即可**(无需 xcodegen):

```bash
cd client-ios
open ShopGuide.xcodeproj
```

选 iPhone 模拟器 Run。App 显示名为「智购罗盘」,模拟器默认连接 `http://127.0.0.1:8000`。

> 只有改了 `client-ios/project.yml`(如后端地址 `SHOPGUIDE_API_BASE_URL`)才需要 `xcodegen generate` 重新生成,然后重开工程。
>
> ⚠️ 若 Run 报 `Multiple commands produce '….app'`:多半是用旧 xcodegen 重新生成出了 `PRODUCT_NAME` 为空的坏工程。已在 `project.yml` 显式设 `PRODUCT_NAME` 修复;若仍遇到,执行 `git checkout -- client-ios/ShopGuide.xcodeproj/project.pbxproj` 还原已提交工程,删掉 `~/Library/Developer/Xcode/DerivedData/ShopGuide-*`,再重开 Xcode 构建。

## 🧩 能力一览(可直接念给评委看的示例)

- **自然对话不硬推**:`今天好累啊不想动` → 共情闲聊,不弹商品卡片;`推荐降噪耳机,预算2000以内` → 直接给卡片。
- **主动澄清**:先问 `推荐手机`,Agent 追问拍照/续航/性能/预算;再答 `拍照优先,预算4000` 继承上下文继续推荐。
- **反选过滤**:`推荐适合油皮的防晒,200元以内,不要含酒精`。
- **长期偏好记忆**:`记住我以后护肤品不要含酒精,我是油皮,预算200` → 之后说 `推荐防晒` 自动带上条件;可 `查看我的偏好` / `清除我的偏好`。
- **替代/平替/换品牌**:推荐后 `第一款太贵了,有没有平替`、`换个品牌`、`有没有更高端一点的`。
- **跨轮追问**:`第一款差评主要说什么`、`这款适合敏感肌吗,有没有酒精`、`第一款不同规格怎么选`(基于 FAQ/评论/SKU/来源)。
- **预算套装**:`我1000元预算,下周去三亚,帮我配一套防晒和出行用品` → 结构化 Shopping Plan(必需/可升级项、总价、剩余预算、选择理由)。
- **售后问答**:`第一款能退换货吗` → 说明 Demo 不产生真实支付/物流/平台承诺,提示核对公开来源,不编造政策。
- **多模态语音**:点麦克风实时转写(聆听浮层);长按朗读按钮调语速/音色;开"语音连续对话"后说完自动发送并朗读回复。
- **拍照找货**:上传商品图 → 豆包多模态向量在图文共享空间跨模态匹配同类(手机照片召回手机、防晒照片召回防晒),融合 VLM 理解 + 轻量视觉特征。
- **购物车与下单**:`把第一款加到购物车,数量改成2`;`我要下单` → Agent 要求地址、汇总订单、等待确认,最终发出结构化 `order` 事件和订单卡。

## ✅ 测试与评测

```bash
PYTHONPATH=server python3 -m pytest server/tests -q          # 后端测试(离线确定性)
PYTHONPATH=server python3 server/evaluation/run_eval.py      # 能力评测,输出 JSON/HTML 报告
```

- **测试覆盖**:健康检查、SSE 推荐/澄清/反选、上下文切换、旅行套装、长期偏好、替代品、反馈闭环、售后问答、订单后推荐、混合检索评分、可解释推荐、商品级追问、SKU 购物车、图片搜索、Agent planner 路由(mock LLM)等。
- **评测能力项**:意图识别、约束抽取、反选过滤、多轮上下文、闲聊插购物、跨模态图搜(`requires: embedding`)、预算套装、来源 grounding 等,报告落在 `server/evaluation/output/`。
- **性能复现**:`PYTHONPATH=server python3 server/scripts/measure_performance.py --repeat 2` 输出首 Token p50/p95、总耗时 p50/p95、缓存命中率和 Trace 到 `server/evaluation/output/performance_report.json`。
- CI(GitHub Actions)在每次 push/PR 自动跑 pytest。

## 📊 可观测性

后端启动后打开 `http://127.0.0.1:8000/admin/metrics`:商品覆盖率、公开来源占比、当前向量库 backend、Agent 调用计数、Grounding Guard 拦截、购物车成功率、**首 token 延迟、LLM 首字延迟、检索/拍照延迟、缓存命中率、p50/p95/p99**。每个请求 `done` 事件带 `trace_id`,可 `GET /api/traces/{trace_id}` 回看意图识别→约束解析→候选过滤→检索→Guard→输出的全链路。

压力测试:

```bash
python3 server/scripts/stress_test_retrieval.py --sample 1000 --concurrency 16 --p95-ms 800
```

## 📚 文档

| 文档 | 内容 |
|---|---|
| `docs/architecture.md` | 系统架构与模块说明 |
| `docs/llm_architecture.md` | 可控 Agent、规划器、多模态嵌入与防幻觉 |
| `docs/rag_design.md` | RAG、上下文、反选与防幻觉设计 |
| `docs/submission_form.md` | 按比赛提交模板整理的提交表 |
| `docs/submission_design_document.md` | 可复制到飞书的技术设计文档 |
| `docs/submission_instruction_document.md` | 可复制到飞书的部署与体验说明文档 |
| `docs/defense_walkthrough.md` | 3 分钟核心链路讲解稿 |
| `docs/api.md` | 接口文档 |
| `docs/runbook.md` | 干净环境启动、自检、Chroma 演示与回归测试步骤 |
| `docs/ui_design.md` | UI 与交互设计 |
| `docs/demo_script.md` | 答辩演示脚本 |
| `docs/video_demo_flow.md` | 录制演示视频的逐镜头流程、口播和备用指令 |
| `docs/full_presentation_script.md` | 极详细项目介绍稿件素材库 |
| `docs/requirements_mapping.md` | 赛题要求逐项映射、验证命令和 Demo 顺序 |

> 注:赛题官方参考数据集(`ecommerce_agent_dataset`)体积较大,未纳入仓库;演示无需它(种子库已开箱即用)。如需从官方数据重建约 100 条基础数据,解压数据集到 `data/extracted/` 后运行 `python scripts/ingest_products.py`(会清表重写,不含另行采集的真实商品)。
