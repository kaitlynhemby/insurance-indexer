#!/usr/bin/env python3
"""Unit checks for the authored-schema guards in schema_util.

Pure (no model, no network). Run: `python tests/test_schema_lint.py`.
Confirms the two known-good schemas pass and every unsupported construct is
caught — the safety net that keeps the config agent from activating a schema
that would break the pipeline.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schema_util as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")


def _base(**props):
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "TestType",
        "type": "object",
        "required": [],
        "properties": props or {"name": {"type": "string"}},
    }


def main() -> int:
    failures = []

    def check(label, cond):
        print(f"  [{'ok' if cond else 'FAIL'}] {label}")
        if not cond:
            failures.append(label)

    print("known-good schemas (must lint clean + round-trip):")
    for fn in ("coi.schema.json", "fnol.schema.json"):
        schema = S.load_schema(os.path.join(CONFIG, fn))
        viol = S.lint_authored_schema(schema)
        ok, why = S.roundtrip_ok(schema)
        check(f"{fn} no violations", viol == [])
        check(f"{fn} roundtrip_ok ({why})", ok)

    print("negative fixtures (each must produce >=1 violation):")
    negatives = {
        "$ref": _base(x={"$ref": "#/defs/y"}),
        "oneOf": _base(x={"oneOf": [{"type": "string"}, {"type": "number"}]}),
        "nested object": _base(x={"type": "object", "properties": {"y": {"type": "string"}}}),
        "array of scalars": _base(x={"type": "array", "items": {"type": "string"}}),
        "array item with nested array": _base(
            x={"type": "array", "items": {"type": "object", "properties": {"y": {"type": "array", "items": {"type": "string"}}}}}
        ),
        "non-draft-07": {**_base(), "$schema": "http://json-schema.org/draft-04/schema#"},
        "empty title": {**_base(), "title": ""},
        "bad x_natural_key": {**_base(name={"type": "string"}), "x_natural_key": "missing"},
        "required not in props": {**_base(name={"type": "string"}), "required": ["ghost"]},
    }
    for label, schema in negatives.items():
        check(f"{label} rejected", len(S.lint_authored_schema(schema)) >= 1)

    print("title collision:")
    coi = S.load_schema(os.path.join(CONFIG, "coi.schema.json"))
    clash = {**_base(), "title": coi["title"]}
    check("colliding title detected", S.title_collision(clash, CONFIG) is not None)
    check("unique title ok", S.title_collision(_base(), CONFIG) is None)
    # editing the same file is allowed via exclude_path
    check(
        "exclude_path lets a schema keep its own title",
        S.title_collision(coi, CONFIG, exclude_path=os.path.join(CONFIG, "coi.schema.json")) is None,
    )

    print("-" * 50)
    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("all schema-lint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
