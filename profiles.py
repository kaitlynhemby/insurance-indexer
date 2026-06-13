"""profiles.py — per-insurer process profiles (the per-company adaptation layer).

A profile captures the PROCESS axes that vary carrier-to-carrier — department
codes, the line-of-business → department taxonomy, admitted vs. surplus market
type, and an agency-code lookup — as config, so the SAME document routes
differently per insurer with no code change. router.py consumes the active
profile to enrich its routing decision; schema_agent.py `profile` authors them.

Pure module: data + deterministic lookups only (no model / pipeline imports),
so it's trivially unit-testable. The agency-code map is synthetic/mocked — in a
real deployment it would resolve against the insurer's agency-management system.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(ROOT, "config", "profiles")
ACTIVE = os.path.join(PROFILES_DIR, "active.json")

# Map an FNOL loss_type to a representative line_of_business for dept routing.
_LOSS_TYPE_TO_LOB = {
    "auto": "auto_liability",
    "property": "property",
    "liability": "general_liability",
    "workers_comp": "workers_comp",
    "other": "other",
}


def load_profile(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def profile_path(insurer_id: str) -> str:
    return os.path.join(PROFILES_DIR, f"{insurer_id}.json")


def list_profiles() -> List[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(PROFILES_DIR, "*.json"))):
        if os.path.basename(p) == "active.json":
            continue
        try:
            out.append(load_profile(p))
        except Exception:
            continue
    return out


def active_profile() -> Optional[dict]:
    """The currently activated profile, or None if none is active."""
    if os.path.exists(ACTIVE):
        try:
            return load_profile(ACTIVE)
        except Exception:
            return None
    return None


def activate(insurer_id: str) -> None:
    import shutil
    shutil.copyfile(profile_path(insurer_id), ACTIVE)


def lint_profile(p: dict) -> List[str]:
    """Return a list of validation problems (empty == valid)."""
    v: List[str] = []
    if not isinstance(p, dict):
        return ["profile is not a JSON object"]
    for key in ("insurer_id", "display_name", "market_type", "departments", "lob_taxonomy"):
        if key not in p:
            v.append(f"missing required key '{key}'")
    if p.get("market_type") not in ("admitted", "surplus", None):
        v.append("market_type must be 'admitted' or 'surplus'")
    depts = p.get("departments")
    if not isinstance(depts, list) or not depts:
        v.append("departments must be a non-empty list")
        depts = depts if isinstance(depts, list) else []
    tax = p.get("lob_taxonomy")
    if not isinstance(tax, dict) or not tax:
        v.append("lob_taxonomy must be a non-empty object")
    else:
        for lob, dept in tax.items():
            if dept not in depts:
                v.append(f"lob_taxonomy['{lob}'] = '{dept}' is not in departments {depts}")
    if "default_department" in p and p["default_department"] not in depts:
        v.append(f"default_department '{p['default_department']}' is not in departments")
    ac = p.get("agency_codes", {})
    if not isinstance(ac, dict):
        v.append("agency_codes must be an object (producer name -> code)")
    return v


def resolve_department(line_of_business: Optional[str], profile: dict) -> Optional[str]:
    """Map a line of business to this insurer's department code."""
    if not line_of_business:
        return profile.get("default_department")
    lob = _LOSS_TYPE_TO_LOB.get(line_of_business, line_of_business)
    return profile.get("lob_taxonomy", {}).get(lob, profile.get("default_department"))


def resolve_agency(producer_name: Optional[str], profile: dict) -> Optional[str]:
    """Mock agency-code resolution: case-insensitive containment match of the
    producer name against the profile's synthetic agency_codes map."""
    if not producer_name:
        return None
    pn = producer_name.casefold()
    for name, code in profile.get("agency_codes", {}).items():
        if name.casefold() in pn or pn in name.casefold():
            return code
    return None


def enrich(line_of_business: Optional[str], producer_name: Optional[str], profile: dict) -> dict:
    """The full per-insurer routing enrichment for a document."""
    return {
        "profile": profile.get("insurer_id"),
        "insurer": profile.get("display_name"),
        "market_type": profile.get("market_type"),
        "department": resolve_department(line_of_business, profile),
        "agency_code": resolve_agency(producer_name, profile),
    }
