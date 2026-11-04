"""Read a JSON object out of a model's final message.

Open models often wrap JSON in code fences or put reasoning before it, so extraction is tolerant.
Validation against the output schema stays strict.
"""

from __future__ import annotations

import json
import re
from typing import Any

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove ``<think>`` blocks, including a block whose opening tag was cut off."""
    return _OPEN_THINK.sub("", _THINK.sub("", text)).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """Return the JSON object in ``text``, or raise ``ValueError``."""
    body = strip_reasoning(text)
    fenced = _FENCE.search(body)
    if fenced:
        body = fenced.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the reply holds no JSON object")
    try:
        value = json.loads(body[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the reply is not valid JSON: {exc.msg} at character {exc.pos}") from exc
    if not isinstance(value, dict):
        raise ValueError("the reply is not a JSON object")
    return value
