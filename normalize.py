"""normalize.py — deterministic value normalization, shared by builder and grader.

goal.md mandates: dates -> ISO YYYY-MM-DD (docs print MM/DD/YYYY); limits ->
integers (strip $ and commas). Keeping this in one place means the extractor
normalizes and the verifier re-derives the SAME way, so accuracy and grounding
never disagree over formatting.
"""
from __future__ import annotations

import re
from typing import List, Optional

_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# A currency-ish amount: optional $, digits with thousands separators.
_AMOUNT_RE = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.\d{2})?")


def norm_str(value) -> str:
    """Whitespace-collapsed, stripped string form (case preserved)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def to_iso_date(value) -> Optional[str]:
    """MM/DD/YYYY (or already-ISO) -> YYYY-MM-DD. None if not a single date."""
    if value is None:
        return None
    s = str(value).strip()
    m = _ISO_RE.search(s)
    if m and s == m.group(0):
        return m.group(0)
    m = _DATE_RE.search(s)
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
    return None


def find_iso_dates(text: str) -> List[str]:
    """Every MM/DD/YYYY (and ISO) date in text, normalized to ISO."""
    out: List[str] = []
    for mm, dd, yyyy in _DATE_RE.findall(text or ""):
        out.append(f"{yyyy}-{int(mm):02d}-{int(dd):02d}")
    for yyyy, mm, dd in _ISO_RE.findall(text or ""):
        out.append(f"{yyyy}-{mm}-{dd}")
    return out


def parse_amount(value) -> Optional[int]:
    """'$2,000,000' / '2000000' / 2000000.0 -> 2000000. None if not numeric."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = _AMOUNT_RE.search(str(value))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def find_amounts(text: str) -> List[int]:
    """Every currency-ish integer amount in text."""
    out: List[int] = []
    for m in _AMOUNT_RE.finditer(text or ""):
        out.append(int(m.group(1).replace(",", "")))
    return out


def normalize_value(value, kind: str):
    """Normalize a raw extracted value by its schema-derived `kind`.

    kind in {'date', 'number', 'string', 'enum', 'const'}.
    """
    if value is None:
        return None
    if kind == "date":
        return to_iso_date(value) or value
    if kind == "number":
        n = parse_amount(value)
        return n if n is not None else value
    # string / enum / const: trim whitespace only (enums are produced canonical)
    return norm_str(value)
