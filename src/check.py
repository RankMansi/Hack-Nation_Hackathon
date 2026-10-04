"""Local requirement checks, not the unavailable official challenge scorer."""

import csv
import hashlib
import json
from collections import Counter
from datetime import date

from jsonschema import Draft202012Validator

from .apply import evaluate
from .changes import match_rules, run as change_run
from .config import ADDRESSES, CACHE, DEFAULT_AS_OF, OUTPUTS, RAW
from .evidence import sources
from .extract import citation_grounded, load_documents
from .submission import active_records

RESULTS = {"applies", "unknown", "superseded", "not_yet_effective", "pending"}


def run():
    checks = []

    def check(condition, name, details=None):
        checks.append({"check": name, "passed": bool(condition), "details": details})
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f": {details}" if details else ""))

    rules = json.loads((OUTPUTS / "rules.json").read_text())["rules"]
    rich = json.loads((OUTPUTS / "rules_internal.json").read_text())["rules"]
    lookups = json.loads((OUTPUTS / "lookups.json").read_text())
    changes = json.loads((OUTPUTS / "changes.json").read_text())
    detailed_changes = json.loads((OUTPUTS / "changes_internal.json").read_text())
    stacks = json.loads((CACHE / "stacks.json").read_text())
    docs = {d["doc_id"]: {**d, "text": d["path"].read_text()} for d in load_documents()}
    docs.update(sources())
    with ADDRESSES.open(newline="") as f:
        addresses = {a["address_id"] for a in csv.DictReader(f)}
    schema = json.loads((RAW / "schema/rule_record.schema.json").read_text())
    validator = Draft202012Validator(schema)
    schema_errors = [f"{r.get('team_rule_id')}: {e.message}" for r in rules for e in validator.iter_errors(r)]
    check(not schema_errors, "All submission rules satisfy the published JSON Schema", schema_errors)
    check(all(set(r) <= set(schema["properties"]) for r in rules), "No diagnostic fields in minimal rules")
    check(rules == active_records(rich), "Minimal rules are current projections of internal history")
    ids = {r["team_rule_id"] for r in rules}
    all_ids = {r["team_rule_id"] for r in rich}
    check(len(all_ids) == len(rich), "Rule IDs are unique and content-stable")
    # Check completeness against independent original cache proposals, not only
    # against an evaluator that could share the same lossy normalization.
    from .extract import cache_path, normalize, validate
    lost = []
    for sid in ("D052", "D006", "D009"):
        d = next(d for d in load_documents() if d["doc_id"] == sid)
        proposals = json.loads(cache_path("claude-sonnet-4-5", d).read_text())["rules"]
        validated = [validate(p, d, d["path"].read_text(), []) for p in proposals]
        expected = {(p["category"], normalize(p["quote"]), p["summary"]) for p in validated if p}
        actual = {(r["category"], normalize(r["quoted_span"]), r["requirement"])
                  for r in rich if r["source_doc_id"] == sid}
        if expected != actual:
            lost.append(sid)
    check(not lost, "Distinct deposit/eviction obligations and coverage branches retained from original caches", lost)
    ungrounded = [r["team_rule_id"] for r in rich
                  if r["quoted_span"] not in docs.get(r["source_doc_id"], {}).get("text", "")]
    check(not ungrounded, "Every rule quote is an exact slice of its captured source", ungrounded)
    uncited = [r["team_rule_id"] for r in rich
               if not citation_grounded(r["citation"], docs[r["source_doc_id"]]["text"])]
    check(not uncited, "All citation identifiers occur in the cited source", uncited)
    bad_evidence = []
    for r in rich:
        for span in r.get("supporting_evidence", []):
            d = docs.get(span["source_doc_id"], {})
            if span["quoted_span"] not in d.get("text", "") or not span.get("source_url") or not span.get("retrieved_at"):
                bad_evidence.append(r["team_rule_id"])
        for key in ("effective_date", "end_date", "failed_date", "enacted_date"):
            if r.get(key):
                date.fromisoformat(r[key])
        if r.get("effective_date") and not r.get("effective_date_evidence"):
            bad_evidence.append(r["team_rule_id"] + " date without evidence")
        if r.get("end_date") and not r.get("end_date_evidence"):
            bad_evidence.append(r["team_rule_id"] + " end date without evidence")
        if r.get("effective_date_evidence") and r["effective_date_evidence"] not in docs[r["source_doc_id"]]["text"]:
            bad_evidence.append(r["team_rule_id"] + " effective span not grounded")
    check(not bad_evidence, "Temporal derivations and supplemental supporting quotes are auditable", bad_evidence)
    check(all(r.get("retrieved_at") and r.get("source_url") for r in rich), "All answers retain source URL and retrieval date internally")
    supplemental = sources()
    check(all(hashlib.sha256(d["text"].encode()).hexdigest() == d["sha256"] for d in supplemental.values()),
          "Supplemental captures match recorded SHA-256 hashes")
    check(all(set(r.get("overrides", [])) <= ids for r in rules), "Submission interaction references exist")
    check(set(lookups) == {"as_of", "lookups"} and lookups["as_of"] == DEFAULT_AS_OF,
          "Lookup top-level fields match template and default date")
    check(set(lookups["lookups"]) == addresses == set(stacks) and len(addresses) == 500,
          "Exactly the 500 supplied address IDs are covered")
    entries = [e for v in lookups["lookups"].values() for e in v]
    check(all(set(e) == {"team_rule_id", "result", "explanation", "conflict_flag"} and
              e["result"] in RESULTS and e["team_rule_id"] in ids and e["explanation"] and
              isinstance(e["conflict_flag"], bool) for e in entries), "Only the five permitted lookup results and template fields")
    check(all(len({e["team_rule_id"] for e in v}) == len(v) for v in lookups["lookups"].values()),
          "No duplicate rule answers per address")
    check(all(lookups["lookups"][a] == [e for e in evaluate(rich, s, DEFAULT_AS_OF) if e["team_rule_id"] in ids]
              for a, s in stacks.items()), "Every exported lookup matches the evaluator")
    check(set(changes) == {f"T{i}" for i in range(1, 6)} and all(set(v) == {
        "affected_address_ids", "conflict_flag_address_ids", "notes"} for v in changes.values()),
        "Exactly T1–T5 with minimal change fields")
    check(all(set(v["affected_address_ids"]) <= addresses and set(v["conflict_flag_address_ids"]) <= addresses and
              v["affected_address_ids"] == sorted(set(v["affected_address_ids"])) and
              v["conflict_flag_address_ids"] == sorted(set(v["conflict_flag_address_ids"])) for v in changes.values()),
          "Change sets are unique, sorted and refer to supplied addresses")
    regenerated = change_run(rich, stacks)
    check(all(detailed_changes[k] == v for k, v in regenerated.items()), "Change tracking is reproducible from rule evaluation")
    states = {st: {a for a, s in stacks.items() if s["stack"]["state"] == st} for st in ("CA", "NJ", "MA")}
    ca, nj, ma = states["CA"], states["NJ"], states["MA"]
    check((len(ca), len(nj), len(ma)) == (250, 140, 110), "All state populations match the sample")

    def entries_for(key, aid, when):
        selected = {r["team_rule_id"] for r in match_rules(key, rich)[2]}
        return [e for e in evaluate(rich, stacks[aid], when) if e["team_rule_id"] in selected]

    check(all(entries_for("CA-ALG-01", a, "2025-12-31") and
              {e["result"] for e in entries_for("CA-ALG-01", a, "2025-12-31")} == {"not_yet_effective"} and
              {e["result"] for e in entries_for("CA-ALG-01", a, "2026-01-01")} == {"applies"} and
              {e["result"] for e in entries_for("CA-ALG-01", a, "2026-01-02")} == {"applies"} for a in ca),
          "T1 effective-day transition checked on all 250 CA addresses")
    check(set(changes["T1"]["affected_address_ids"]) == ca, "T1 affected set equals all CA addresses")
    hob = {a for a, s in stacks.items() if s["stack"]["city"] == "Hoboken, NJ"}
    jc = {a for a, s in stacks.items() if s["stack"]["city"] == "Jersey City, NJ"}
    check(len(hob) == 40 and len(jc) == 50 and not hob & jc and
          set(detailed_changes["T2"]["by_rule"]["HOB-ALG-01"]) == hob and
          set(detailed_changes["T2"]["by_rule"]["JC-ALG-01"]) == jc and
          set(changes["T2"]["affected_address_ids"]) == hob | jc,
          "T2 separate 40 Hoboken / 50 Jersey City sets, excluding Newark")
    check(all({e["result"] for e in entries_for("NJ-ALG-01", a, "2026-10-01")} == {"not_yet_effective"} and
              {e["result"] for e in entries_for("NJ-ALG-01", a, "2027-06-30")} == {"not_yet_effective"} and
              {e["result"] for e in entries_for("NJ-ALG-01", a, "2027-07-01")} == {"applies"} and
              {e["result"] for e in entries_for("NJ-ALG-01", a, "2027-07-02")} == {"applies"} for a in nj),
          "T3 future transition checked on all 140 NJ addresses")
    flagged = {a for a in nj if any(e["conflict_flag"] for e in entries_for("NJ-ALG-01", a, DEFAULT_AS_OF))}
    future_flags = {a for a in nj if any(e["conflict_flag"] for e in entries_for("NJ-ALG-01", a, "2027-07-02"))}
    check(set(changes["T3"]["affected_address_ids"]) == nj and
          set(changes["T3"]["conflict_flag_address_ids"]) == flagged == future_flags == hob | jc,
          "T3 exactly 90 local conflicts, present in current and future lookup answers")
    check(all(len(entries_for("MA-ALG-P1", a, DEFAULT_AS_OF)) == 1 and
              len(entries_for("MA-ALG-P2", a, DEFAULT_AS_OF)) == 1 and
              all(e["result"] == "pending" for key in ("MA-ALG-P1", "MA-ALG-P2")
                  for e in entries_for(key, a, DEFAULT_AS_OF)) for a in ma) and
          set(changes["T4"]["affected_address_ids"]) == ma and len(detailed_changes["T4"]["team_rule_ids"]) == 2,
          "T4 both distinct pending bills at every MA address")
    check(not changes["T5"]["affected_address_ids"] and not any(
        r["jurisdiction"] in ("MA", "Boston, MA", "Cambridge, MA") and r.get("caps_rent") and
        r["status"] not in ("pending", "failed") for r in rich),
        "T5 never imposes a Boston/Cambridge rent cap and has empty affected set")
    check(any(r["status"] == "failed" and r["source_doc_id"] == "S-MA-BALLOT" for r in rich),
          "Failed initiative has verified disposition, not a fabricated enacted cap")
    unresolved = [s for s in stacks.values() if not s["geocoded"]]
    check(all(s["stack"]["city"] is None for s in unresolved) and all(
        all(next(r for r in rich if r["team_rule_id"] == e["team_rule_id"])["level"] == "state"
            for e in evaluate(rich, s, DEFAULT_AS_OF)) for s in unresolved),
        "Unresolved addresses never acquire local law from their postal city")
    check(not any("application for employment" in r["quoted_span"].lower() for r in rich),
          "Employment screening law is not rendered as housing law")
    check(not any(r.get("end_date") and r["end_date"] < DEFAULT_AS_OF for r in rules),
          "Ended rules cannot govern current submission answers")
    check(not (OUTPUTS / "failures.txt").read_text().strip(), "All available cached corpus documents processed successfully")
    report = {"official_scorer_available": False, "passed": all(c["passed"] for c in checks),
              "checks": checks, "rules_current": len(rules), "rules_internal": len(rich),
              "lookup_results": dict(Counter(e["result"] for e in entries))}
    (OUTPUTS / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print("check:", "ALL PASS" if report["passed"] else "FAILED (see outputs/validation.json)")
    return report["passed"]


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)