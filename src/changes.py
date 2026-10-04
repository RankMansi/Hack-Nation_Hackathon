"""Module C: each change test is `apply` at one or two dates, then a difference. No hand-listed addresses."""

import json
from datetime import date, timedelta

from .apply import evaluate
from .config import CHANGE_TESTS, DEFAULT_AS_OF

JUR_CODES = {
    "CA": "CA", "NJ": "NJ", "MA": "MA",
    "LA": "Los Angeles, CA", "SF": "San Francisco, CA", "SD": "San Diego, CA", "BRK": "Berkeley, CA", "SA": "Santa Ana, CA",
    "JC": "Jersey City, NJ", "HOB": "Hoboken, NJ", "NWK": "Newark, NJ", "BOS": "Boston, MA", "CAM": "Cambridge, MA",
}
CAT_CODES = {
    "ALG": "algorithmic_rent_setting", "RENT": "rent_increase_limits", "JC": "just_cause_eviction",
    "DEP": "security_deposits", "FEE": "application_screening_fees", "SCR": "screening_restrictions",
}


def match_rules(key_id: str, rules: list[dict]) -> tuple[str, str, list[dict]]:
    """Translate a test-file rule id like 'HOB-ALG-01' or 'MA-ALG-P1' into our extracted rules."""
    jur_code, cat_code, n = key_id.split("-")
    jur, cat = JUR_CODES[jur_code], CAT_CODES[cat_code]
    found = [r for r in rules if r["jurisdiction"] == jur and r["category"] == cat]
    if n.startswith("P"):
        found = [r for r in found if r["status"] in ("pending", "failed")]
    else:
        found = [r for r in found if r["status"] not in ("pending", "failed")]
    return jur, cat, found


def results_at(rules: list[dict], stacks: dict, as_of: str, ids: set[str]) -> dict[str, dict[str, dict]]:
    out = {}
    for aid, rec in stacks.items():
        res = {r["team_rule_id"]: r for r in evaluate(rules, rec, as_of) if r["team_rule_id"] in ids}
        if res:
            out[aid] = res
    return out


def in_city(stacks: dict, jur: str) -> list[str]:
    return sorted(a for a, s in stacks.items() if s["stack"]["city"] == jur)


def as_of_test(t: dict, rules: list[dict], stacks: dict) -> dict:
    matched = [r for kid in t["rule_ids"] for r in match_rules(kid, rules)[2]]
    ids = {r["team_rule_id"] for r in matched}
    before = results_at(rules, stacks, t["as_of_before"], ids)
    after = results_at(rules, stacks, t["as_of_after"], ids)
    affected = sorted(a for a in set(before) | set(after) if {k: v["result"] for k, v in before.get(a, {}).items()} != {k: v["result"] for k, v in after.get(a, {}).items()})
    counts = lambda res: {s: sum(1 for a in res.values() for v in a.values() if v["result"] == s) for s in ("applies", "unknown", "not_yet_effective", "pending", "superseded")}
    entry = {
        "affected_address_ids": affected,
        "conflict_flag_address_ids": [],
        "team_rule_ids": sorted(ids),
        "before": {"as_of": t["as_of_before"], "results": counts(before)},
        "after": {"as_of": t["as_of_after"], "results": counts(after)},
        "notes": "",
    }
    notes = [f"Matched rules: {', '.join(f'{r['team_rule_id']} ({r['citation']}, effective {r.get('effective_date')})' for r in matched) or 'none extracted'}."]
    if t.get("conflict_with"):
        flagged = sorted(a for a, res in results_at(rules, stacks, t["as_of_before"], ids).items() if any(v["conflict_flag"] for v in res.values()))
        for kid in t["conflict_with"]:
            jur, _, local = match_rules(kid, rules)
            if not local:
                boundary = [a for a in in_city(stacks, jur) if a in affected]
                flagged.extend(boundary)
                notes.append(f"{kid} ({jur}) has no rule text in the supplied corpus (link-only source), so it was not extracted; its conflict set is the {len(boundary)} affected addresses the Census geocoder places inside {jur}.")
        entry["conflict_flag_address_ids"] = sorted(set(flagged))
    entry["notes"] = " ".join(notes)
    return entry


def boundary_test(t: dict, rules: list[dict], stacks: dict) -> dict:
    affected, notes, by_rule = set(), [], {}
    for kid in t["rule_ids"]:
        jur, _, matched = match_rules(kid, rules)
        if matched:
            ids = {r["team_rule_id"] for r in matched}
            hits = sorted(results_at(rules, stacks, t["as_of"], ids))
            notes.append(f"{kid}: rules {', '.join(sorted(ids))} reach {len(hits)} addresses.")
        else:
            hits = in_city(stacks, jur)
            notes.append(f"{kid} ({jur}): no rule text in the supplied corpus (link-only source), so no rule was extracted and lookups.json does not report it; the {len(hits)} addresses the Census geocoder places inside {jur} are listed as the boundary set.")
        by_rule[kid] = hits
        affected.update(hits)
    newark = [a for a in affected if stacks[a]["stack"]["city"] == "Newark, NJ"]
    notes.append(f"Newark addresses in the affected set: {len(newark)}.")
    return {"affected_address_ids": sorted(affected), "conflict_flag_address_ids": [], "by_rule": by_rule, "notes": " ".join(notes)}


def pending_test(t: dict, rules: list[dict], stacks: dict) -> dict:
    matched = list({r["team_rule_id"]: r for kid in t["rule_ids"] for r in match_rules(kid, rules)[2] if r["status"] == "pending"}.values())
    ids = {r["team_rule_id"] for r in matched}
    res = results_at(rules, stacks, t["as_of"], ids)
    applies = [a for a, v in res.items() if any(x["result"] == "applies" for x in v.values())]
    return {
        "affected_address_ids": sorted(a for a, v in res.items() if any(x["result"] == "pending" for x in v.values())),
        "conflict_flag_address_ids": [],
        "team_rule_ids": sorted(ids),
        "notes": f"Pending bills, never in force: {', '.join(f'{r['team_rule_id']} ({r['citation']})' for r in matched) or 'none extracted'}. Affected = addresses they would cover if enacted. Addresses reported as applies: {len(applies)}.",
    }


def negative_test(t: dict, rules: list[dict], stacks: dict) -> dict:
    jur_code, cat_code, _ = t["rule_ids"][0].split("-")
    state, cat = JUR_CODES[jur_code], CAT_CODES[cat_code]
    scoped = [r for r in rules if r["category"] == cat and (r["jurisdiction"] == state or r["jurisdiction"].endswith(f", {state}"))]
    enacted = [r for r in scoped if r["status"] in ("in_force", "not_yet_effective")]
    caps = [r for r in enacted if r.get("caps_rent")]
    others = [r for r in enacted if not r.get("caps_rent")]
    failed = [r for r in scoped if r["status"] in ("failed", "pending")]
    res = results_at(rules, stacks, t["as_of"], {r["team_rule_id"] for r in caps})
    affected = sorted(a for a, v in res.items() if any(x["result"] in ("applies", "superseded", "not_yet_effective") for x in v.values()))
    return {
        "affected_address_ids": affected,
        "conflict_flag_address_ids": [],
        "notes": f"Rent-cap rules reported for {state} addresses: {len(affected)}. Non-enacted measures recorded: {', '.join(f'{r['team_rule_id']} ({r['citation']}, {r['status']})' for r in failed) or 'none in supplied text'}. "
        f"Other {state} rules in this category (e.g. a bar on local rent control) do not impose a cap: {', '.join(f'{r['team_rule_id']} ({r['citation']})' for r in others) or 'none'}.",
    }


def incoming_test(rules: list[dict], stacks: dict) -> dict:
    new = [r for r in rules if r.get("incoming")]
    if not new:
        return {"affected_address_ids": [], "conflict_flag_address_ids": [], "notes": "data/incoming/ is empty; no new ordinance to apply."}
    affected, unknown, parts = set(), set(), []
    for r in new:
        when = r.get("effective_date") or DEFAULT_AS_OF
        day_after = (date.fromisoformat(when) + timedelta(days=1)).isoformat()
        res = results_at(rules, stacks, day_after, {r["team_rule_id"]})
        before = results_at(rules, stacks, DEFAULT_AS_OF, {r["team_rule_id"]})
        hits = {a for a, v in res.items() if v[r["team_rule_id"]]["result"] in ("applies", "unknown")}
        unknown |= {a for a, v in res.items() if v[r["team_rule_id"]]["result"] == "unknown"}
        affected |= hits
        status_now = next(iter(next(iter(before.values())).values()))["result"] if before else "not reported"
        parts.append(f"{r['team_rule_id']} {r['jurisdiction']} {r['category']} ({r['citation']}), effective {r.get('effective_date')}: {status_now} on {DEFAULT_AS_OF}, reaches {len(hits)} addresses on {day_after}.")
    return {
        "affected_address_ids": sorted(affected),
        "conflict_flag_address_ids": [],
        "unknown_address_ids": sorted(unknown),
        "team_rule_ids": [r["team_rule_id"] for r in new],
        "notes": " ".join(parts),
    }


def run(rules: list[dict], stacks: dict) -> dict:
    tests = json.loads(CHANGE_TESTS.read_text())
    handlers = {"as_of": as_of_test, "boundary": boundary_test, "pending": pending_test, "negative": negative_test}
    out = {t["test_id"]: {"title": t["title"], **handlers[t["type"]](t, rules, stacks)} for t in tests}
    out["T6"] = {"title": "New ordinance from data/incoming/", **incoming_test(rules, stacks)}
    for k, v in out.items():
        print(f"changes: {k} affected={len(v['affected_address_ids'])} conflicts={len(v['conflict_flag_address_ids'])}")
    return out
