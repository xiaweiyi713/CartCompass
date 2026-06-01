from __future__ import annotations

import re

from app.agent.grounding_guard import GroundingGuard


class LLMOutputSanitizer:
    def __init__(self, guard: GroundingGuard) -> None:
        self.guard = guard

    def should_flush_stream_segment(self, text: str) -> bool:
        if not text:
            return False
        if self.ends_with_unfinished_numeric_claim(text):
            return False
        return len(text) >= 32 or text[-1] in "。！？；;，,\n"

    def ends_with_unfinished_numeric_claim(self, text: str) -> bool:
        compact = text.rstrip()
        if not compact:
            return False
        return re.search(r"(?:¥|￥)?\d+(?:\.\d*)?$", compact) is not None

    def is_internal_review_segment(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        internal_markers = [
            "已核对",
            "输出规范",
            "已整理完成",
            "已梳理完成",
            "已补充完成",
            "严格依据给定",
            "给定商品",
            "给定参数",
            "给定资料",
            "未添加额外",
            "未新增额外",
            "无需额外信息",
            "无额外补充",
            "无额外编造",
            "最终推荐内容",
            "最终整理",
            "可按此整理",
            "按此输出",
            "推荐内容已补充",
            "推荐需求已收到",
            "当前需要为用户",
            "推荐话术",
            "我已经整理好",
            "所有内容均",
        ]
        return any(marker in compact for marker in internal_markers)

    def answer_start_index(self, text: str) -> int | None:
        markers = ["给你推荐", "为你推荐", "推荐如下", "以下推荐", "这几款", "1.", "1、", "一、"]
        indexes = [index for marker in markers if (index := text.find(marker)) >= 0]
        return min(indexes) if indexes else None

    def strip_internal_review_text(self, text: str) -> str:
        if not text:
            return text
        parts = re.split(r"(?<=[。！？；;\n])", text)
        cleaned = "".join(part for part in parts if part and not self.is_internal_review_segment(part)).strip()
        cleaned = self.strip_model_preamble(cleaned)
        return cleaned or text

    def strip_model_preamble(self, text: str) -> str:
        source_prefix = "以下信息来自本地商品库。"
        prefix = ""
        body = text.strip()
        if body.startswith(source_prefix):
            prefix = source_prefix
            body = body[len(source_prefix):].lstrip()
        answer_start = self.answer_start_index(body)
        if answer_start is not None and answer_start > 0:
            return (prefix + body[answer_start:]).strip()
        return text.strip()

    def is_safe_stream_segment(self, emitted_text: str, pending_text: str, products, constraints) -> bool:
        if not pending_text:
            return True
        return self.guard.is_safe(pending_text, products, constraints) and self.guard.is_safe(
            emitted_text + pending_text,
            products,
            constraints,
        )
