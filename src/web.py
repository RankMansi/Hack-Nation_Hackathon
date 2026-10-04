"""Local demo evaluates internal historical records without model/network calls."""

import json
import re
from datetime import date
from html import escape
from string import Template

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .apply import evaluate
from .config import CACHE, CATEGORIES, CATEGORY_LABELS, DEFAULT_AS_OF, OUTPUTS, ROOT, STATES

app = FastAPI()
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
PAGE = Template((ROOT / "web" / "index.html").read_text(encoding="utf-8"))

STATUS = {
    "applies": ("Applies", "status-applies"),
    "superseded": ("Overridden by local rule", "status-superseded"),
    "not_yet_effective": ("Not in force yet", "status-not-yet"),
    "pending": ("Pending bill, not law", "status-pending"),
    "unknown": ("Unknown: data missing", "status-unknown"),
}


def load():
    rules_file, stacks_file = OUTPUTS / "rules_internal.json", CACHE / "stacks.json"
    if not rules_file.exists() or not stacks_file.exists():
        return None, None
    return [r for r in json.loads(rules_file.read_text())["rules"] if not r.get("incoming")], json.loads(stacks_file.read_text())


def options(stacks: dict, selected: str) -> str:
    groups: dict[str, list[str]] = {}
    for aid, s in stacks.items():
        city = s["stack"]["city"] or f"Unresolved ({s['state']})"
        sel = " selected" if aid == selected else ""
        groups.setdefault(city, []).append(f'<option value="{escape(aid)}"{sel}>{escape(aid)} · {escape(s["street"])}, {escape(s["postal_city"])}</option>')
    return "".join(f'<optgroup label="{escape(g)}">{"".join(o)}</optgroup>' for g, o in sorted(groups.items()))


def fact(v) -> str:
    return escape(str(v)) if v is not None else '<span class="unknown">unknown</span>'


def card(entry: dict, rule: dict, as_of: str) -> str:
    label, cls = STATUS[entry["result"]]
    if entry["result"] == "not_yet_effective":
        label += f" (from {rule['effective_date']})"
    conflict = ""
    if entry["conflict_flag"]:
        conflict = '<p class="conflict-warning"><strong>Human review flagged.</strong> Possible state/local conflict, preemption or source ambiguity. See the explanation and evidence; this is not a determination that the local rule is invalid.</p>'
    key = f'<p class="key-value"><span>Key value:</span> {escape(rule["key_value"])}</p>' if rule.get("key_value") else ""
    retrieved = escape((rule.get("retrieved_at") or "").replace("T", " ")) or "date not recorded"
    eff = f" · effective {escape(rule['effective_date'])}" if rule.get("effective_date") else ""
    eff += f" · through {escape(rule['end_date'])}" if rule.get("end_date") else ""
    support = "".join(f'<li><a href="{escape(e["source_url"])}">{escape(e["source_doc_id"])}</a> · retrieved {escape(e["retrieved_at"])}<p>{escape(e["reason"])}</p><blockquote class="evidence-quote">{escape(e["quoted_span"])}</blockquote></li>'
                      for e in rule.get("supporting_evidence", []))
    derivation = f'<p>{escape(rule["effective_date_derivation"])}</p>' if rule.get("effective_date_derivation") else ""
    evidence_html = f'<details><summary>Temporal and coverage evidence</summary>{derivation}<ul class="evidence-list">{support}</ul></details>' if support or derivation else ""
    return f"""
    <article class="rule-card">
      <div class="rule-meta">
        <span class="status {cls}">{escape(label)}</span>
        <span class="rule-context">{escape(rule['jurisdiction'])} · {escape(rule['level'])} rule · as of {escape(as_of)}</span>
      </div>
      <h3 class="rule-title">{escape(rule['title'])}</h3>
      <p class="rule-requirement">{escape(rule['requirement'])}</p>
      {key}
      <p class="why-result"><span>Why this result:</span> {escape(entry['explanation'])}</p>
      {conflict}
      <p class="citation"><strong>{escape(rule['citation'])}</strong>{eff}</p>
      <p class="source-note">Source {escape(rule['source_doc_id'] or '')}: <a href="{escape(rule['source_url'])}">{escape(rule['source_url'])}</a> · retrieved {retrieved}</p>
      <details>
        <summary>Quoted text from the law</summary>
        <blockquote class="quoted-text">{escape(rule['quoted_span'])}</blockquote>
      </details>
      {evidence_html}
    </article>"""


def body(rules: list[dict], rec: dict, aid: str, as_of: str) -> str:
    st = rec["stack"]
    parts = [STATES.get(st["state"], st["state"] or "unknown state")]
    if st.get("county"):
        parts.append(st["county"])
    parts.append(st["city"].split(",")[0] if st["city"] else (f"{st['place']} (no city rules in scope)" if st.get("place") else "city not resolved"))
    stack_html = " <span class='crumb' aria-hidden='true'>›</span> ".join(escape(p) for p in parts)
    note = "" if rec["geocoded"] else '<p class="uncertainty-note">The Census geocoder could not match this address, so only state rules are shown. The postal city is not used to guess the legal city.</p>'
    results = evaluate(rules, rec, as_of)
    rmap = {r["team_rule_id"]: r for r in rules}
    order = {"applies": 0, "superseded": 1, "unknown": 2, "not_yet_effective": 3, "pending": 4}
    sections, empty = [], []
    for cat in CATEGORIES:
        items = sorted((e for e in results if rmap[e["team_rule_id"]]["category"] == cat), key=lambda e: (order[e["result"]], rmap[e["team_rule_id"]]["level"] != "city"))
        if not items:
            empty.append(CATEGORY_LABELS[cat])
            continue
        sections.append(f'<section class="category-section"><h2 class="section-title">{escape(CATEGORY_LABELS[cat])}</h2><div class="rule-list">{"".join(card(e, rmap[e["team_rule_id"]], as_of) for e in items)}</div></section>')
    none = ""
    if empty:
        none = f'<p class="empty-state">No operative rule found for this date in the available captured text for: {escape(", ".join(empty))}. Missing or ended sources do not mean there is no legal protection.</p>'
    inventory_file = OUTPUTS / "source_inventory.json"
    limitation = ""
    if inventory_file.exists():
        inventory = json.loads(inventory_file.read_text())
        jurisdictions = {st["state"], st.get("city")}
        missing = [d for d in inventory["missing_or_link_only"] if any(j and j in (d.get("jurisdictions") or "") for j in jurisdictions)]
        if missing:
            missing_html = "".join(f'<li>{escape(d["doc_id"])} · {escape(d.get("title") or d["url"])} ({escape(d.get("status") or "missing")})</li>' for d in missing)
            limitation = f'<details class="source-limitations"><summary>Source limitations: {len(missing)} original sources missing or link-only</summary><p>Some gaps have targeted public supplements. Others remain missing; do not interpret an absent rule as no law. <a href="/downloads/source_inventory.json">Source inventory</a></p><ul>{missing_html}</ul></details>'
    return f"""
    <section class="answer-panel">
      <p class="answer-kicker">Answer as of {escape(as_of)}</p>
      <h2 class="answer-address">{escape(rec['street'])}, {escape(rec['postal_city'])}, {escape(rec['state'])} {escape(rec['zip'])}</h2>
      <p class="jurisdiction">{stack_html}</p>
      {note}
      <dl class="fact-grid">
        <div><dt>Year built</dt><dd>{fact(rec['year_built'])}</dd></div>
        <div><dt>Units</dt><dd>{fact(rec['units'])}</dd></div>
        <div><dt>Use</dt><dd>{fact(rec.get('use_description'))}</dd></div>
      </dl>
      <p class="building-disclosure">Building facts: {escape(rec.get('source_dataset') or 'public assessor data')} · retrieved {escape(rec.get('retrieved_at') or 'not recorded')}. Assessor construction year is not an exact certificate date. Jurisdiction from the Census Geocoder{': ' + escape(rec['matched_address']) if rec.get('matched_address') else ''}. Quotes are exact slices of the source documents.</p>
    </section>
    {limitation}
    {''.join(sections)}
    {none}"""


@app.get("/", response_class=HTMLResponse)
def index(address_id: str | None = None, as_of: str = DEFAULT_AS_OF) -> str:
    rules, stacks = load()
    if rules is None:
        msg = '<p class="empty-state">No internal outputs yet. Run <code>uv run python -m src.pipeline</code> first.</p>'
        return PAGE.substitute(options="", as_of=DEFAULT_AS_OF, body=msg)
    try:
        date.fromisoformat(as_of if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of or "") else "")
    except ValueError:
        raise HTTPException(400, "as_of must be a valid YYYY-MM-DD date")
    if address_id is not None and address_id not in stacks:
        raise HTTPException(404, "Unknown sample address_id")
    aid = address_id or next(iter(stacks))
    return PAGE.substitute(options=options(stacks, aid), as_of=as_of, body=body(rules, stacks[aid], aid, as_of))


@app.get("/api/lookup/{address_id}")
def lookup(address_id: str, as_of: str = DEFAULT_AS_OF):
    rules, stacks = load()
    if rules is None:
        raise HTTPException(503, "Run pipeline first")
    if address_id not in stacks:
        raise HTTPException(404, "Unknown sample address_id")
    try:
        date.fromisoformat(as_of if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of) else "")
    except ValueError:
        raise HTTPException(400, "as_of must be a valid YYYY-MM-DD date")
    results = evaluate(rules, stacks[address_id], as_of)
    ids = {e["team_rule_id"] for e in results}
    return {"address_id": address_id, "as_of": as_of, "results": results,
            "rules": [r for r in rules if r["team_rule_id"] in ids], "building": stacks[address_id]}


@app.get("/downloads/{filename}")
def download(filename: str):
    if filename not in {"rules.json", "lookups.json", "changes.json", "source_inventory.json", "validation.json"}:
        raise HTTPException(404, "Unknown download")
    path = OUTPUTS / filename
    if not path.exists():
        raise HTTPException(503, "Run pipeline first")
    return FileResponse(path, filename=filename, media_type="application/json")


@app.get("/method-note")
def method_note():
    return FileResponse(ROOT / "docs" / "method-note.pdf", media_type="application/pdf", filename="method-note.pdf")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
