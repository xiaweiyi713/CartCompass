from __future__ import annotations

import contextvars
import html
import statistics
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_trace_id", default=None)


@dataclass
class Trace:
    trace_id: str
    kind: str
    input: dict[str, Any]
    started_at: float
    finished_at: float | None = None
    status: str = "running"
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at) * 1000, 2)


class ObservabilityStore:
    def __init__(self, max_traces: int = 80, max_latency_points: int = 400) -> None:
        self.max_traces = max_traces
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.latencies: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_latency_points))
        self.traces: OrderedDict[str, Trace] = OrderedDict()

    def start_trace(self, kind: str, payload: dict[str, Any]) -> str:
        trace_id = uuid.uuid4().hex[:12]
        self.traces[trace_id] = Trace(trace_id=trace_id, kind=kind, input=payload, started_at=time.time())
        while len(self.traces) > self.max_traces:
            self.traces.popitem(last=False)
        _current_trace_id.set(trace_id)
        self.increment(f"{kind}_requests")
        return trace_id

    def current_trace_id(self) -> str | None:
        return _current_trace_id.get()

    def set_current_trace(self, trace_id: str | None) -> contextvars.Token:
        return _current_trace_id.set(trace_id)

    def reset_current_trace(self, token: contextvars.Token) -> None:
        _current_trace_id.reset(token)

    def add_step(self, trace_id: str | None, name: str, payload: dict[str, Any]) -> None:
        if not trace_id or trace_id not in self.traces:
            return
        self.traces[trace_id].steps.append(
            {
                "name": name,
                "at_ms": round((time.time() - self.traces[trace_id].started_at) * 1000, 2),
                "payload": payload,
            }
        )

    def add_current_step(self, name: str, payload: dict[str, Any]) -> None:
        self.add_step(self.current_trace_id(), name, payload)

    def finish_trace(self, trace_id: str | None, status: str = "ok") -> None:
        if not trace_id or trace_id not in self.traces:
            return
        trace = self.traces[trace_id]
        trace.status = status
        trace.finished_at = time.time()
        if trace.duration_ms is not None:
            self.record_latency(f"{trace.kind}_latency_ms", trace.duration_ms)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def record_latency(self, name: str, value_ms: float) -> None:
        self.latencies[name].append(float(value_ms))

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        trace = self.traces.get(trace_id)
        if not trace:
            return None
        return self._trace_payload(trace)

    def recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        traces = list(self.traces.values())[-limit:]
        return [self._trace_payload(trace) for trace in reversed(traces)]

    def snapshot(self, product_stats: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_stats": product_stats,
            "derived_metrics": self._derived_metrics(),
            "counters": dict(sorted(self.counters.items())),
            "latencies": {name: self._latency_summary(values) for name, values in sorted(self.latencies.items())},
            "recent_traces": self.recent_traces(limit=12),
        }

    def render_html(self, product_stats: dict[str, Any]) -> str:
        data = self.snapshot(product_stats)
        counters = data["counters"]
        derived_metrics = data["derived_metrics"]
        latencies = data["latencies"]
        traces = data["recent_traces"]
        product_cards = "".join(
            self._metric_card(label, str(value)) for label, value in product_stats.items()
        )
        derived_cards = "".join(
            self._metric_card(label.replace("_", " "), str(value)) for label, value in derived_metrics.items()
        )
        counter_cards = "".join(
            self._metric_card(label.replace("_", " "), str(value)) for label, value in counters.items()
        )
        latency_rows = "".join(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{summary['count']}</td>"
            f"<td>{summary['p50']:.2f}</td>"
            f"<td>{summary['p95']:.2f}</td>"
            f"<td>{summary['p99']:.2f}</td>"
            f"<td>{summary['max']:.2f}</td>"
            "</tr>"
            for name, summary in latencies.items()
        )
        trace_rows = "".join(
            "<tr>"
            f"<td><a href='/api/traces/{trace['trace_id']}'>{trace['trace_id']}</a></td>"
            f"<td>{html.escape(trace['kind'])}</td>"
            f"<td>{html.escape(trace['status'])}</td>"
            f"<td>{trace.get('duration_ms') or '-'} ms</td>"
            f"<td>{html.escape(str(trace['input'].get('message') or trace['input'].get('query') or ''))[:90]}</td>"
            "</tr>"
            for trace in traces
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShopGuide Evaluation Dashboard</title>
  <style>
    :root {{ color-scheme: light dark; --accent:#168fa2; --bg:#f6f8fa; --card:#ffffff; --line:#d8e2e7; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101417; --card:#172025; --line:#2a3a41; }} }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:CanvasText; }}
    header {{ padding:32px 28px 18px; background:linear-gradient(135deg,#0d8fa7,#34c6b1); color:white; }}
    h1 {{ margin:0; font-size:28px; letter-spacing:0; }}
    h2 {{ margin:28px 0 12px; font-size:18px; }}
    main {{ padding:20px 28px 40px; max-width:1180px; margin:auto; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 8px 26px rgba(0,0,0,.05); }}
    .label {{ font-size:12px; opacity:.68; text-transform:uppercase; }}
    .value {{ font-size:25px; font-weight:750; margin-top:6px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; font-size:14px; }}
    th {{ background:rgba(22,143,162,.12); }}
    a {{ color:var(--accent); }}
  </style>
</head>
<body>
  <header>
    <h1>ShopGuide 评测与可观测性 Dashboard</h1>
    <p>商品覆盖、Agent 调用、延迟分布和最近 Trace 都在这里汇总。</p>
  </header>
  <main>
    <h2>商品与数据质量</h2>
    <section class="grid">{product_cards}</section>
    <h2>性能与缓存</h2>
    <section class="grid">{derived_cards or '<div class="card">暂无缓存数据</div>'}</section>
    <h2>运行计数器</h2>
    <section class="grid">{counter_cards or '<div class="card">暂无运行数据</div>'}</section>
    <h2>延迟指标</h2>
    <table><thead><tr><th>指标</th><th>样本</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th><th>max ms</th></tr></thead><tbody>{latency_rows}</tbody></table>
    <h2>最近 Agent Trace</h2>
    <table><thead><tr><th>Trace</th><th>类型</th><th>状态</th><th>耗时</th><th>输入</th></tr></thead><tbody>{trace_rows}</tbody></table>
  </main>
</body>
</html>"""

    def _trace_payload(self, trace: Trace) -> dict[str, Any]:
        return {
            "trace_id": trace.trace_id,
            "kind": trace.kind,
            "input": trace.input,
            "status": trace.status,
            "duration_ms": trace.duration_ms,
            "steps": trace.steps,
        }

    def _latency_summary(self, values: deque[float]) -> dict[str, float | int]:
        if not values:
            return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        ordered = sorted(values)
        return {
            "count": len(ordered),
            "p50": self._percentile(ordered, 50),
            "p95": self._percentile(ordered, 95),
            "p99": self._percentile(ordered, 99),
            "max": max(ordered),
        }

    def _derived_metrics(self) -> dict[str, str]:
        return {
            "retrieval_cache_hit_rate": self._hit_rate("retrieval_cache_hits", "retrieval_cache_misses"),
            "recommendation_cache_hit_rate": self._hit_rate("recommendation_cache_hits", "recommendation_cache_misses"),
        }

    def _hit_rate(self, hit_counter: str, miss_counter: str) -> str:
        hits = self.counters.get(hit_counter, 0)
        misses = self.counters.get(miss_counter, 0)
        total = hits + misses
        if total <= 0:
            return "n/a"
        return f"{hits / total:.1%}"

    def _percentile(self, values: list[float], percent: int) -> float:
        if len(values) == 1:
            return values[0]
        return statistics.quantiles(values, n=100, method="inclusive")[percent - 1]

    def _metric_card(self, label: str, value: str) -> str:
        return (
            "<div class='card'>"
            f"<div class='label'>{html.escape(label)}</div>"
            f"<div class='value'>{html.escape(value)}</div>"
            "</div>"
        )


observability = ObservabilityStore()
