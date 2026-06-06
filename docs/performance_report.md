# 智购罗盘 CartCompass 性能复测说明

## 复测命令

```bash
PYTHONPATH=server python3 server/scripts/measure_performance.py --repeat 2
```

脚本会走 FastAPI TestClient，执行防晒、手机高预算、三亚旅行套装、通勤耳机 4 类典型查询。`--repeat 2` 会重复同一组查询，用来观察检索缓存命中。

输出文件：

```text
server/evaluation/output/performance_report.json
```

## 关键指标

- `first_token_p50_ms` / `first_token_p95_ms`：来自后端 Trace 的 `sse_first_token`，不是客户端解析时间。
- `total_latency_p50_ms` / `total_latency_p95_ms`：完整 SSE 响应总耗时。
- `retrieval_cache_hit_rate`：相同 query + 结构化约束 + limit + 向量后端身份的检索缓存命中率。
- `retrieval_stack`：每轮 Trace 中的检索链路，例如 `Chroma text_embedding(...)`、`text_embedding(...)` 或 `hashing_vector`。

## 当前优化点

- 明确购物意图走 deterministic fast-path，跳过不必要的 LLM planner。
- 商品卡片先于长文案输出，降低用户感知等待。
- 检索缓存复用结构化过滤、BM25、向量重排结果。
- Chroma 启用时优先承载真实商品文本 embedding；无 key/无向量时使用 hashing fallback，保证演示稳定。
