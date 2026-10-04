"""Module B, part 2: a pure function of (rules, address stack and facts, as-of date) -> per-rule results."""

from datetime import date

COVERED, NOT_COVERED, UNKNOWN = "covered", "not_covered", "unknown"


def _year_test(yb: int | None, cutoff: str, on_or_before: bool) -> tuple[str, str]:
    d = date.fromisoformat(cutoff)
    label = f"{'on or before' if on_or_before else 'after'} {cutoff}"
    if yb is None:
        return UNKNOWN, f"coverage depends on construction date ({label}) and year built is not in the data"
    last_day = (d.month, d.day) == (12, 31)
    if on_or_before:
        if yb < d.year or (yb == d.year and last_day):
            return COVERED, f"built {yb}, {label}"
        if yb > d.year:
            return NOT_COVERED, f"built {yb}, not {label}"
    else:
        if yb > d.year:
            return COVERED, f"built {yb}, {label}"
        if yb < d.year or (yb == d.year and last_day):
            return NOT_COVERED, f"built {yb}, not {label}"
    return UNKNOWN, f"built in {yb}, the cutoff year; the certificate-of-occupancy date is needed to decide ({label})"


def coverage(rule: dict, facts: dict, as_of: str) -> tuple[str, list[str]]:
    c = rule.get("coverage_conditions") or {}
    yb, units = facts.get("year_built"), facts.get("units")
    states, reasons = [], []

    def add(state, reason):
        states.append(state)
        reasons.append(reason)

    if c.get("built_on_or_before"):
        add(*_year_test(yb, c["built_on_or_before"], True))
    if c.get("built_after"):
        add(*_year_test(yb, c["built_after"], False))
    if c.get("exempt_if_newer_than_years"):
        n = c["exempt_if_newer_than_years"]
        cutoff = date.fromisoformat(as_of).year - n
        if yb is None:
            add(UNKNOWN, f"buildings newer than {n} years are exempt and year built is not in the data")
        elif yb < cutoff:
            add(COVERED, f"built {yb}, older than the {n}-year new-construction exemption")
        elif yb > cutoff:
            add(NOT_COVERED, f"built {yb}, within the {n}-year new-construction exemption")
        else:
            add(UNKNOWN, f"built {yb}, at the edge of the {n}-year new-construction exemption")
    for key, op, word in (("min_units", lambda u, n: u >= n, "at least"), ("max_units", lambda u, n: u <= n, "at most")):
        if c.get(key) is not None:
            n = c[key]
            if facts.get("unit_conflict"):
                add(UNKNOWN, "unit count conflicts with assessor use description")
            elif units is None:
                add(UNKNOWN, f"covers buildings with {word} {n} units and the unit count is not in the data")
            elif op(units, n):
                add(COVERED, f"{units} units ({word} {n})")
            else:
                add(NOT_COVERED, f"{units} units, rule covers {word} {n}")
    if c.get("exemption_max_units") is not None:
        n = c["exemption_max_units"]
        if facts.get("unit_conflict"):
            add(UNKNOWN, "the recorded unit count conflicts with the assessor description; building versus parcel units need verification")
        elif units is None:
            add(UNKNOWN, f"an exemption applies to properties with {n} or fewer units and the unit count is not in the data")
        elif units > n:
            add(COVERED, f"{units} units, so the {n}-or-fewer-unit exemption cannot apply")
        else:
            if rule.get("unconditional_small_building_exemption"):
                add(NOT_COVERED, f"{units} units; the exemption for buildings with {n} or fewer units applies")
            else:
                add(UNKNOWN, f"{units} units; the small-property exemption may apply but depends on owner facts not in the data")
    for fact in c.get("facts_required") or []:
        if fact == "year_built" and yb is None and not any("year built" in r for r in reasons):
            add(UNKNOWN, "coverage depends on year built, which is not in the data")
        elif fact == "units" and units is None and not any("unit count" in r for r in reasons):
            add(UNKNOWN, "coverage depends on the unit count, which is not in the data")
        elif fact == "owner_type" and c.get("exemption_max_units") is None:
            add(UNKNOWN, "coverage depends on owner type; owner data is deliberately excluded from the sample")
        elif fact == "other":
            add(UNKNOWN, f"coverage depends on a building fact not in the data{': ' + c['text'] if c.get('text') else ''}")
        elif fact == "use_code" and not facts.get("use_code"):
            add(UNKNOWN, "coverage depends on use/type, which is not in the data")
    if rule.get("unit_level_exemptions"):
        add(UNKNOWN, "unit-level condo, subsidy, registration or rehabilitation facts are not in the assessor sample")
    if c.get("yields_to_local") and not facts.get("city_resolved", True):
        add(UNKNOWN, "legal city is unresolved; possible stricter local coverage cannot be decided from the mailing city")
    if NOT_COVERED in states:
        return NOT_COVERED, [r for s, r in zip(states, reasons) if s == NOT_COVERED]
    if UNKNOWN in states:
        return UNKNOWN, [r for s, r in zip(states, reasons) if s == UNKNOWN]
    return COVERED, reasons


def evaluate(rules: list[dict], record: dict, as_of: str) -> list[dict]:
    date.fromisoformat(as_of)
    stack = record["stack"]
    in_stack = {stack.get("state"), stack.get("city")} - {None}
    facts = {k: record.get(k) for k in ("year_built", "units", "use_code", "use_description", "unit_conflict")}
    facts["city_resolved"] = bool(stack.get("city"))
    results = []
    for rule in rules:
        if rule["jurisdiction"] not in in_stack:
            continue
        failed_on = rule.get("failed_date")
        if rule["status"] == "failed" and (not failed_on or as_of >= failed_on):
            continue
        if rule.get("end_date") and as_of > rule["end_date"]:
            continue
        cov, reasons = coverage(rule, facts, as_of)
        if cov == NOT_COVERED:
            continue
        where = "Statewide rule" if rule["level"] == "state" else f"Local rule for {rule['jurisdiction']}"
        why = "; ".join(reasons)
        eff = rule.get("effective_date")
        if rule["status"] == "pending" or (rule["status"] == "failed" and failed_on and as_of < failed_on) or (
                rule.get("enacted_date") and as_of < rule["enacted_date"]):
            result, expl = "pending", f"{where}: a pending bill or proposal, not law as of {as_of}."
        elif eff and as_of < eff:
            result, expl = "not_yet_effective", f"{where}: enacted, takes effect {eff} (after {as_of})."
        elif rule.get("in_force_by") and as_of < rule["in_force_by"]:
            result, expl = "unknown", f"{where}: adopted but exact publication-dependent commencement day is not verified."
        elif not eff and rule.get("historical_start_unverified") and as_of < rule["retrieved_at"][:10]:
            result, expl = "unknown", f"{where}: operative at capture, but historical commencement is not evidenced for {as_of}."
        elif cov == UNKNOWN:
            result, expl = "unknown", f"{where}: {why}."
        else:
            result, expl = "applies", f"{where} in force{' since ' + eff if eff else ''}" + (f"; {why}." if why else ".")
        if result in ("pending", "not_yet_effective") and cov == UNKNOWN:
            expl += f" Coverage also uncertain: {why}."
        if rule.get("uncertainty_note"):
            expl += " Evidence limitation: " + rule["uncertainty_note"]
        if any((rule.get("coverage_conditions") or {}).get(k) for k in (
                "built_on_or_before", "built_after", "exempt_if_newer_than_years")):
            expl += " Assessor year is a construction-year proxy, not a certificate-of-occupancy date; cutoff-year cases remain unknown."
        if rule.get("effective_date_derivation"):
            expl += " Effective date derived from sourced commencement rule; see audit evidence."
        results.append({"rule": rule, "result": result, "explanation": expl,
                        "conflict_flag": bool(rule.get("conflict_flag")) and rule["level"] == "city"})

    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["rule"]["category"], []).append(r)
    for items in by_cat.values():
        local = [r for r in items if r["rule"]["level"] == "city"]
        local_applies = [r for r in local if r["result"] == "applies" and
                         (r["rule"].get("caps_rent") if r["rule"]["category"] == "rent_increase_limits" else True)]
        local_unknown = [r for r in local if r["result"] == "unknown" and
                         (r["rule"].get("caps_rent") if r["rule"]["category"] == "rent_increase_limits" else True)]
        for r in items:
            rule = r["rule"]
            if rule["level"] != "state":
                continue
            yields = (rule.get("coverage_conditions") or {}).get("yields_to_local")
            if yields and r["result"] == "applies" and local_applies:
                names = ", ".join(l["rule"]["citation"] for l in local_applies)
                r["result"] = "superseded"
                r["explanation"] += f" The stricter local rule governs ({names}); state rule superseded."
            elif yields and r["result"] == "applies" and local_unknown:
                r["result"] = "unknown"
                r["explanation"] += " Statewide rule yields to local rules where they cover the building; local coverage is unknown, so which rule governs remains unknown."
            if (r["result"] in ("pending", "not_yet_effective") or rule.get("possible_local_preemption")) and local_applies:
                r["conflict_flag"] = True
                r["explanation"] += " Possible conflict with the in-force local rule; flagged for human review."
                for l in local_applies:
                    l["conflict_flag"] = True
                    l["explanation"] += f" A {r['result'].replace('_', ' ')} state rule ({rule['citation']}) covers the same subject; possible conflict, flagged for human review."
    return [
        {"team_rule_id": r["rule"]["team_rule_id"], "result": r["result"], "explanation": r["explanation"], "conflict_flag": r["conflict_flag"]}
        for r in results
    ]


def lookups(rules: list[dict], stacks: dict[str, dict], as_of: str) -> dict:
    return {"as_of": as_of, "lookups": {aid: evaluate(rules, rec, as_of) for aid, rec in stacks.items()}}
