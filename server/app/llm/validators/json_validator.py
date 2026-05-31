from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError


def extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def parse_model_json(text: str, schema: type[BaseModel]) -> BaseModel | None:
    payload = extract_json_object(text)
    if payload is None:
        return None
    try:
        return schema.model_validate(payload)
    except ValidationError:
        return None

