"""Turn documented JSON examples into JSON schemas."""

from __future__ import annotations

import json
import re
from typing import Any

ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
ELLIPSIS_LINE = re.compile(r"^[ \t]*\.\.\.[ \t]*,?[ \t]*$", re.MULTILINE)
LEADING_ZERO_NUMBER = re.compile(r"(?<=[:\[,\s])0(\d+)(?=\s*[,}\]\s])")
TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def load_example(text: str) -> Any | None:
    """Parse an example body, tolerating the `...` placeholders and typos found in the docs.

    Returns None when the text is empty or cannot be parsed even after repair.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    repaired = ELLIPSIS_LINE.sub("", text)
    repaired = LEADING_ZERO_NUMBER.sub(r"0.\1", repaired)
    repaired = TRAILING_COMMA.sub(r"\1", repaired)
    try:
        return json.loads(repaired)
    except ValueError:
        return None


def infer_schema(value: Any) -> dict[str, Any]:
    if value is None:
        return {"nullable": True}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string", "format": "date-time"} if ISO_DATETIME.match(value) else {"type": "string"}
    if isinstance(value, list):
        items: dict[str, Any] = {}
        for item in value:
            items = merge_schemas(items, infer_schema(item))
        return {"type": "array", "items": items}
    if isinstance(value, dict):
        schema: dict[str, Any] = {"type": "object"}
        if value:
            schema["properties"] = {key: infer_schema(child) for key, child in value.items()}
        return schema
    return {}


def merge_schemas(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Combine two schemas inferred from different examples of the same thing."""
    if not first:
        return second
    if not second or first == second:
        return first

    first_type, second_type = first.get("type"), second.get("type")
    if first_type is None or second_type is None:
        # A bare `null` example only tells us the value may be null.
        typed = first if first_type else second
        return {**typed, "nullable": True}

    nullable = first.get("nullable") or second.get("nullable")
    if first_type == second_type == "object":
        properties = dict(first.get("properties", {}))
        for name, child in second.get("properties", {}).items():
            properties[name] = merge_schemas(properties.get(name, {}), child)
        merged: dict[str, Any] = {"type": "object"}
        if properties:
            merged["properties"] = properties
    elif first_type == second_type == "array":
        merged = {"type": "array", "items": merge_schemas(first.get("items", {}), second.get("items", {}))}
    elif {first_type, second_type} == {"integer", "number"}:
        merged = {"type": "number"}
    elif first_type == second_type:
        merged = {key: value for key, value in first.items() if key != "nullable"}
        if first.get("format") != second.get("format"):
            merged.pop("format", None)
    else:
        merged = {key: value for key, value in first.items() if key != "nullable"}
    if nullable:
        merged["nullable"] = True
    return merged
