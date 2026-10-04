"""Module A: one structured model call per corpus document, then grounding checks in code."""

import csv
import hashlib
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from .config import CACHE, CATEGORIES, CORPUS_DIR, DEFAULT_AS_OF, FETCH_LOG, FETCHED, INCOMING, JURISDICTIONS, MANIFEST, OUTPUTS
from .dates import resolve_effective

PROMPT_VERSION = "v5"
CHUNK_LIMIT = 48_000
CHUNK_TARGET = 40_000
FACTS = ["year_built", "units", "owner_type", "use_code", "other"]

SYSTEM = f"""You extract rental housing rules from one legal source document into structured records.
Today (the query date) is {DEFAULT_AS_OF}. You are not giving legal advice; you are transcribing what the text says.

Only extract rules in these six categories:
- rent_increase_limits: caps or formulas limiting rent increases (rent control / rent stabilization / statewide caps), or a state law barring local rent control.
- just_cause_eviction: limits on terminating tenancies to listed causes, required notices, relocation assistance tied to no-fault eviction.
- security_deposits: maximum deposit amounts and deposit conditions.
- application_screening_fees: application / screening fee caps, allowed upfront charges, receipts and refunds, broker fees charged to tenants.
- screening_restrictions: limits on criminal-history screening (fair chance) or source-of-income discrimination in tenant selection.
- algorithmic_rent_setting: bans or restrictions on algorithmic / coordinated pricing software for rents.
Ignore everything else (habitability, notices unrelated to eviction causes, general discrimination not about income source or criminal history, navigation text, news about other topics).

One record per distinct law (one citation) per category. Capture the headline operative rule; do not split a single section into many sub-records.
Do not invent rules. If the document only mentions a law in passing without its operative text, skip it.
Exception: a legislature's own bill page (bill number, title, status, history) for a bill in one of the six categories is recorded as one record even without bill text: status from the bill's session and history, citation is the bill number as printed (e.g. "H.5222"), quote is the bill's title line or committee report sentence, summary says what the bill would do if enacted.

Field rules:
- jurisdiction: the government whose law it is (state code or "City, ST"), even if the document is published by someone else.
- status: "enacted" for law that is in force or signed with a future effective date; "pending" for bills/proposals still under consideration; "failed" for bills from a concluded session that were not enacted, vetoed bills, or measures struck/withdrawn. Massachusetts 193rd General Court (2023-2024) has ended; its unenacted bills are failed. The 194th (2025-2026) is current.
- effective_date: YYYY-MM-DD when the law takes or took effect. Compute it from the text when the text gives a rule (e.g. "first day of the twelfth month next following enactment" with an approval date). A California statute chaptered without an urgency clause takes effect January 1 of the following year. Use null for long-standing codified law whose date the text does not give.
- effective_date_evidence: an exact span from the document supporting the date (approval line, effective-date clause, or announcement), or null.
- citation: the official cite, written so that its section/chapter numbers appear in the document (e.g. "Cal. Civ. Code § 1947.12", "S.F. Admin. Code § 37.10C", "N.J.S.A. 46:8-21.2", "M.G.L. c. 186 § 15B", "P.L.2026, c.43").
- quote: copy an exact contiguous span (one to three sentences, 40-600 characters) from the document that states the operative requirement. Copy character for character; no ellipses, no paraphrase.
- summary: one plain-English sentence a renter can understand, restating the quote without adding facts.
- key_value: the headline number or formula (e.g. "1 month's rent", "5% + CPI, max 10%", "$50"), or null.
Building-coverage predicates (only from the text; null when the text sets no such condition):
- built_on_or_before: YYYY-MM-DD; the rule only covers buildings built / first certificate of occupancy on or before this date.
- built_after: YYYY-MM-DD; the rule only covers buildings built after this date.
- exempt_if_newer_than_years: integer N when buildings with a certificate of occupancy issued within the previous N years are exempt (rolling exemption).
- min_units / max_units: unit-count limits on the buildings covered.
- exemption_max_units: integer N when an exemption only applies to properties with N or fewer units (e.g. small-landlord or owner-occupied exceptions).
- facts_required: building facts the coverage depends on: year_built, units, owner_type, use_code, or "other" for any other building-level fact (e.g. public funding, subsidized status, registration). Do not list tenant-specific facts like length of tenancy. Do not list the landlord's conduct (e.g. whether it uses pricing software, charges a fee, or screens applicants): a rule regulating conduct covers every building in its jurisdiction.
- caps_rent: true only for a rent_increase_limits rule that itself limits rent or rent increases on covered units; false for a law that bars or preempts local rent control, and false in every other category.
- yields_to_local: true only if the text says this rule does not apply where a local ordinance is more protective / restrictive (e.g. a state cap that exempts units under local rent control).
- penalty, exemption_note, coverage_text: short strings from the text or null.
Return an empty list if the document contains no rule in the six categories."""

RULE_PROPS = {
    "category": {"type": "string", "enum": CATEGORIES},
    "jurisdiction": {"type": "string", "enum": JURISDICTIONS},
    "status": {"type": "string", "enum": ["enacted", "pending", "failed"]},
    "title": {"type": "string"},
    "citation": {"type": "string"},
    "quote": {"type": "string"},
    "summary": {"type": "string"},
    "key_value": {"type": ["string", "null"]},
    "effective_date": {"type": ["string", "null"]},
    "effective_date_evidence": {"type": ["string", "null"]},
    "coverage_text": {"type": ["string", "null"]},
    "built_on_or_before": {"type": ["string", "null"]},
    "built_after": {"type": ["string", "null"]},
    "exempt_if_newer_than_years": {"type": ["integer", "null"]},
    "min_units": {"type": ["integer", "null"]},
    "max_units": {"type": ["integer", "null"]},
    "exemption_max_units": {"type": ["integer", "null"]},
    "facts_required": {"type": "array", "items": {"type": "string", "enum": FACTS}},
    "yields_to_local": {"type": "boolean"},
    "caps_rent": {"type": "boolean"},
    "exemption_note": {"type": ["string", "null"]},
    "penalty": {"type": ["string", "null"]},
}

TOOL = {
    "name": "record_rules",
    "description": "Record every rental housing rule found in the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "items": {"type": "object", "properties": RULE_PROPS, "required": list(RULE_PROPS)},
            }
        },
        "required": ["rules"],
    },
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PUNCT = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u00a0": " "})


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    out, idx = [], []
    prev_space = True
    for i, ch in enumerate(text):
        ch = unicodedata.normalize("NFKC", ch).translate(PUNCT)
        for c in ch:
            if c.isspace():
                if prev_space:
                    continue
                c, prev_space = " ", True
            else:
                prev_space = False
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def normalize(text: str) -> str:
    return normalize_with_map(text)[0].strip()


def ground_quote(quote: str, source: str) -> str | None:
    """Return the slice of the source file that matches the quote, or None."""
    norm_src, idx = normalize_with_map(source)
    q = normalize(quote).strip(" .\"'")
    if len(q) < 20:
        return None
    pos = norm_src.find(q)
    if pos < 0:
        pos = norm_src.lower().find(q.lower())
    if pos < 0:
        return None
    start, end = idx[pos], idx[pos + len(q) - 1] + 1
    return source[start:end]


def citation_grounded(citation: str, source: str) -> bool:
    src = normalize(source).lower()
    nums = re.findall(r"\d+(?:[.:\-]\d+)*[a-z]?", citation.lower())
    if nums:
        return all(n in src or n.lstrip("0") in src for n in nums)
    words = [w for w in re.findall(r"[a-z]{4,}", citation.lower())]
    return bool(words) and any(w in src for w in words)


def chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_LIMIT:
        return [text]
    parts, cur = [], ""
    for block in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(block) > CHUNK_TARGET:
            parts.append(cur)
            cur = ""
        cur += block + "\n\n"
    if cur.strip():
        parts.append(cur)
    return parts


def load_documents() -> list[dict]:
    docs = []
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] != "ok" or not row["text_file"]:
                continue
            path = CORPUS_DIR / row["text_file"]
            docs.append({
                "doc_id": row["doc_id"],
                "path": path,
                "hint": row["jurisdictions"],
                "url": row["url"],
                "retrieved_at": row["retrieved_at"],
                "incoming": False,
            })
    if FETCH_LOG.exists():
        with FETCH_LOG.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                path = FETCHED / f"{row['doc_id']}.txt"
                if row["status"] == "ok" and path.exists():
                    docs.append({"doc_id": row["doc_id"], "path": path, "hint": row["jurisdictions"], "url": row["url"],
                                 "retrieved_at": row["retrieved_at"], "incoming": False})
    for path in sorted(INCOMING.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        url = re.search(r"^SOURCE:\s*(\S+)", text, re.M)
        ret = re.search(r"^RETRIEVED:\s*(.+)$", text, re.M)
        docs.append({
            "doc_id": f"IN-{path.stem}",
            "path": path,
            "hint": "unknown (new document)",
            "url": url.group(1) if url else str(path.relative_to(path.parents[2])),
            "retrieved_at": ret.group(1).strip() if ret else None,
            "incoming": True,
        })
    return docs


def call_model(client: anthropic.Anthropic, model: str, doc: dict, text: str) -> list[dict]:
    msg = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_rules"},
        messages=[{
            "role": "user",
            "content": f"Document {doc['doc_id']} (manifest jurisdiction: {doc['hint']}; URL: {doc['url']}).\n\n<document>\n{text}\n</document>",
        }],
    )
    for block in msg.content:
        if block.type == "tool_use":
            rules = block.input.get("rules", [])
            if isinstance(rules, str):
                rules = json.loads(rules)
            if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
                raise ValueError("model returned rules in an unexpected shape")
            return rules
    raise ValueError("model returned no tool call")


def cache_path(model: str, doc: dict) -> Path:
    text = doc["path"].read_text(encoding="utf-8")
    key = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{text}".encode()).hexdigest()[:24]
    return CACHE / "extract" / f"{doc['doc_id']}-{key}.json"


def make_client() -> anthropic.Anthropic:
    or_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if or_key:
        return anthropic.Anthropic(
            base_url="https://openrouter.ai/api",
            api_key=or_key,
            max_retries=4,
        )
    return anthropic.Anthropic(max_retries=4)


def extract_doc(client, model: str, doc: dict, refresh: bool, *, api_model: str | None = None) -> dict:
    api_model = api_model or model
    text = doc["path"].read_text(encoding="utf-8")
    cache_file = cache_path(model, doc)
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text())
    raw = []
    for part in chunks(text):
        last_err = None
        for _ in range(3):
            try:
                raw.extend(call_model(client, api_model, doc, part))
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if last_err:
            raise last_err
    record = {"doc_id": doc["doc_id"], "model": api_model, "prompt_version": PROMPT_VERSION, "rules": raw}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(record, indent=1))
    return record


def validate(raw: dict, doc: dict, text: str, audit: list) -> dict | None:
    def drop(reason):
        audit.append({"doc_id": doc["doc_id"], "decision": "dropped", "reason": reason, "citation": raw.get("citation"), "category": raw.get("category")})
        return None

    if raw.get("category") not in CATEGORIES:
        return drop("category not in list")
    if raw.get("jurisdiction") not in JURISDICTIONS:
        return drop("jurisdiction not in list")
    span = ground_quote(raw.get("quote", ""), text)
    if not span:
        return drop("quote not found in source")
    if not citation_grounded(raw.get("citation", ""), text):
        return drop("citation not found in source")
    rule = dict(raw)
    rule["quote"] = span
    for k in ("effective_date", "built_on_or_before", "built_after"):
        if rule.get(k) and not DATE_RE.match(rule[k]):
            rule[k] = None
    ev = rule.get("effective_date_evidence")
    rule["effective_date_evidence"] = ground_quote(ev, text) if ev else None
    kept_date, why = resolve_effective(rule.get("effective_date"), text)
    if rule.get("effective_date") != kept_date:
        audit.append({"doc_id": doc["doc_id"], "decision": "effective_date", "citation": rule.get("citation"), "claimed": rule.get("effective_date"), "kept": kept_date, "reason": why})
    rule["effective_date"] = kept_date
    rule["facts_required"] = [f for f in rule.get("facts_required") or [] if f in FACTS]
    rule.update(source_doc_id=doc["doc_id"], source_url=doc["url"], retrieved_at=doc["retrieved_at"], incoming=doc["incoming"])
    rule["_hint_match"] = rule["jurisdiction"].split(",")[0] in doc["hint"]
    audit.append({"doc_id": doc["doc_id"], "decision": "kept", "citation": rule["citation"], "category": rule["category"], "jurisdiction": rule["jurisdiction"]})
    return rule


def citation_key(citation: str) -> str:
    nums = re.findall(r"\d+(?:[.:\-]\d+)*[a-z]?", citation.lower())
    return "|".join(sorted(set(nums))) if nums else re.sub(r"[^a-z]", "", citation.lower())


def dedupe(rules: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rules:
        groups.setdefault((r["jurisdiction"], r["category"], citation_key(r["citation"])), []).append(r)
    out = []
    for group in groups.values():
        group.sort(key=lambda r: (not r["_hint_match"], r["source_doc_id"]))
        best = dict(group[0])
        if not best.get("effective_date"):
            best["effective_date"] = next((g["effective_date"] for g in group if g.get("effective_date")), None)
        best["also_found_in"] = sorted({g["source_doc_id"] for g in group[1:]} - {best["source_doc_id"]})
        out.append(best)
    return out


def run(refresh: bool = False) -> list[dict]:
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    docs = load_documents()
    misses = [d for d in docs if refresh or not cache_path(model, d).exists()]
    or_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    ant_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    api_model = (os.environ.get("OPENROUTER_MODEL") or model) if or_key else model
    if misses and not or_key and not ant_key:
        raise SystemExit(
            f"No API key set and {len(misses)} documents need the model. "
            "Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY in .env and run with `uv run --env-file .env ...`."
        )
    client = make_client() if misses else None
    print(f"extract: {len(docs)} documents with model {api_model} ({len(misses)} model calls, {len(docs) - len(misses)} cached)")

    failures, audit, kept = [], [], []

    def work(doc):
        try:
            return doc, extract_doc(client, model, doc, refresh, api_model=api_model), None
        except Exception as e:  # noqa: BLE001
            return doc, None, e

    with ThreadPoolExecutor(max_workers=6) as pool:
        for doc, record, err in pool.map(work, docs):
            if err:
                failures.append(f"{doc['path'].name}\t{err}")
                print(f"  FAIL {doc['doc_id']}: {err}")
                continue
            text = doc["path"].read_text(encoding="utf-8")
            n = 0
            for raw in record["rules"]:
                rule = validate(raw, doc, text, audit)
                if rule:
                    kept.append(rule)
                    n += 1
            print(f"  {doc['doc_id']}: {len(record['rules'])} proposed, {n} grounded")

    (OUTPUTS / "failures.txt").write_text("\n".join(failures) + ("\n" if failures else ""))
    with (OUTPUTS / "audit.jsonl").open("w") as f:
        for a in audit:
            f.write(json.dumps({**a, "model": model, "prompt_version": PROMPT_VERSION}) + "\n")
    rules = dedupe(kept)
    print(f"extract: {len(kept)} grounded records -> {len(rules)} rules after dedupe; {len(failures)} failed docs")
    return rules
