# Demo Runbook

这份 runbook 用于在干净环境里复现“克隆 -> 起后端 -> 跑 iOS -> 展示可观测性”的最短路径，避免答辩现场出现大量手动配置。

## 1. 后端启动

```bash
cd "字节AI全栈挑战赛"
python3.11 -m venv server/.venv
source server/.venv/bin/activate
python --version
pip install -r server/requirements.txt
PYTHONPATH=server python server/scripts/self_check.py
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端验证：

```bash
source server/.venv/bin/activate
PYTHONPATH=server python server/scripts/self_check.py --require-server
curl http://127.0.0.1:8000/api/health
```

必须确认：

- `python --version` 是 3.10+，推荐 3.11。
- `/api/health` 返回 `ok: true`。
- `product_count` 大于 100。
- `vector_store.active_backend` 与演示口径一致。

## 2. 启用 Chroma 演示路径

如果需要展示标准向量数据库：

```bash
source server/.venv/bin/activate
pip install -r server/requirements-optional.txt
export VECTOR_STORE_BACKEND=chroma
export CHROMA_PATH=server/storage/chroma
PYTHONPATH=server python server/scripts/self_check.py
PYTHONPATH=server python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

验证点：

- `/api/health` 的 `vector_store.active_backend` 是 `chroma_hashing_vector` 或 `chroma_text_embedding`。
- `/admin/metrics` 的商品与数据质量卡片显示“当前向量库”和“Chroma 持久化”。
- 一次推荐请求后的 Trace 里 `retrieval_stack` 包含 `Chroma vector DB` 或 `Chroma text_embedding(...)`。

没有文本 embedding key 时，Chroma 会承载本地 hashing 向量；配置 `TEXT_EMBEDDING_*` 并预计算后才会显示 `chroma_text_embedding`。

## 3. iOS 启动

```bash
cd client-ios
open ShopGuide.xcodeproj
```

选择 iPhone 真机或模拟器运行。答辩演示优先使用真机 + Release，因为模拟器对毛玻璃和语音链路更容易受宿主机影响。

如果改过 `client-ios/project.yml` 才需要重新生成工程；普通演示不要现场跑 xcodegen。

## 4. 演示前检查清单

- 重启后端，确认加载的是当前代码；如果 `self_check.py` 提示 `/api/health` 没有 `vector_store` 字段，说明 8000 端口还是旧实例。
- 用 `VECTOR_STORE_BACKEND=chroma` 启动后端，再打开 `/admin/metrics` 给评委看“当前向量库=chroma_text_embedding/chroma_hashing_vector”。
- 使用真机 + Release 跑 iOS；模拟器对毛玻璃和语音链路仍可能受宿主机软渲染影响。
- 演示开始前先跑 `PYTHONPATH=server python server/scripts/self_check.py --require-server`。
- 打开 `http://127.0.0.1:8000/admin/metrics`。
- 发送“推荐适合油皮的防晒，200元以内，不要含酒精”，确认商品卡先出现、首 token 正常。
- 打开该请求的 `/api/traces/{trace_id}`，确认链路包含 intent/constraint/retrieval/guard。
- 用 App 点开侧栏、商品详情、购物车，确认动画流畅且文本不重叠。
- 走一次“把第一款加到购物车 -> 我要下单 -> 确认下单”，确认 order 卡片返回。

## 5. 回归测试

```bash
source server/.venv/bin/activate
PYTHONPATH=server python -m pytest server/tests -q
PYTHONPATH=server python server/evaluation/run_e2e_smoke.py --output-dir server/evaluation/output/e2e_goal_smoke
```

如启用 Chroma，再补一次：

```bash
VECTOR_STORE_BACKEND=chroma PYTHONPATH=server python -m pytest server/tests/test_observability.py -q
```
