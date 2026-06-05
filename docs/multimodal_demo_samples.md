# 多模态图片找货样例

样例配置见 `server/evaluation/cases/multimodal_demo_samples.json`。这些图片都来自本地商品库静态图，适合答辩时稳定复现。

## 运行方式

```bash
python3 - <<'PY'
import json
from pathlib import Path
import requests

base = "http://127.0.0.1:8000"
samples = json.loads(Path("server/evaluation/cases/multimodal_demo_samples.json").read_text())
for sample in samples:
    path = Path(sample["image"])
    with path.open("rb") as fh:
        response = requests.post(
            base + "/api/image_search",
            params={"query": sample["query"]},
            files={"file": (path.name, fh, "image/jpeg")},
            timeout=30,
        )
    products = response.json().get("products", [])
    print(sample["id"], [p["product_id"] for p in products[:5]])
PY
```

## 2026-06-04 本地验证结果

当前后端 `/api/health` 显示：

- `llm_configured=true`
- `provider=ark`
- `text_embedding.model=doubao-embedding-vision-251215`

验证结果：

| 样例 | 图片 | Query | Top 5 | 结论 |
|---|---|---|---|---|
| 手机 | `p_digital_016.jpg` | `拍照好一点的手机` | `p_digital_016`, `p_digital_002`, `p_digital_015`, `p_digital_003`, `p_digital_008` | Top1 命中，Top3 同为数码电子 |
| 充电设备 | `p_anker_001_fc881685.jpg` | `旅行快充充电设备` | `p_anker_001_fc881685`, `p_anker_006_8c72c769`, `p_real_026_714cbdac`, `p_real_025_f464bcf1`, `p_anker_007_e0ef82c1` | Top1 命中，Top3 同为数码电子 |
| 防晒 | `p_beauty_001.jpg` | `油皮防晒` | `p_beauty_001`, `p_beauty_020`, `p_beauty_002`, `p_beauty_006`, `p_beauty_010` | Top1 命中，Top3 同为美妆护肤 |
| 防水徒步鞋 | `p_clothes_014.jpg` | `下雨通勤防滑鞋` | `p_clothes_014`, `p_clothes_015`, `p_clothes_017`, `p_clothes_009`, `p_clothes_012` | Top1 命中，Top3 同为服饰运动 |

如果现场没有配置 Ark/VLM/embedding key，服务仍会降级到轻量视觉特征；演示时可以说明此时 Top-K 仍可用，但“图文共享空间语义匹配”能力需要 key 才能展示完整效果。
