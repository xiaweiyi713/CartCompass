# 智购罗盘 CartCompass 提交信息表

> 用法：把本文复制到比赛提交表或飞书文档中；`待填写` 项在最终提交前补齐并打开访问权限。

## 队名（仅组队填写）

个人参赛可留空；组队参赛填写队名。

## 团队成员

- 待填写：姓名 / 学校或单位 / 联系方式

## 分工说明（仅组队填写）

个人参赛可填写“独立完成”。组队参赛建议按下面格式补齐：

| 成员 | 分工 |
|---|---|
| 待填写 | iOS 客户端、SwiftUI 交互、语音/图片入口 |
| 待填写 | FastAPI 后端、RAG 检索、Agent 编排、测试与部署 |
| 待填写 | 数据采集清洗、演示视频、文档与答辩 |

## 项目名称

智购罗盘 CartCompass

副标题：基于 RAG 的多模态电商智能导购 AI Agent

## 代码仓库地址

- GitHub：待填写
- Zip 包：如不提交 GitHub，在此填写压缩包说明

## 设计文档

- 飞书文档链接：待填写，需打开评审可访问权限
- 本地源文档：[submission_design_document.md](submission_design_document.md)

## 说明文档

- 飞书文档链接：待填写，需打开评审可访问权限
- 本地源文档：[submission_instruction_document.md](submission_instruction_document.md)

## 演示视频

- 视频链接：待填写
- 建议时长：5-10 分钟
- 录制脚本参考：[video_demo_flow.md](video_demo_flow.md)

## 项目亮点/创新点

1. **受控 Agent + GroundingGuard**：LLM 负责意图规划和自然表达，商品筛选、对比、购物车、下单和售后全部走确定性工具；价格、SKU、库存、来源均来自 SQLite 商品事实库，流式回复会被 GroundingGuard 拦截未落库承诺。
2. **原生 iOS 多模态导购闭环**：不是网页壳 Demo，而是 SwiftUI 原生 App，覆盖文字、语音 ASR/TTS、拍照/相册找货、商品卡、SKU 详情、对比、购物车、模拟下单和订单后推荐。
3. **可评测、可观测、可复现**：内置 321 条种子商品、Docker/本地启动脚本、pytest/E2E 评测、`/admin/metrics` Dashboard、请求 Trace、首 token 延迟和缓存命中率指标，便于评委快速验证。

## 其他补充信息

- 后端无模型 Key 也可运行，会自动降级到本地确定性推荐；配置 `ARK_API_KEY` 后可启用 Ark/Doubao 对话、VLM 图像理解和多模态 embedding。
- iOS 工程文件仍为 `client-ios/ShopGuide.xcodeproj`，这是为了保留既有源码路径和提交稳定性；App 显示名、Bundle ID 和提交品牌已改为「智购罗盘 / CartCompass」。
- 后端新环境变量为 `CARTCOMPASS_DB`、`CARTCOMPASS_STATIC_DIR`，旧 `SHOPGUIDE_*` 变量仍兼容，避免已有本地环境失效。
