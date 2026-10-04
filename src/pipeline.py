"""Single entry: extract -> adapt -> resolve -> apply -> changes -> self-check."""

import argparse
import json
import sys

from . import adapt, apply, changes, check, extract, resolve
from .config import ADDRESSES, CACHE, CORPUS_DIR, DEFAULT_AS_OF, INCOMING, MANIFEST, OUTPUTS, RAW


def main() -> None:
    parser = argparse.ArgumentParser(description="Rental Housing Law Navigator pipeline")
    parser.add_argument("--refresh", action="store_true", help="ignore the extraction cache and call the model again")
    args = parser.parse_args()

    missing = [p for p in (MANIFEST, CORPUS_DIR / "text", ADDRESSES, RAW / "schema" / "rule_record.schema.json") if not p.exists()]
    if missing:
        raise SystemExit(f"Starter pack incomplete under data/raw/: missing {[str(p) for p in missing]}")
    for d in (CACHE, OUTPUTS, INCOMING):
        d.mkdir(parents=True, exist_ok=True)

    stacks = resolve.run()
    rules = adapt.to_schema(extract.run(refresh=args.refresh))
    schema = json.loads((RAW / "schema" / "rule_record.schema.json").read_text())
    submitted = [{k: v for k, v in r.items() if k in schema["properties"]} for r in rules]
    (OUTPUTS / "rules.json").write_text(json.dumps({"rules": submitted}, indent=2))
    (OUTPUTS / "lookups.json").write_text(json.dumps(apply.lookups(rules, stacks, DEFAULT_AS_OF), indent=2))
    raw_changes = changes.run(rules, stacks)
    public = {tid: {"affected_address_ids": v["affected_address_ids"], "conflict_flag_address_ids": v.get("conflict_flag_address_ids", []), "notes": v.get("notes", "")}
              for tid, v in raw_changes.items() if tid != "T6"}
    (OUTPUTS / "changes.json").write_text(json.dumps(public, indent=2))
    print(f"wrote {OUTPUTS}/rules.json, lookups.json, changes.json")
    sys.exit(0 if check.run() else 1)


if __name__ == "__main__":
    main()
