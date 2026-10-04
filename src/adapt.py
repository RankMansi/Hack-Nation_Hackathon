"""Internal extracted rules -> records matching schema/rule_record.schema.json."""

from .config import CATEGORIES, DEFAULT_AS_OF, JURISDICTIONS

PREDICATES = ["built_on_or_before", "built_after", "exempt_if_newer_than_years", "min_units", "max_units", "exemption_max_units", "facts_required", "yields_to_local"]


def schema_status(rule: dict, as_of: str = DEFAULT_AS_OF) -> str:
    if rule["status"] == "failed":
        return "failed"
    if rule["status"] == "pending":
        return "pending"
    eff = rule.get("effective_date")
    return "not_yet_effective" if eff and as_of < eff else "in_force"


def level_of(jurisdiction: str) -> str:
    return "city" if "," in jurisdiction else "state"


def state_of(jurisdiction: str) -> str:
    return jurisdiction.split(", ")[-1]


def to_schema(rules: list[dict]) -> list[dict]:
    rules = sorted(rules, key=lambda r: (JURISDICTIONS.index(r["jurisdiction"]), CATEGORIES.index(r["category"]), r["citation"]))
    out = []
    for i, r in enumerate(rules, 1):
        coverage = {k: r.get(k) for k in PREDICATES}
        coverage["text"] = r.get("coverage_text")
        out.append({
            "team_rule_id": f"r-{i:04d}",
            "jurisdiction": r["jurisdiction"],
            "level": level_of(r["jurisdiction"]),
            "category": r["category"],
            "status": schema_status(r),
            "title": r["title"],
            "requirement": r["summary"],
            "key_value": r.get("key_value"),
            "caps_rent": bool(r.get("caps_rent")),
            "coverage_conditions": coverage,
            "exemptions": r.get("exemption_note"),
            "overrides": [],
            "interaction": None,
            "effective_date": r.get("effective_date"),
            "effective_date_evidence": r.get("effective_date_evidence"),
            "citation": r["citation"],
            "source_doc_id": r["source_doc_id"],
            "source_url": r["source_url"],
            "retrieved_at": r.get("retrieved_at"),
            "also_found_in": r.get("also_found_in", []),
            "incoming": r.get("incoming", False),
            "quoted_span": r["quote"],
            "penalty": r.get("penalty"),
            "confidence": None,
            "conflict_flag": False,
            "conflict_note": None,
        })

    for s in out:
        if s["level"] != "state":
            continue
        locals_ = [c for c in out if c["level"] == "city" and c["category"] == s["category"] and state_of(c["jurisdiction"]) == s["jurisdiction"]]
        if s["coverage_conditions"]["yields_to_local"] and locals_:
            s["overrides"] = [c["team_rule_id"] for c in locals_]
            s["interaction"] = "Yields to the listed local rules where they cover the building (state rule becomes superseded)."
            for c in locals_:
                c["overrides"].append(s["team_rule_id"])
                c["interaction"] = "Supersedes the listed state rule where this local rule covers the building."
        in_force_locals = [c for c in locals_ if c["status"] == "in_force"]
        if s["status"] in ("pending", "not_yet_effective") and in_force_locals:
            names = ", ".join(sorted({c["jurisdiction"] for c in in_force_locals}))
            s["conflict_flag"] = True
            s["conflict_note"] = f"{s['status'].replace('_', ' ')} state rule in the same category as in-force local rules ({names}); flagged for human review."
            for c in in_force_locals:
                c["conflict_flag"] = True
                c["conflict_note"] = f"State rule {s['team_rule_id']} ({s['citation']}) is {s['status'].replace('_', ' ')} in the same category; possible conflict or preemption, flagged for human review."
    return out
