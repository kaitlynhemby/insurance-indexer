"""schema_util.py — drive everything off config/active.schema.json.

The extractor and verifier never hardcode field names. They walk the *active*
canonical schema, so dropping fnol.schema.json over active.schema.json
re-targets the entire pipeline with no code change — the live config-swap proof.

Supported schema shapes (draft-07): an object of scalar leaves, plus optional
arrays-of-objects (e.g. COI `coverages`). FNOL is all scalar leaves.
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List, Tuple

# ----- classification ------------------------------------------------------


def classify(leaf: dict) -> str:
    """Map a scalar leaf schema to a normalization 'kind'."""
    if "const" in leaf:
        return "const"
    if "enum" in leaf:
        return "enum"
    if leaf.get("format") == "date":
        return "date"
    t = leaf.get("type")
    if t in ("number", "integer"):
        return "number"
    return "string"


def _is_array_of_objects(prop: dict) -> bool:
    return prop.get("type") == "array" and prop.get("items", {}).get("type") == "object"


def load_schema(path: str) -> dict:
    with open(path, "r") as fh:
        return json.load(fh)


# ----- envelope schema (for `claude -p --json-schema`) ---------------------

_WRAPPER_REQUIRED = ["value", "confidence", "source", "needs_review"]


def _value_schema(kind: str) -> dict:
    if kind == "number":
        return {"type": ["number", "null"]}
    return {"type": ["string", "null"]}


def _wrapper(kind: str) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": _WRAPPER_REQUIRED,
        "properties": {
            "value": _value_schema(kind),
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source": {
                "type": "object",
                "additionalProperties": False,
                "required": ["page", "text_span"],
                "properties": {
                    "page": {"type": "integer"},
                    "text_span": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                },
            },
            "needs_review": {"type": "boolean"},
        },
    }


def envelope_schema(active: dict) -> dict:
    """Transform the active schema into the structured-output schema the model
    must fill: every scalar leaf becomes an extraction-envelope wrapper."""
    props: Dict[str, dict] = {}
    for name, prop in active.get("properties", {}).items():
        if _is_array_of_objects(prop):
            item_props = {
                sub: _wrapper(classify(subschema))
                for sub, subschema in prop["items"].get("properties", {}).items()
            }
            props[name] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(item_props.keys()),
                    "properties": item_props,
                },
            }
        else:
            props[name] = _wrapper(classify(prop))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props.keys()),
        "properties": props,
    }


# ----- pulling the plain .value layer back out -----------------------------


def value_layer(envelope: dict, active: dict) -> dict:
    """Collapse an extraction envelope to plain values (for jsonschema
    validation in Gate 2 and accuracy compare in Gate 6). Null/omitted values
    are dropped so 'required but null' surfaces as a real schema violation."""
    out: Dict = {}
    for name, prop in active.get("properties", {}).items():
        if name not in envelope or envelope[name] is None:
            continue
        if _is_array_of_objects(prop):
            rows = []
            for item in envelope[name]:
                row = {}
                for sub in prop["items"].get("properties", {}):
                    cell = item.get(sub)
                    if cell and cell.get("value") is not None:
                        row[sub] = cell["value"]
                rows.append(row)
            out[name] = rows
        else:
            cell = envelope[name]
            if isinstance(cell, dict) and cell.get("value") is not None:
                out[name] = cell["value"]
    return out


# ----- iterating every populated leaf wrapper (Gates 1/3/4) ----------------


def iter_fields(envelope: dict, active: dict) -> Iterator[Tuple[str, dict, str]]:
    """Yield (path, wrapper, kind) for every leaf wrapper present in envelope."""
    for name, prop in active.get("properties", {}).items():
        if name not in envelope or envelope[name] is None:
            continue
        if _is_array_of_objects(prop):
            sub_kinds = {
                sub: classify(s)
                for sub, s in prop["items"].get("properties", {}).items()
            }
            for idx, item in enumerate(envelope[name]):
                if not isinstance(item, dict):
                    continue
                for sub, wrapper in item.items():
                    if sub in sub_kinds and isinstance(wrapper, dict):
                        yield (f"{name}[{idx}].{sub}", wrapper, sub_kinds[sub])
        else:
            yield (name, envelope[name], classify(prop))


def required_paths(active: dict) -> List[str]:
    """Top-level required field names (for human-readable diagnostics)."""
    return list(active.get("required", []))
