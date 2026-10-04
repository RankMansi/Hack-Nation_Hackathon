"""Self-check run after the pipeline. The participant pack ships without score.py or a dev key, so this
verifies what can be verified without an answer key: schema, grounding, coverage of all addresses, T1-T5."""

import json
import re
from collections import Counter

from .apply import evaluate
from .changes import match_rules
from .config import CACHE, CATEGORIES, OUTPUTS, RAW
from .extract import load_documents, normalize

REQUIRED = ["team_rule_id", "jurisdiction", "level", "category", "status", "title", "requirement", "citation", "source_url", "quoted_span"]
RESULTS = {"applies", "unknown", "superseded", "not_yet_effective", "pending"}


def line(ok: bool, text: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    return ok


def run() -> bool:
    rules = json.loads((OUTPUTS / "rules.json").read_text())["rules"]
    lookups = json.loads((OUTPUTS / "lookups.json").read_text())
    changes = json.loads((OUTPUTS / "changes.json").read_text())
    stacks = json.loads((CACHE / "stacks.json").read_text())
    docs = {d["doc_id"]: normalize(d["path"].read_text(encoding="utf-8")) for d in load_documents()}
    print("\ncheck: rules.json")
    ok = True
    bad_schema = [r["team_rule_id"] for r in rules if any(not r.get(k) for k in REQUIRED) or r["category"] not in CATEGORIES
                  or r["status"] not in ("in_force", "not_yet_effective", "pending", "failed") or len(r["quoted_span"]) < 20
                  or (r.get("effective_date") and not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", r["effective_date"]))]
    ok &= line(not bad_schema, f"{len(rules)} rules match the schema {bad_schema or ''}")
    ungrounded = [r["team_rule_id"] for r in rules if normalize(r["quoted_span"]) not in docs.get(r["source_doc_id"], "")]
    ok &= line(not ungrounded, f"every quoted_span is found in its source document {ungrounded or ''}")
    by = Counter((r["jurisdiction"], r["category"]) for r in rules)
    print("  rules by jurisdiction x category:")
    for jur in sorted({j for j, _ in by}):
        print(f"    {jur:20s} " + "  ".join(f"{c.split('_')[0][:5]}={by[(jur, c)]}" for c in CATEGORIES))

    print("check: lookups.json")
    lk = lookups["lookups"]
    ok &= line(len(lk) == len(stacks) == 500, f"{len(lk)} addresses in lookups (expect 500)")
    ids = {r["team_rule_id"] for r in rules}
    bad = [e for v in lk.values() for e in v if e["result"] not in RESULTS or e["team_rule_id"] not in ids]
    ok &= line(not bad, "every result value and team_rule_id is valid")
    results = Counter(e["result"] for v in lk.values() for e in v)
    print(f"  results: {dict(results)}")
    applies = [e for v in lk.values() for e in v if e["result"] == "applies"]
    rmap = {r["team_rule_id"]: r for r in rules}
    cited = sum(1 for e in applies if rmap[e["team_rule_id"]]["source_url"] and normalize(rmap[e["team_rule_id"]]["quoted_span"]) in docs.get(rmap[e["team_rule_id"]]["source_doc_id"], ""))
    ok &= line(cited == len(applies), f"citations: {cited}/{len(applies)} 'applies' answers carry a grounded quote")
    newark_bans = [a for a, v in lk.items() if stacks[a]["stack"]["city"] == "Newark, NJ" and any(rmap[e["team_rule_id"]]["jurisdiction"] in ("Jersey City, NJ", "Hoboken, NJ") for e in v)]
    ok &= line(not newark_bans, "no Newark address carries a Jersey City or Hoboken rule")
    ma_caps = [a for a, v in lk.items() if stacks[a]["stack"]["state"] == "MA" and any(rmap[e["team_rule_id"]]["category"] == "rent_increase_limits" and e["result"] in ("applies", "superseded") and "40P" not in rmap[e["team_rule_id"]]["citation"] for e in v)]
    ok &= line(not ma_caps, f"no Boston/Cambridge address reports a rent cap ({len(ma_caps)} found)")

    print("check: changes.json (T1-T5 expectations from dev/change_tests.json)")
    ca = {a for a, s in stacks.items() if s["stack"]["state"] == "CA"}
    nj = {a for a, s in stacks.items() if s["stack"]["state"] == "NJ"}
    ma = {a for a, s in stacks.items() if s["stack"]["state"] == "MA"}
    t1 = match_rules("CA-ALG-01", rules)[2]
    ok &= line(bool(t1), f"T1 CA algorithmic rule extracted: {[(r['team_rule_id'], r['citation'], r.get('effective_date')) for r in t1]}")
    if t1:
        rid = t1[0]["team_rule_id"]
        sample = sorted(ca)[:40]
        pre = [next((e["result"] for e in evaluate(rules, stacks[a], "2025-12-31") if e["team_rule_id"] == rid), None) for a in sample]
        post = [next((e["result"] for e in evaluate(rules, stacks[a], "2026-01-02") if e["team_rule_id"] == rid), None) for a in sample]
        ok &= line(set(pre) == {"not_yet_effective"} and set(post) == {"applies"}, f"T1 not_yet_effective on 2025-12-31 -> applies on 2026-01-02 (sampled {len(sample)}: {Counter(pre)} -> {Counter(post)})")
    ok &= line(set(changes["T1"]["affected_address_ids"]) == ca, f"T1 affected = all {len(ca)} CA addresses ({len(changes['T1']['affected_address_ids'])})")
    t2 = changes["T2"]
    ok &= line(not any(stacks[a]["stack"]["city"] == "Newark, NJ" for a in t2["affected_address_ids"]), f"T2 {len(t2['affected_address_ids'])} affected, none in Newark")
    t3 = changes["T3"]
    ok &= line(set(t3["affected_address_ids"]) == nj, f"T3 affected = all {len(nj)} NJ addresses ({len(t3['affected_address_ids'])})")
    jc_hob = {a for a in nj if stacks[a]["stack"]["city"] in ("Jersey City, NJ", "Hoboken, NJ")}
    ok &= line(set(t3["conflict_flag_address_ids"]) == jc_hob, f"T3 conflict flags = {len(jc_hob)} Jersey City + Hoboken addresses ({len(t3['conflict_flag_address_ids'])})")
    t4 = changes["T4"]
    pending = [r for r in rules if r["jurisdiction"] == "MA" and r["category"] == "algorithmic_rent_setting" and r["status"] == "pending"]
    ok &= line(len(pending) >= 2 and set(t4["affected_address_ids"]) == ma, f"T4 pending bills {[r['citation'] for r in pending]}, affected = all {len(ma)} MA addresses ({len(t4['affected_address_ids'])})")
    ok &= line(not changes["T5"]["affected_address_ids"], "T5 affected set is empty")
    allowed = {"affected_address_ids", "conflict_flag_address_ids", "notes"}
    extra = {tid: sorted(set(v) - allowed) for tid, v in changes.items() if set(v) - allowed}
    ok &= line(set(changes) == {"T1", "T2", "T3", "T4", "T5"} and not extra, f"changes.json is T1-T5 with only the template fields {extra or ''}")
    schema = json.loads((RAW / "schema" / "rule_record.schema.json").read_text())
    stray = sorted({k for r in rules for k in r if k not in schema["properties"]})
    ok &= line(not stray, f"rules.json has only schema fields {stray or ''}")
    print(f"\ncheck: {'ALL PASS' if ok else 'SOME CHECKS FAILED'}")
    return ok
