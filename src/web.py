"""Local page. Reads outputs/rules.json and the cached stacks, calls apply.evaluate. Never calls the model or Census."""

import csv
import json
import re
from datetime import date
from html import escape
from string import Template

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .apply import evaluate
from .config import CACHE, CATEGORIES, CATEGORY_LABELS, CORPUS_DIR, DEFAULT_AS_OF, FETCH_LOG, FETCHED, MANIFEST, OUTPUTS, ROOT, STATES

app = FastAPI()
if OUTPUTS.exists():
    app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
PAGE = Template((ROOT / "web" / "index.html").read_text(encoding="utf-8"))

STATUS = {
    "applies": ("Applies", "bg-pistachio-200 text-forest border-pistachio-300"),
    "superseded": ("Overridden by local rule", "bg-sand text-forest/80 border-amber-200/80"),
    "not_yet_effective": ("Not in force yet", "bg-amber-100 text-amber-950 border-amber-300"),
    "pending": ("Pending bill, not law", "bg-sky-100 text-sky-950 border-sky-300"),
    "unknown": ("Unknown: data missing", "bg-violet-100 text-violet-950 border-violet-300"),
}


def source_limitations_count() -> int:
    n = 0
    for row in csv.DictReader(MANIFEST.open(encoding="utf-8")):
        doc_id = row["doc_id"]
        has_text = (CORPUS_DIR / "text" / f"{doc_id}.txt").exists() or (FETCHED / f"{doc_id}.txt").exists()
        status = row.get("status", "")
        if status == "link-only" and not has_text:
            n += 1
        elif status != "ok" and not has_text:
            n += 1
    return n


def load():
    rules_file, stacks_file = OUTPUTS / "rules.json", CACHE / "stacks.json"
    if not rules_file.exists() or not stacks_file.exists():
        return None, None
    retrieved = {row["doc_id"]: row["retrieved_at"] for row in csv.DictReader(MANIFEST.open(encoding="utf-8"))}
    if FETCH_LOG.exists():
        retrieved.update({row["doc_id"]: row["retrieved_at"] for row in csv.DictReader(FETCH_LOG.open(encoding="utf-8")) if row["status"] == "ok"})
    rules = json.loads(rules_file.read_text())["rules"]
    for rule in rules:
        rule["retrieved_at"] = retrieved.get(rule.get("source_doc_id"))
    return rules, json.loads(stacks_file.read_text())


def options(stacks: dict, selected: str) -> str:
    groups: dict[str, list[str]] = {}
    for aid, s in stacks.items():
        city = s["stack"]["city"] or f"Unresolved ({s['state']})"
        sel = " selected" if aid == selected else ""
        groups.setdefault(city, []).append(
            f'<option value="{escape(aid)}"{sel}>{escape(aid)} - {escape(s["street"])}, {escape(s["postal_city"])}</option>'
        )
    return "".join(f'<optgroup label="{escape(g)}">{"".join(o)}</optgroup>' for g, o in sorted(groups.items()))


def fact(v) -> str:
    return f'<span class="font-semibold text-forest">{escape(str(v))}</span>' if v is not None else '<span class="font-semibold text-violet-800">unknown</span>'


def card(entry: dict, rule: dict) -> str:
    label, cls = STATUS[entry["result"]]
    if entry["result"] == "not_yet_effective":
        label += f" (from {rule['effective_date']})"
    conflict = ""
    if entry["conflict_flag"]:
        conflict = '<p class="mt-3 text-sm bg-rose-50 border border-rose-200 text-rose-900 rounded-lg px-3 py-2"><strong>Conflict flagged for human review.</strong> A local rule and a state rule on the same subject disagree or one may preempt the other.</p>'
    key = f'<p class="mt-1 text-sm text-forest/80"><span class="text-forest/55">Key value:</span> {escape(rule["key_value"])}</p>' if rule.get("key_value") else ""
    retrieved = escape((rule.get("retrieved_at") or "").replace("T", " ")) or "date not recorded"
    eff = f" · effective {escape(rule['effective_date'])}" if rule.get("effective_date") else ""
    return f"""
    <article class="bg-white border border-pistachio-300/70 rounded-xl p-5 shadow-sm">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs border rounded-full px-2.5 py-0.5 font-semibold {cls}">{escape(label)}</span>
        <span class="text-xs text-forest/55">{escape(rule['jurisdiction'])} · {escape(rule['level'])} rule</span>
      </div>
      <h3 class="mt-2 text-lg font-semibold text-forest">{escape(rule['title'])}</h3>
      <p class="mt-1 text-forest/90 leading-relaxed">{escape(rule['requirement'])}</p>
      {key}
      <p class="mt-2 text-sm text-forest/80"><span class="text-forest/55">Why this result:</span> {escape(entry['explanation'])}</p>
      {conflict}
      <p class="mt-3 text-sm text-forest"><span class="font-semibold">{escape(rule['citation'])}</span>{eff}</p>
      <p class="text-xs text-forest/55 mt-1">Source {escape(rule['source_doc_id'] or '')}: <a class="text-forest underline underline-offset-2 break-all hover:text-forest-light" href="{escape(rule['source_url'])}">{escape(rule['source_url'])}</a> · retrieved {retrieved}</p>
      <details class="mt-3 text-sm">
        <summary class="cursor-pointer font-medium text-forest/75 hover:text-forest">Quoted text from the law</summary>
        <blockquote class="mt-2 border-l-4 border-pistachio-400 pl-3 text-forest/85 whitespace-pre-line leading-relaxed">{escape(rule['quoted_span'])}</blockquote>
      </details>
    </article>"""


def body(rules: list[dict], rec: dict, aid: str, as_of: str) -> str:
    st = rec["stack"]
    parts = [STATES.get(st["state"], st["state"] or "unknown state")]
    if st.get("county"):
        parts.append(st["county"])
    parts.append(st["city"].split(",")[0] if st["city"] else (f"{st['place']} (no city rules in scope)" if st.get("place") else "city not resolved"))
    stack_html = " <span class='text-forest/35'>›</span> ".join(f'<span class="text-forest/75">{escape(p)}</span>' for p in parts)
    note = "" if rec["geocoded"] else '<p class="text-sm text-violet-900 bg-violet-50 border border-violet-200 rounded-lg px-3 py-2 mt-3">The Census geocoder could not match this address, so only state rules are shown. The postal city is not used to guess the legal city.</p>'
    results = evaluate(rules, rec, as_of)
    rmap = {r["team_rule_id"]: r for r in rules}
    order = {"applies": 0, "superseded": 1, "unknown": 2, "not_yet_effective": 3, "pending": 4}
    sections, empty = [], []
    for cat in CATEGORIES:
        items = sorted((e for e in results if rmap[e["team_rule_id"]]["category"] == cat), key=lambda e: (order[e["result"]], rmap[e["team_rule_id"]]["level"] != "city"))
        if not items:
            empty.append(CATEGORY_LABELS[cat])
            continue
        sections.append(
            f'<section class="mt-8"><h2 class="text-xs font-bold uppercase tracking-[0.15em] text-forest/50">{escape(CATEGORY_LABELS[cat])}</h2>'
            f'<div class="mt-3 space-y-3">{"".join(card(e, rmap[e["team_rule_id"]]) for e in items)}</div></section>'
        )
    none = ""
    if empty:
        none = f'<p class="mt-8 text-sm text-forest/75">No rule found at the state or city level in the supplied corpus for: {escape(", ".join(empty))}.</p>'
    return f"""
    <section class="mt-6 bg-white border border-pistachio-300/60 rounded-xl p-5 sm:p-6 shadow-sm">
      <p class="text-[11px] font-bold text-forest/45 uppercase tracking-[0.2em]">Answer as of {escape(as_of)}</p>
      <p class="mt-2 text-xl sm:text-2xl font-serif font-bold text-forest leading-snug">{escape(rec['street'])}, {escape(rec['postal_city'])}, {escape(rec['state'])} {escape(rec['zip'])}</p>
      <p class="mt-2 text-sm">{stack_html}</p>
      {note}
      <dl class="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm border-t border-pistachio-200/80 pt-4">
        <div><dt class="text-forest/55 font-medium">Year built</dt><dd class="mt-0.5">{fact(rec['year_built'])}</dd></div>
        <div><dt class="text-forest/55 font-medium">Units</dt><dd class="mt-0.5">{fact(rec['units'])}</dd></div>
        <div><dt class="text-forest/55 font-medium">Use</dt><dd class="mt-0.5">{fact(rec.get('use_description'))}</dd></div>
      </dl>
      <p class="mt-4 text-xs text-forest/55 leading-relaxed">Building facts: {escape(rec.get('source_dataset') or 'public assessor data')}. Jurisdiction from the Census Geocoder{': ' + escape(rec['matched_address']) if rec.get('matched_address') else ''}. Quotes are exact slices of the source documents.</p>
    </section>
    {''.join(sections)}
    {none}"""


@app.get("/", response_class=HTMLResponse)
def index(address_id: str | None = None, as_of: str = DEFAULT_AS_OF) -> str:
    rules, stacks = load()
    if rules is None:
        msg = '<p class="mt-6 bg-white border border-pistachio-300/60 rounded-xl p-5 text-forest">No outputs yet. Run <code class="bg-pistachio-100 px-1 rounded">uv run --env-file .env python -m src.pipeline</code> first.</p>'
        return PAGE.substitute(options="", as_of=DEFAULT_AS_OF, body=msg, source_limitations=str(source_limitations_count()))
    try:
        date.fromisoformat(as_of if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of or "") else "")
    except ValueError:
        as_of = DEFAULT_AS_OF
    aid = address_id if address_id in stacks else next(iter(stacks))
    return PAGE.substitute(
        options=options(stacks, aid),
        as_of=as_of,
        body=body(rules, stacks[aid], aid, as_of),
        source_limitations=str(source_limitations_count()),
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
