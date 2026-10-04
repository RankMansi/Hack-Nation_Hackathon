"""Single entry: extract -> adapt -> resolve -> apply -> changes -> self-check."""

import argparse
import json
import sys

from . import adapt, apply, changes, check, extract, resolve, evidence, submission
from .config import ADDRESSES, CACHE, CORPUS_DIR, DEFAULT_AS_OF, INCOMING, MANIFEST, OUTPUTS, RAW


def main() -> None:
    parser = argparse.ArgumentParser(description="Rental Housing Law Navigator pipeline")
    parser.add_argument("--refresh", action="store_true", help="ignore the extraction cache and call the model again")
    parser.add_argument("--include-incoming", action="store_true", help="evaluate optional incoming documents internally; never include them in required exports")
    args = parser.parse_args()

    missing = [p for p in (MANIFEST, CORPUS_DIR / "text", ADDRESSES, RAW / "schema" / "rule_record.schema.json") if not p.exists()]
    if missing:
        raise SystemExit(f"Starter pack incomplete under data/raw/: missing {[str(p) for p in missing]}")
    for d in (CACHE, OUTPUTS, INCOMING):
        d.mkdir(parents=True, exist_ok=True)

    stacks = resolve.run()
    extracted = extract.run(refresh=args.refresh, include_incoming=args.include_incoming)
    repairs = []
    # Required rules are normalized independently. Optional incoming documents
    # must not win a duplicate merge or replace required source evidence.
    corrected = evidence.repair([r for r in extracted if not r.get("incoming")],
                                extract.load_documents(), repairs)
    with (OUTPUTS / "audit.jsonl").open("a") as f:
        for event in repairs:
            f.write(json.dumps({"stage": "evidence_repair", **event}) + "\n")
    rules = adapt.to_schema(corrected)
    rules.extend(adapt.to_schema([r for r in extracted if r.get("incoming")]))
    required_rules = [r for r in rules if not r.get("incoming")]
    tracked = changes.run(required_rules, stacks)
    if args.include_incoming:
        tracked["optional_incoming"] = changes.incoming_test(rules, stacks)
    submission.write(rules, apply.lookups(required_rules, stacks, DEFAULT_AS_OF), tracked)
    (OUTPUTS / "source_inventory.json").write_text(json.dumps(evidence.inventory(), indent=2) + "\n")
    print(f"wrote {OUTPUTS}/rules.json, lookups.json, changes.json")
    sys.exit(0 if check.run() else 1)


if __name__ == "__main__":
    main()
