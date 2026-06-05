from __future__ import annotations

import re


class ProductQAService:
    def answer(self, message: str, product, rag: dict) -> str:
        compact = re.sub(r"[\s，。！？,.!?]", "", message.lower())
        prefix = f"我只基于商品库里的详情、FAQ、评论和来源回答。关于 {product.title[:28]}："
        if any(term in compact for term in ["差评", "低分", "缺点", "吐槽", "问题", "评论", "评价", "口碑"]):
            return f"{prefix}{self._review_summary(rag)}"
        if any(term in compact for term in ["来源", "真实", "可靠", "证据", "哪里来", "采集"]):
            return f"{prefix}{self._source_summary(product, rag)}"
        if any(term in compact for term in ["尺码", "什么码", "选码", "身高", "体重"]):
            return f"{prefix}{self._size_summary(product)}"
        if any(term in compact for term in ["规格", "版本", "颜色", "容量", "尺码", "怎么选", "如何选", "区别"]):
            return f"{prefix}{self._sku_summary(product)}"
        if any(term in compact for term in ["为什么", "推荐理由", "推荐它", "推荐这款", "为什么推荐"]):
            return f"{prefix}{self._recommendation_reason(product, rag)}"
        return f"{prefix}{self._attribute_answer(message, product, rag)}"

    def _review_summary(self, rag: dict) -> str:
        reviews = rag.get("user_reviews") if isinstance(rag.get("user_reviews"), list) else []
        if not reviews:
            return "这条商品数据暂时没有用户评论，所以我不能编造差评或口碑结论。建议把它当作来源信息较完整、但评论证据不足的候选。"
        low_reviews = [
            review
            for review in reviews
            if isinstance(review, dict) and float(review.get("rating") or 0) <= 3
        ]
        focus_reviews = low_reviews or [review for review in reviews if isinstance(review, dict)][:2]
        snippets = []
        for review in focus_reviews[:3]:
            rating = review.get("rating", "?")
            content = str(review.get("content") or "").strip()
            if content:
                snippets.append(f"{rating}星评论提到：{content[:58]}")
        if low_reviews:
            return f"共有 {len(reviews)} 条评论，其中 {len(low_reviews)} 条是3星及以下差评/低分评论。主要负反馈是" + "；".join(snippets) + "。"
        return f"共有 {len(reviews)} 条评论，暂未看到3星及以下差评。可参考的评论反馈是" + "；".join(snippets) + "。"

    def _source_summary(self, product, rag: dict) -> str:
        parts = [f"当前可信依据来自 {product.source_name}。"]
        if product.source_url:
            parts.append(f"商品库记录了公开来源链接：{product.source_url}。")
        faqs = rag.get("official_faq") if isinstance(rag.get("official_faq"), list) else []
        for faq in faqs:
            if not isinstance(faq, dict):
                continue
            answer = str(faq.get("answer") or "")
            if any(term in answer for term in ["公开页面采集", "robots.txt", "不包含登录态", "公开商品信息"]):
                parts.append(answer[:96])
                break
        if product.evidence:
            parts.append("可核验片段包括：" + "；".join(product.evidence[:2]) + "。")
        return "".join(parts)

    def _sku_summary(self, product) -> str:
        if not product.skus:
            return "这款商品没有可选规格，按默认商品信息购买即可。"
        price_values = [sku.price for sku in product.skus]
        property_names = sorted({str(name) for sku in product.skus for name in sku.properties.keys()})
        option_parts = []
        for name in property_names[:4]:
            values = list(dict.fromkeys(str(sku.properties.get(name)) for sku in product.skus if sku.properties.get(name)))
            if values:
                option_parts.append(f"{name}可选" + "、".join(values[:6]))
        image_count = sum(1 for sku in product.skus if sku.image_url)
        independent_image_count = sum(1 for sku in product.skus if sku.image_url and sku.image_url != product.image_url)
        text = (
            f"它有 {len(product.skus)} 个 SKU，价格约 {min(price_values):.0f}-{max(price_values):.0f} 元。"
            + "；".join(option_parts)
            + "。"
        )
        if independent_image_count:
            text += f"其中 {independent_image_count} 个规格带有独立规格图，切换规格时可以用对应真实图片辅助判断。"
        elif image_count:
            text += "每个规格都会关联真实商品图片；当前商品库没有独立颜色图时，会复用真实商品主图，不生成或涂改假图。"
        return text

    def _size_summary(self, product) -> str:
        sku_text = self._sku_summary(product)
        if product.category != "服饰运动":
            return "这不是服饰尺码型商品，商品库没有可用于身高、体重换算的尺码表证据。" + sku_text
        if not product.skus:
            return "商品库没有尺码 SKU，也没有可核验的身高、体重和版型对应尺码表；我不能编造尺码建议，建议以来源页尺码表为准。"
        return (
            "尺码建议只能基于商品库证据判断：当前商品库记录了 SKU 信息，但没有完整的身高、体重、版型尺码表。"
            + sku_text
            + "如果要按 175cm/70kg 精准选码，建议优先核对来源页尺码表、版型和试穿评论。"
        )

    def _recommendation_reason(self, product, rag: dict) -> str:
        reasons = []
        if product.reason:
            reasons.append(product.reason)
        reasons.extend(product.highlights[:2])
        faq_reason = self._matching_faq_answer(["推荐理由", "适合", "主要"], rag)
        if faq_reason:
            reasons.append(faq_reason)
        if product.average_rating:
            reasons.append(f"评论均分约 {product.average_rating}，评论数 {product.review_count} 条")
        return "推荐理由是：" + "；".join(list(dict.fromkeys(reasons))[:4]) + "。"

    def _attribute_answer(self, message: str, product, rag: dict) -> str:
        terms = self._qa_terms(message)
        evidence = self._evidence_for_terms(terms, rag)
        if evidence:
            return "我在商品知识里找到了这些相关证据：" + "；".join(evidence[:4]) + "。"
        if product.evidence:
            return "商品库没有直接命中你问的细节。已知可核验信息是：" + "；".join(product.evidence[:3]) + "。如果你要，我可以继续按这个条件重新筛选其他商品。"
        return "商品库没有足够证据回答这个细节，我不会编造。可以换成问评论、来源、规格，或让我重新筛选更匹配的商品。"

    def _qa_terms(self, message: str) -> list[str]:
        known_terms = [
            "酒精",
            "香精",
            "敏感肌",
            "油皮",
            "干皮",
            "防水",
            "防汗",
            "控油",
            "搓泥",
            "提亮",
            "续航",
            "拍照",
            "游戏",
            "快充",
            "防晒",
            "保湿",
            "无糖",
            "低糖",
            "咖啡因",
            "过敏",
        ]
        terms = [term for term in known_terms if term in message]
        if not terms:
            terms = [part for part in re.split(r"[，。！？,.!?\s]+", message) if len(part) >= 2][:3]
        return terms

    def _evidence_for_terms(self, terms: list[str], rag: dict) -> list[str]:
        if not terms:
            return []
        candidates: list[str] = []
        chunks = rag.get("retrieved_chunks") if isinstance(rag.get("retrieved_chunks"), list) else []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("chunk_text") or "")
            if any(term in text for term in terms):
                chunk_type = str(chunk.get("chunk_type") or "chunk")
                candidates.append(f"{chunk_type}片段：{text[:110]}")
        marketing = str(rag.get("marketing_description") or "")
        if any(term in marketing for term in terms):
            candidates.append(marketing[:120])
        faqs = rag.get("official_faq") if isinstance(rag.get("official_faq"), list) else []
        for faq in faqs:
            if not isinstance(faq, dict):
                continue
            text = f"{faq.get('question', '')} {faq.get('answer', '')}".strip()
            if any(term in text for term in terms):
                candidates.append(str(faq.get("answer") or text)[:120])
        reviews = rag.get("user_reviews") if isinstance(rag.get("user_reviews"), list) else []
        for review in reviews:
            if not isinstance(review, dict):
                continue
            content = str(review.get("content") or "")
            if any(term in content for term in terms):
                candidates.append(f"{review.get('rating', '?')}星评论：{content[:88]}")
        return list(dict.fromkeys(item for item in candidates if item))[:5]

    def _matching_faq_answer(self, terms: list[str], rag: dict) -> str | None:
        faqs = rag.get("official_faq") if isinstance(rag.get("official_faq"), list) else []
        for faq in faqs:
            if not isinstance(faq, dict):
                continue
            text = f"{faq.get('question', '')} {faq.get('answer', '')}"
            if any(term in text for term in terms):
                return str(faq.get("answer") or "").strip()[:110]
        return None
