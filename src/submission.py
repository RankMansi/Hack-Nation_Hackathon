"""Only permitted template/schema keys in submission files; rich data is separate."""

import json

from .config import DEFAULT_AS_OF, OUTPUTS, RAW


def active_records(rules, as_of=DEFAULT_AS_OF):
    # No "expired" status is allowed in the submission schema. Retain history
    # internally and omit records whose inclusive operative interval ended.
    selected = [r for r in rules if not r.get("incoming") and
                (not r.get("end_date") or as_of <= r["end_date"])]
    ids = {r["team_rule_id"] for r in selected}
    properties = json.loads((RAW / "schema/rule_record.schema.json").read_text())["properties"]
    out = []
    for r in selected:
        minimal = {k: v for k, v in r.items() if k in properties}
        minimal["overrides"] = [rid for rid in minimal.get("overrides", []) if rid in ids]
        out.append(minimal)
    return out


def write(rules, lookups, changes):
    rich = {"rules": rules}
    (OUTPUTS / "rules_internal.json").write_text(json.dumps(rich, indent=2))
    (OUTPUTS / "changes_internal.json").write_text(json.dumps(changes, indent=2))
    rmap = {r["team_rule_id"]: r for r in rules}
    rich_lookups = {
        "as_of": lookups["as_of"],
        "lookups": {aid: [{**e, "as_of": lookups["as_of"],
                          **{k: rmap[e["team_rule_id"]][k] for k in (
                              "source_doc_id", "source_url", "quoted_span", "retrieved_at",
                              "effective_date", "end_date", "supporting_evidence")}}
                         for e in entries] for aid, entries in lookups["lookups"].items()},
    }
    (OUTPUTS / "lookups_internal.json").write_text(json.dumps(rich_lookups, indent=2))
    minimal_rules = active_records(rules)
    ids = {r["team_rule_id"] for r in minimal_rules}
    minimal_lookups = {
        "as_of": lookups["as_of"],
        "lookups": {aid: [e for e in entries if e["team_rule_id"] in ids]
                    for aid, entries in lookups["lookups"].items()},
    }
    minimal_changes = {tid: {k: entry[k] for k in (
        "affected_address_ids", "conflict_flag_address_ids", "notes")}
        for tid, entry in changes.items() if tid in {f"T{i}" for i in range(1, 6)}}
    for filename, value in (
        ("rules.json", {"rules": minimal_rules}),
        ("lookups.json", minimal_lookups), ("changes.json", minimal_changes),
    ):
        (OUTPUTS / filename).write_text(json.dumps(value, indent=2) + "\n")