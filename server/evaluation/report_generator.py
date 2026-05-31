from __future__ import annotations

import html
from datetime import datetime
from typing import Any


def render_report(results: dict[str, Any]) -> str:
    metrics = results["metrics"]
    case_rows = "".join(_case_row(case) for case in results["cases"])
    metric_cards = "".join(
        _metric_card(label, _format_metric(value)) for label, value in metrics.items()
    )
    generated_at = html.escape(results.get("generated_at", datetime.now().isoformat(timespec="seconds")))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ShopGuide 自动化评测报告</title>
  <style>
    :root {{ color-scheme: light dark; --accent:#168fa2; --bg:#f7f9fb; --card:#fff; --line:#dce6eb; --ok:#138a57; --bad:#c9372c; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101417; --card:#172025; --line:#293942; }} }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:CanvasText; }}
    header {{ padding:30px 28px 18px; background:linear-gradient(135deg,#0d8fa7,#34c6b1); color:white; }}
    main {{ max-width:1180px; margin:auto; padding:22px 28px 42px; }}
    h1 {{ margin:0 0 8px; font-size:28px; letter-spacing:0; }}
    h2 {{ margin:26px 0 12px; font-size:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 8px 24px rgba(0,0,0,.05); }}
    .label {{ font-size:12px; opacity:.68; text-transform:uppercase; }}
    .value {{ font-size:26px; font-weight:760; margin-top:6px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:14px; }}
    th {{ background:rgba(22,143,162,.12); }}
    .pass {{ color:var(--ok); font-weight:700; }}
    .fail {{ color:var(--bad); font-weight:700; }}
    code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  </style>
</head>
<body>
  <header>
    <h1>ShopGuide 自动化评测报告</h1>
    <p>生成时间：{generated_at}</p>
  </header>
  <main>
    <h2>核心指标</h2>
    <section class="grid">{metric_cards}</section>
    <h2>用例明细</h2>
    <table>
      <thead><tr><th>用例</th><th>类型</th><th>结果</th><th>耗时</th><th>命中商品 / 说明</th></tr></thead>
      <tbody>{case_rows}</tbody>
    </table>
  </main>
</body>
</html>"""


def _case_row(case: dict[str, Any]) -> str:
    status = "PASS" if case.get("passed") else "FAIL"
    status_class = "pass" if case.get("passed") else "fail"
    details = case.get("details") or {}
    detail_text = html.escape(str(details))[:900]
    product_ids = ", ".join(case.get("product_ids") or [])
    if product_ids:
        detail_text = f"<code>{html.escape(product_ids)}</code><br>{detail_text}"
    return (
        "<tr>"
        f"<td>{html.escape(case['id'])}</td>"
        f"<td>{html.escape(case['type'])}</td>"
        f"<td class='{status_class}'>{status}</td>"
        f"<td>{case.get('latency_ms', 0):.2f} ms</td>"
        f"<td>{detail_text}</td>"
        "</tr>"
    )


def _metric_card(label: str, value: str) -> str:
    return (
        "<div class='card'>"
        f"<div class='label'>{html.escape(label.replace('_', ' '))}</div>"
        f"<div class='value'>{html.escape(value)}</div>"
        "</div>"
    )


def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.2f}"
    return str(value)
