"""schema_util.py — drive everything off config/active.schema.json.

The extractor and verifier never hardcode field names. They walk the *active*
canonical schema, so dropping fnol.schema.json over active.schema.json
re-targets the entire pipeline with no code change — the live config-swap proof.

Supported schema shapes (draft-07): an object of scalar leaves, plus optional
arrays-of-objects (e.g. COI `coverages`). FNOL is all scalar leaves.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, Iterator, List, Optional, Tuple

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


# ----- guarding model-authored schemas ------------------------------------
# An agent (schema_agent.py) authors new schemas. These functions are the
# formal statement of the shape the pipeline above supports — they keep a
# generated schema from silently breaking classify()/envelope_schema()/
# value_layer()/iter_fields(). Nothing is activated unless it passes them.

_UNSUPPORTED_KEYWORDS = (
    "$ref", "oneOf", "anyOf", "allOf", "if", "then", "else", "not",
    "patternProperties", "dependencies", "dependentSchemas",
)
_SCALAR_TYPES = ("string", "number", "integer")


def _leaf_violations(label: str, leaf: dict) -> List[str]:
    out = []
    for kw in _UNSUPPORTED_KEYWORDS:
        if kw in leaf:
            out.append(f"{label}: unsupported keyword '{kw}'")
    if "const" in leaf or "enum" in leaf:
        return out  # const/enum leaves are fine — classify() handles them
    t = leaf.get("type")
    if t is None:
        out.append(f"{label}: leaf needs a 'type' (or const/enum)")
    elif t not in _SCALAR_TYPES:
        out.append(f"{label}: unsupported leaf type {t!r} (use string/number/integer, enum, or const)")
    return out


def lint_authored_schema(schema: dict) -> List[str]:
    """Return a list of shape violations (empty == valid). The supported shape:
    draft-07 object of scalar leaves + at most one level of array-of-objects of
    scalar leaves, plus optional x_natural_key naming a scalar field."""
    if not isinstance(schema, dict):
        return ["schema is not a JSON object"]
    v: List[str] = []
    if schema.get("$schema") != "http://json-schema.org/draft-07/schema#":
        v.append("$schema must be 'http://json-schema.org/draft-07/schema#'")
    if not isinstance(schema.get("title"), str) or not schema.get("title", "").strip():
        v.append("title must be a non-empty string")
    if schema.get("type") != "object":
        v.append("top-level type must be 'object'")
    for kw in _UNSUPPORTED_KEYWORDS:
        if kw in schema:
            v.append(f"(root): unsupported keyword '{kw}'")

    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        v.append("schema must have a non-empty 'properties' object")
        props = props if isinstance(props, dict) else {}

    for name, prop in props.items():
        if not isinstance(prop, dict):
            v.append(f"{name}: property must be an object")
            continue
        if _is_array_of_objects(prop):
            for kw in _UNSUPPORTED_KEYWORDS:
                if kw in prop or kw in prop.get("items", {}):
                    v.append(f"{name}: unsupported keyword '{kw}' in array")
            item_props = prop.get("items", {}).get("properties")
            if not isinstance(item_props, dict) or not item_props:
                v.append(f"{name}: array items must be objects with 'properties'")
            else:
                for sub, leaf in item_props.items():
                    if not isinstance(leaf, dict):
                        v.append(f"{name}[].{sub}: must be an object")
                    elif leaf.get("type") in ("array", "object") or "properties" in leaf or "items" in leaf:
                        v.append(f"{name}[].{sub}: nested arrays/objects inside an array item are not supported")
                    else:
                        v += _leaf_violations(f"{name}[].{sub}", leaf)
        elif prop.get("type") == "array":
            v.append(f"{name}: arrays must be arrays-of-objects (array-of-scalars is not supported)")
        elif prop.get("type") == "object" or "properties" in prop:
            v.append(f"{name}: nested objects are not supported (scalar leaves + one array-of-objects only)")
        else:
            v += _leaf_violations(name, prop)

    nk = schema.get("x_natural_key")
    if nk is not None:
        if nk not in props:
            v.append(f"x_natural_key '{nk}' must name a top-level property")
        elif _is_array_of_objects(props.get(nk, {})):
            v.append(f"x_natural_key '{nk}' must be a scalar field, not an array")

    for r in schema.get("required", []):
        if r not in props:
            v.append(f"required field '{r}' is not in properties")
    return v


def _synthetic_envelope(schema: dict) -> dict:
    """A minimal filled envelope mirroring the schema, for the round-trip check."""
    def cell(kind: str) -> dict:
        val = 0 if kind == "number" else ("2026-01-01" if kind == "date" else "x")
        return {"value": val, "confidence": 0.9, "source": {"page": 1, "text_span": "x"}, "needs_review": False}

    env: Dict = {}
    for name, prop in schema.get("properties", {}).items():
        if _is_array_of_objects(prop):
            env[name] = [{sub: cell(classify(s)) for sub, s in prop["items"].get("properties", {}).items()}]
        else:
            env[name] = cell(classify(prop))
    return env


def roundtrip_ok(schema: dict) -> Tuple[bool, str]:
    """Behavioral proof the schema won't break the pipeline: build a synthetic
    envelope and run envelope_schema/value_layer/iter_fields with no exception,
    and confirm every top-level field is reachable via iter_fields."""
    try:
        env = _synthetic_envelope(schema)
        envelope_schema(schema)
        value_layer(env, schema)
        seen = {path.split("[")[0].split(".")[0] for path, _w, _k in iter_fields(env, schema)}
        missing = [f for f in schema.get("properties", {}) if f not in seen]
        if missing:
            return False, f"fields not reachable via iter_fields: {missing}"
        return True, "ok"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{type(exc).__name__}: {exc}"


def title_collision(schema: dict, config_dir: str, exclude_path: Optional[str] = None) -> Optional[str]:
    """Path of an existing (non-active) schema sharing this title, or None.
    The verifier keys schemas by title globally, so a duplicate would mis-route
    existing records. exclude_path skips the file we're (re)writing."""
    title = schema.get("title")
    if not title:
        return None
    for p in glob.glob(os.path.join(config_dir, "*.schema.json")):
        if os.path.basename(p) == "active.schema.json":
            continue
        if exclude_path and os.path.abspath(p) == os.path.abspath(exclude_path):
            continue
        try:
            if load_schema(p).get("title") == title:
                return p
        except Exception:
            continue
    return None
