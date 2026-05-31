# 商品数据补充流水线

这个目录实现“合规轻量采集器”：从配置文件读取公开商品 URL，低频访问并检查 `robots.txt`，采集基础字段，再清洗成 ShopGuide 后端可直接检索的商品结构。

## 推荐流程

1. 复制并编辑采集配置：

```bash
cp server/data_pipeline/configs/crawl_targets.example.yaml server/data_pipeline/configs/crawl_targets.yaml
```

2. 把允许公开访问的商品页 URL 填到 `urls`，按目标站点调整 `selectors`。

3. 静态页面采集、清洗：

```bash
PYTHONPATH=server python3 server/scripts/crawl_products.py \
  --config server/data_pipeline/configs/crawl_targets.yaml \
  --raw-output server/data_pipeline/output/products_raw.json \
  --clean-output server/data_pipeline/output/products_clean.json
```

4. 导入 SQLite：

```bash
PYTHONPATH=server python3 server/scripts/crawl_products.py \
  --mode ingest-only \
  --clean-output server/data_pipeline/output/products_clean.json
```

也可以采集后直接导入：

```bash
PYTHONPATH=server python3 server/scripts/crawl_products.py \
  --config server/data_pipeline/configs/crawl_targets.yaml \
  --ingest
```

## 输出格式

- `products_raw.json`：爬虫原始字段，保留来源、标题、价格文本、描述、图片 URL、商品链接等。
- `products_clean.json`：清洗后的 ShopGuide 商品结构，包含 `product_id/title/brand/category/sub_category/base_price/skus/rag_knowledge/attributes`。
- SQLite 导入会写入 `products` 和 `product_vectors`，不删除原始比赛数据。

## 合规边界

采集器只做公开页面、小规模、低频请求。不要加入验证码绕过、登录态抓取、代理池、指纹伪装、反爬绕过或评论区个人信息采集。

动态页面可以用：

```bash
PYTHONPATH=server python3 server/scripts/crawl_products.py --mode dynamic --config ...
```

动态采集需要额外安装 Playwright，只建议在目标页面公开允许访问但由 JavaScript 渲染时使用。

## 已验证真实来源

Anker 官方商城商品页已经验证可采集：`robots.txt` 未禁止 `/products/...`，并提供产品 sitemap 和标准 `schema.org/Product` JSON-LD。

```bash
PYTHONPATH=server python3 server/scripts/crawl_products.py \
  --config server/data_pipeline/configs/crawl_targets.anker.yaml \
  --raw-output server/data_pipeline/output/anker/products_raw.json \
  --clean-output server/data_pipeline/output/anker/products_clean.json \
  --product-prefix p_anker \
  --usd-cny-rate 6.8
```

Anker US 原站价格币种是 `USD`。清洗层会保留 `source_price`、`source_price_currency`、`exchange_rate_to_cny`，同时把 `base_price` 换算为人民币并设置 `price_currency: "CNY"`，这样现有推荐、购物车和 iOS UI 可以继续按人民币价格工作。本次导入使用 `1 USD = 6.8 CNY`。
