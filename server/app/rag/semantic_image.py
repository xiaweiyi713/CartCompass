from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class SemanticImageScore:
    score: float | None
    provider: str
    available: bool


class OptionalSemanticImageEncoder:
    """Optional CLIP-compatible image encoder.

    The base project must run without heavyweight ML dependencies. If
    sentence-transformers with a CLIP model is installed, this adapter enables
    semantic image embedding automatically. Otherwise callers get an explicit
    unavailable signal and can fall back to lightweight visual features.
    """

    def __init__(self) -> None:
        self.provider = os.getenv("SHOPGUIDE_VISION_PROVIDER", "sentence_transformers_clip")
        self.model_name = os.getenv("SHOPGUIDE_CLIP_MODEL", "clip-ViT-B-32")
        self._model: Any | None = None
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        self._ensure_model()
        return bool(self._available)

    def image_similarity(self, left: Image.Image, right: Image.Image) -> SemanticImageScore:
        self._ensure_model()
        if not self._available or self._model is None:
            return SemanticImageScore(score=None, provider=self.provider, available=False)
        try:
            left_vec = self._encode_image(left)
            right_vec = self._encode_image(right)
        except Exception:  # noqa: BLE001 - optional model fallback should be resilient.
            return SemanticImageScore(score=None, provider=self.provider, available=False)
        return SemanticImageScore(
            score=max(0.0, min(1.0, (self._cosine(left_vec, right_vec) + 1.0) / 2.0)),
            provider=self.provider,
            available=True,
        )

    def _ensure_model(self) -> None:
        if self._available is not None:
            return
        if self.provider != "sentence_transformers_clip":
            self._available = False
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
            self._available = True
        except Exception:  # noqa: BLE001 - missing optional deps/model should not break app startup.
            self._model = None
            self._available = False

    def _encode_image(self, image: Image.Image) -> list[float]:
        if self._model is None:
            return []
        vector = self._model.encode(image.convert("RGB"), convert_to_numpy=False)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
