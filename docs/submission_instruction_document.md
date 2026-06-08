# 智购罗盘 CartCompass 部署与体验说明文档

## 0. 获取代码

```bash
git clone https://github.com/xiaweiyi713/CartCompass.git
cd CartCompass
```

> 仓库开箱即用：321 条演示商品的种子库已随仓提交，首次启动会自动建库并补全分块与库存，无需手动入库。

## 1. 快速体验路径

评委最快体验方式：

1. 启动 FastAPI 后端（见第 2 节，约 1 分钟）。
2. 打开 `client-ios/ShopGuide.xcodeproj`，选 iPhone 模拟器运行 iOS App。App 显示名为「智购罗盘」。
3. 发送导购问题，观察商品卡、流式回答、对比、购物车、下单和 Dashboard Trace。

后端没有模型 Key 也能运行（自动降级本地确定性导购）；配置 `ARK_API_KEY` 后可启用更完整的 LLM 生成、VLM 图像理解、多模态 embedding 与服务端语音转写。

## 2. 本地后端部署

要求 Python 3.10+，推荐 Python 3.11。

```bash
cd CartCompass
python3.11 -m venv server/.venv
source server/.venv/bin/activate
python --version
pip install -r server/requirements.txt
PYTHONPATH=server python server/scripts/self_check.py
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端验证：

```bash
source server/.venv/bin/activate
PYTHONPATH=server python server/scripts/self_check.py --require-server
curl http://127.0.0.1:8000/api/health
```

预期结果：

- `/api/health` 返回 `ok: true`。
- `product_count` 大于 100，当前种子库为 321 条商品。
- `vector_store.active_backend` 显示当前向量后端。

## 3. Docker 部署

```bash
cd CartCompass
docker compose up --build cartcompass-api
```

服务地址：`http://127.0.0.1:8000`

Docker Compose 会挂载 `server/storage` 和 `server/static`，并透传 Ark、VLM、embedding、CORS 等环境变量。

## 4. 可选模型配置

复制环境变量文件并填入 Key：

```bash
cp server/.env.example server/.env
```

常用配置：

```bash
ARK_API_KEY=YOUR_KEY
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-lite-260428
TEXT_EMBEDDING_MODEL=doubao-embedding-vision-251215
VISION_UNDERSTANDING_MODEL=doubao-seed-2-0-lite-260428
VISION_UNDERSTANDING_JSON_MODE=false
```

没有 Key 时，项目会自动降级到本地确定性导购，商品事实和购物车链路不受影响。

## 5. 可选 Chroma 向量库

如需展示标准向量数据库：

```bash
source server/.venv/bin/activate
pip install -r server/requirements-optional.txt
VECTOR_STORE_BACKEND=chroma \
CHROMA_PATH=server/storage/chroma \
CHROMA_COLLECTION=cartcompass_products \
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证：

- `/api/health` 中 `vector_store.active_backend` 为 `chroma_hashing_vector` 或 `chroma_text_embedding`。
- `/admin/metrics` 显示当前向量库。
- 请求 Trace 中能看到 Chroma 或 text embedding 检索链路。

## 6. iOS App 运行

```bash
cd client-ios
open ShopGuide.xcodeproj
```

选择 iPhone 模拟器或真机运行。默认后端地址为 `http://127.0.0.1:8000`。

注意：

- 提交前已包含 `ShopGuide.xcodeproj`，普通体验不需要现场运行 `xcodegen generate`。
- App 显示名、Bundle ID 和产品名已改为「智购罗盘 / CartCompass」。
- 若修改 `client-ios/project.yml` 后重新生成工程，再重新打开 Xcode。

## 7. 核心体验脚本

### 7.1 主动澄清

输入：

```text
推荐手机
```

预期：Agent 不直接乱推，会追问拍照、续航、游戏性能和预算。

继续输入：

```text
游戏，预算9999
```

预期：返回手机商品卡和 grounded 推荐理由。

### 7.2 条件筛选与反选

输入：

```text
推荐适合油皮的防晒，200元以内，不要含酒精
```

预期：商品卡先出现，回答说明来自本地商品库，推荐结果满足预算和排除条件。

### 7.3 对比

输入：

```text
对比前两款
```

预期：返回结构化 `compare` 事件，iOS 渲染对比卡。

### 7.4 平替和反馈

输入：

```text
第一款太贵了，有没有平替
```

预期：系统继承上一轮上下文，返回更便宜替代品。

### 7.5 长期偏好

输入：

```text
记住我以后护肤品不要含酒精，我是油皮，预算200
```

再输入：

```text
推荐防晒
```

预期：自动带上油皮、预算和酒精排除偏好。

### 7.6 购物车与模拟下单

输入：

```text
把第一款加到购物车
我要下单
北京市朝阳区 Demo 路 1 号
确认下单
```

预期：返回购物车状态、地址确认、订单汇总和订单卡；沙箱结算不产生真实扣款。

### 7.7 语音输入与朗读

点击聊天页底部麦克风，说出需求（如「推荐拍照好的手机四千以内」），观察聆听浮层**实时转写**；长按顶部喇叭可调**语速 / 音色**；开启「语音连续对话」后说完会**自动发送并朗读回复**。端侧识别为主，亦可走服务端 `POST /api/speech/transcribe` 转写音频。

### 7.8 图片找货

在 App 中点击图片入口，上传：

```text
server/static/product_images/p_anker_001_fc881685.jpg
```

预期：返回同类充电设备商品，推荐理由中包含图文语义匹配、VLM 关键词或视觉特征。

### 7.9 可观测性

打开：

```text
http://127.0.0.1:8000/admin/metrics
```

预期：看到商品数量、向量库 backend、Agent 调用次数、首 token 延迟、p50/p95/p99、缓存命中率和最近 Trace。

## 8. 自动化测试与评测

```bash
source server/.venv/bin/activate
PYTHONPATH=server python -m pytest server/tests -q
PYTHONPATH=server python server/evaluation/run_eval.py
```

性能复现：

```bash
PYTHONPATH=server python server/scripts/measure_performance.py --repeat 2
```

输出报告位于 `server/evaluation/output/`。

## 9. 演示视频建议

5-10 分钟视频建议顺序：

1. 30 秒介绍项目定位：多模态 RAG 电商导购，事实零幻觉。
2. 1 分钟展示主动澄清和条件推荐。
3. 1 分钟展示商品卡、详情页、SKU 和来源依据。
4. 1 分钟展示对比、平替和多轮上下文。
5. 1 分钟展示购物车、地址确认、模拟下单和订单卡。
6. 1 分钟展示语音输入/TTS 和拍照找货。
7. 1 分钟展示 `/admin/metrics`、Trace、测试和降级策略。

详细镜头脚本见 `docs/video_demo_flow.md`。

## 10. 常见问题

| 问题 | 处理 |
|---|---|
| Python 启动报类型注解错误 | 确认使用 Python 3.10+，推荐 `python3.11` |
| `/api/health` 字段不对 | 8000 端口可能是旧进程，停止旧服务后重新启动 |
| 没有模型 Key | 可以正常演示本地导购；只影响 LLM 润色、VLM 和真实 embedding |
| iOS 连不上后端 | 确认后端在 `127.0.0.1:8000`；真机演示需改为电脑局域网 IP |
| 重新生成 Xcode 工程后异常 | 使用已提交的 `ShopGuide.xcodeproj`，或按 `project.yml` 重新生成后重开 Xcode |
| Chroma 没生效 | 安装 `server/requirements-optional.txt`，设置 `VECTOR_STORE_BACKEND=chroma` 并检查 `/api/health` |
