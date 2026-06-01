# API 文档

服务默认地址：`http://127.0.0.1:8000`

## 健康检查

`GET /api/health`

返回：

```json
{
  "ok": true,
  "product_count": 312,
  "llm_configured": false
}
```

## 商品

`GET /api/products`

参数：

- `query`：可选，搜索词。
- `category`：可选，类目过滤。
- `max_price`：可选，最高价。
- `limit`：默认 50，最大 100。

`GET /api/products/{product_id}`

商品字段包括：

- `product_id`、`title`、`brand`、`category`、`sub_category`
- `base_price`、`image_url`
- `skus`：包含 `sku_id`、`properties`、`price`、`image_url`、`image_source_url`
- `highlights`、`reason`
- `source_url`、`source_name`、`evidence`
- `average_rating`、`review_count`
- `match_score`：0-100 的推荐匹配分，搜索/推荐场景会填充。
- `match_reasons`：命中的类目、预算、偏好、来源、评论、SKU 等依据。
- `risk_flags`：预算临界、缺少公开来源、评论不足、评分偏低等注意点。

`GET /api/products/{product_id}/alternatives`

参数：

- `mode`：`cheaper`、`premium`、`brand_excluded`。
- `query`：可选，用于补充“平替”“更高端”“换品牌”等反馈语义。
- `excluded_brand`：可选，多值参数，额外排除品牌。
- `limit`：默认 3，最大 10。

返回同类替代商品。后端会复用结构化过滤 + BM25 + 向量 + 可信度 reranker，并在 `reason` 中解释平替、升级款或换品牌逻辑。

`GET /api/products/{product_id}/after_sale`

参数：

- `question`：可选，售后/退换货/保修相关问题。

返回：

- `answer`：基于 Demo 边界、商品来源和类目风险生成的谨慎回答。
- `policy`：结构化政策摘要，包含商品 ID、来源站点、来源链接和免责声明。

注意：本项目不模拟真实支付、物流、库存或平台售后承诺。售后回答不会编造七天无理由、运费险、保修期限等未落库事实。

## 聊天流式接口

`POST /api/chat/stream`

请求：

```json
{
  "session_id": "ios-demo",
  "message": "推荐适合油皮的防晒，200元以内，不要含酒精"
}
```

响应类型：`text/event-stream`

事件：

- `token`：流式文本片段。
- `products`：商品卡片数组。
- `compare`：结构化对比结果。
- `cart`：购物车状态。
- `plan`：预算套装方案，包含预算、总价、剩余预算、必需项、升级项和方案说明。
- `profile`：用户长期偏好，包含预算偏好、偏好特征、排除品牌、排除成分、肤质和常见场景。
- `error`：错误信息。
- `done`：本轮完成，包含 `trace_id`，可用于查看本轮 Agent 决策链路。

## 用户偏好

`GET /api/profile/{session_id}`

返回当前会话的长期偏好。偏好会持久化到 `server/storage/user_profiles.json`。

`DELETE /api/profile/{session_id}`

清除当前会话的长期偏好。

聊天中也支持：

- `记住我以后护肤品不要含酒精，我是油皮，预算200`
- `查看我的偏好`
- `清除我的偏好`

## 预算套装

聊天中支持预算组合推荐，例如：

```text
我1000元预算，下周去三亚，帮我配一套防晒和出行用品
```

后端会按场景拆分必需类目，从每个类目召回候选，在预算内组合商品，并返回 `plan` 事件和对应 `products` 事件。

## 反馈闭环

推荐后可继续输入：

- `第一款太贵了，有没有平替`
- `有没有更高端一点的`
- `换个品牌`
- `喜欢这款`
- `不喜欢这个`

Agent 会把反馈写入用户画像 `last_feedback`，并根据反馈类型即时调用替代品检索。

## 售后政策问答

推荐后可继续输入：

```text
第一款售后和保修怎么说
```

Agent 会返回通用 Demo 售后边界、商品来源提醒和类目风险点，并在有目标商品时附带商品卡。回答会明确说明真实退换货政策以来源平台和商家页面为准。

## 评测与可观测性

`GET /api/metrics`

返回商品数据质量、运行计数器、延迟分布和最近 Trace 摘要。

`GET /api/traces/{trace_id}`

返回单轮请求的 Trace，包括意图、约束解析、检索候选变化、Grounding Guard、SSE 输出等步骤。

`GET /admin/metrics`

返回本地 HTML Dashboard，适合答辩时展示系统健康状态、p50/p95/p99 延迟、图片检索延迟、SSE 首 token 延迟、主动澄清次数、购物车操作成功数和最近请求链路。

## 购物车

`POST /api/cart/add`

```json
{
  "session_id": "ios-demo",
  "product_id": "p_digital_003",
  "sku_id": "s_p_digital_003_5",
  "quantity": 1
}
```

`POST /api/cart/update`

```json
{
  "session_id": "ios-demo",
  "product_id": "p_digital_003",
  "sku_id": "s_p_digital_003_5",
  "quantity": 2
}
```

`DELETE /api/cart/{session_id}/{product_id}?sku_id=s_p_digital_003_5`

`GET /api/cart/{session_id}`

`DELETE /api/cart/{session_id}`

`POST /api/cart/checkout`

```json
{
  "session_id": "ios-demo",
  "address": "默认地址"
}
```

返回订单字段包括：

- `order_id`、`session_id`、`address`、`items`、`total_price`、`status`
- `post_purchase_recommendations`：订单后推荐商品数组，用于展示配件、补充购买或复购候选。

## 图片找货

`POST /api/image_search`

`multipart/form-data`：

- `file`：上传图片。
- `query`：可选文本，用于图文融合，例如上传商品图时同时输入“油皮防晒”或“黑色手机”。

返回融合排序后的商品数组。商品 `reason`、`match_score`、`match_reasons` 会说明 VLM 图像理解词、视觉相似度、文本筛选词和融合得分。

如果安装可选依赖 `sentence-transformers` 并设置 `SHOPGUIDE_CLIP_MODEL`，图片找货会启用 CLIP 语义图像 embedding 重排；未安装时服务自动降级到轻量视觉特征，并在 `risk_flags` / `match_reasons` 中说明 fallback 状态。

图片找货默认使用 OpenAI-compatible VLM 模型 `doubao-seed-2-0-lite-260428`；只要配置 `VISION_UNDERSTANDING_API_KEY` 或复用 `ARK_API_KEY`，后端会先调用 VLM，把图片理解为本地商品库可用的品类、子类目、关键词和属性；这些信号只参与召回/排序，不会生成商品事实。未配置 key 或调用失败时自动降级到 CLIP/轻量视觉 fallback。

本地调参可运行：

```bash
PYTHONPATH=server python3 server/scripts/probe_vision_understanding.py \
  --image server/static/product_images/p_anker_001_fc881685.jpg \
  --detail low \
  --max-image-side 768 \
  --max-tokens 240
```
