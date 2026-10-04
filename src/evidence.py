"""Deterministic, source-guarded repairs to cached extraction.

No address sets or expected test results live here. Dates and supplemental
provisions are parsed from captured public text; every repair records evidence.
"""

import copy
import hashlib
import json
import re
from datetime import date, timedelta

from .config import ROOT
from .extract import citation_key, ground_quote, normalize

SUPPLEMENTAL = ROOT / "data" / "supplemental"
MONTHS = {name: i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), 1)}
DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
PREDICATES = (
    "built_on_or_before", "built_after", "exempt_if_newer_than_years",
    "min_units", "max_units", "exemption_max_units", "facts_required",
    "yields_to_local", "caps_rent", "exemption_note",
)


def parse_date(value):
    value = normalize(value).replace(",", "")
    month, day, year = value.split()
    month_number = MONTHS.get(month) or next(n for name, n in MONTHS.items() if name[:3] == month)
    return date(int(year), month_number, int(day)).isoformat()


def coverage_identity(rule):
    """Different conditions/exemptions are different branches, not duplicates."""
    values = {key: rule.get(key) for key in PREDICATES}
    values["facts_required"] = sorted(values.get("facts_required") or [])
    return json.dumps(values, sort_keys=True)


def sources():
    records = json.loads((SUPPLEMENTAL / "manifest.json").read_text())
    return {r["doc_id"]: {**r, "text": (SUPPLEMENTAL / r["text_file"]).read_text()} for r in records}


def evidence(doc, span, reason):
    exact = span if span in doc["text"] else ground_quote(span, doc["text"])
    if not exact:
        raise ValueError(f"Evidence not found in {doc['doc_id']}: {span[:80]}")
    return {"source_doc_id": doc["doc_id"], "source_url": doc.get("url"),
            "retrieved_at": doc.get("retrieved_at"), "quoted_span": exact, "reason": reason}


def extract_supplemental(supp):
    """Small transparent grammar for adopted prohibitions and a failed petition."""
    out = []
    for sid in ("S-HOB-ALG", "S-JC-ALG", "S-SD-ALG", "S-MA-BALLOT"):
        d = supp[sid]
        text = d["text"]
        if sid == "S-MA-BALLOT":
            m = re.search(r"We\s+remand the matter.*?Statewide election ballot\.", text, re.S)
            if not m:
                raise ValueError("Failed initiative disposition missing")
            category, status = "rent_increase_limits", "failed"
            cite = "SJC-13893" if "SJC-13893" in text else "Cella v. Attorney General"
            title = "Rent-control initiative petition 25-21: certification invalid"
        else:
            category, status = "algorithmic_rent_setting", "enacted"
            if sid == "S-HOB-ALG":
                m = re.search(r"Landlords who rent any residential dwelling unit.*?algorithmic pricing\.", text, re.S)
                cite = "Hoboken City Code § 154-8"
            elif sid == "S-JC-ALG":
                m = re.search(r"It is unlawful for any real estate lessor.*?Service Provider\.", text, re.S)
                cite = "Ord. 25-057"
            else:
                m = re.search(r"It is unlawful for a .*? to use an .*?residential rental property\.", text, re.S)
                cite = "San Diego Municipal Code § 98.1103"
            if not m:
                raise ValueError(f"Operative prohibition missing in {sid}")
            title = "Algorithmic rent-setting prohibition"
        quote = m.group(0)
        rule = {
            "jurisdiction": d["jurisdictions"], "category": category, "status": status,
            "citation": cite, "title": title, "quote": quote, "summary": normalize(quote),
            "source_doc_id": sid, "source_url": d["url"], "retrieved_at": d["retrieved_at"],
            "incoming": False, "_hint_match": True, "facts_required": [], "caps_rent": False,
            "key_value": None, "effective_date": None, "coverage_text": "Residential rentals",
            "exemption_note": None, "also_found_in": [], "supporting_evidence": [],
        }
        if sid == "S-HOB-ALG":
            status_doc = supp["S-HOB-STATUS"]
            rule["supporting_evidence"].append(evidence(status_doc,
                "July 10, 2025", "Official announcement confirms ordinance is in operation by this date; publication date not supplied."))
            rule["in_force_by"] = "2025-07-10"
            rule["enacted_date"] = "2025-07-09"
            rule["uncertainty_note"] = "Adopted July 9; publication-dependent commencement day is not verified. Source heading says 158-2 but body says 154-8; codification needs human review."
            rule["conflict_flag"] = True
            rule["penalty"] = "Fine not exceeding $2,000 or community service not exceeding 90 days."
        elif sid == "S-JC-ALG":
            m = re.search(r"Adopted on second and final reading after hearing on\s+([A-Za-z]+ \d+ \d{4})", text)
            rule["enacted_date"] = parse_date(m[1])
            # The later adopted amendment treats the original prohibition as
            # existing law. This is a conservative in-force-by anchor, not a
            # claim that the original ban commenced on either adoption day.
            status_doc = supp["S-JC-STATUS"]
            adopted = re.search(r"Adopted on second and final reading after hearing on\s+([A-Za-z]+ \d+ \d{4})",
                                status_doc["text"])
            operative = re.search(r"having landlords proactively declare that they are not violating the law.*?otherwise;", status_doc["text"], re.S)
            if not adopted or not operative:
                raise ValueError("Jersey City in-force anchor not established")
            rule["in_force_by"] = parse_date(adopted[1])
            rule["supporting_evidence"].extend([
                evidence(status_doc, adopted[0], "Later adopted amendment's date, used conservatively as an in-force-by anchor"),
                evidence(status_doc, operative[0], "Later amendment treats the existing ban as law being enforced"),
            ])
            rule["uncertainty_note"] = (
                f"Final adoption verified; precise original publication/commencement is unverified. "
                f"A later amendment establishes that the ban is in force by {rule['in_force_by']}; "
                "earlier post-adoption queries remain unknown. Definitions exclude care/detention facilities and same-owner-only coordination.")
            rule["penalty"] = "Subsequent violations: $100–$2,000; each day is a separate violation."
        elif sid == "S-SD-ALG":
            m = re.search(r"effective (\d+)-(\d+)-(\d{4})", text)
            rule["effective_date"] = date(int(m[3]), int(m[1]), int(m[2])).isoformat()
            rule["effective_date_evidence"] = m[0]
            rule["penalty"] = "Civil penalties up to $1,000 per violation; costs and reasonable attorney fees."
        else:
            m = re.search(r"June\s+23,\s+2026", text)
            if not m:
                raise ValueError("Decision date missing")
            rule["failed_date"] = parse_date(m[0])
            rule["supporting_evidence"].append(evidence(d, m[0], "Court decision date"))
            rule["coverage_text"] = "Failed proposal, never an operative rent cap"
        out.append(rule)
    return out


def repair(rules, docs, audit):
    supp = sources()
    all_docs = {d["doc_id"]: {**d, "text": d["path"].read_text()} for d in docs}
    all_docs.update(supp)
    out = []
    for original in rules + extract_supplemental(supp):
        r = copy.deepcopy(original)
        d = all_docs[r["source_doc_id"]]
        text, q = normalize(d["text"]), normalize(r["quote"])
        notes = r.setdefault("supporting_evidence", [])
        # Reject employment provisions that the model misclassified as housing.
        if "application for employment" in q.lower() or "For an employer" in q:
            audit.append({"decision": "dropped", "source_doc_id": r["source_doc_id"],
                          "reason": "Employment-only provision, not housing"})
            continue
        # A codified cap is preferred to an announcement about the same bill.
        if (r["jurisdiction"] == "CA" and r["category"] == "security_deposits" and
                "Assembly Bill" in r["citation"] and
                any(term in q.lower() for term in ("one month's rent", "two months' rent"))):
            if any(x["jurisdiction"] == "CA" and "1950.5" in x["citation"] for x in rules):
                audit.append({"decision": "merged", "source_doc_id": r["source_doc_id"],
                              "reason": "AB 12 announcement duplicates codified deposit cap; retained as supporting evidence"})
                continue
        # Non-operative navigation headings are not sufficient law.
        if len(q.split()) < 8 and not re.search(r"\d+(?:\.\d+)?%", q):
            audit.append({"decision": "dropped", "source_doc_id": r["source_doc_id"],
                          "reason": "Heading without an operative requirement"})
            continue
        interval = re.search(rf"({DATE})\s*(?:,?\s*through|[–—-])\s*({DATE})", q)
        if interval:
            r["effective_date"], r["end_date"] = map(parse_date, interval.groups())
            r["effective_date_evidence"] = ground_quote(interval[0], d["text"])
            r["end_date_evidence"] = r["effective_date_evidence"]
            notes.append(evidence(d, interval[0], "Inclusive operative date interval"))
        # Dates must have evidence, not just a model assertion.
        elif r.get("effective_date") and not r.get("effective_date_evidence"):
            r["effective_date"] = None
            r["uncertainty_note"] = "Effective day not stated or not grounded; no historical commencement assumed."
        if r["jurisdiction"] == "CA" and r["category"] == "algorithmic_rent_setting":
            approval = re.search(rf"Approved\s+by\s+Governor\s+({DATE})", text, re.I)
            if not approval:
                raise ValueError("CA enactment evidence missing")
            approved = parse_date(approval[1])
            if re.search(r"urgency statute|take effect immediately|special session", text, re.I):
                raise ValueError("Ordinary CA commencement cannot be used for exceptional legislation")
            # Odd-year regular-session bills: Article IV 8(c)(2).
            authority = supp["S-CA-COMMENCEMENT"]
            clause = re.search(r"\(2\)\s+A statute, other than a statute establishing.*?unless, before January 1", authority["text"], re.S)
            if not clause or date.fromisoformat(approved).year % 2 != 1:
                raise ValueError("CA regular-session commencement authority unavailable")
            r["effective_date"] = f"{date.fromisoformat(approved).year + 1}-01-01"
            r["effective_date_evidence"] = ground_quote(approval[0], d["text"])
            r["effective_date_derivation"] = "Odd-year regular-session chaptered statute without urgency or special commencement: January 1 after enactment under Cal. Const. Art. IV §8(c)(2); assumes no referendum delay."
            notes.extend([evidence(d, approval[0], "Enactment anchor"),
                          evidence(authority, clause[0], "General legal commencement authority, not a corpus quote")])
        # The deposit amount started in July 2024, not the later section amendment.
        if r["jurisdiction"] == "CA" and "1950.5" in r["citation"]:
            m = re.search(rf"This subdivision shall not apply.*?before ({DATE})", text)
            if m:
                r["effective_date"] = parse_date(m[1])
                r["effective_date_evidence"] = ground_quote(m[0], d["text"])
                notes.append(evidence(d, m[0], "Provision-specific applicability; amendment footer is not the cap's start"))
                r["uncertainty_note"] = "One-month cap for security demanded on/after July 1, 2024; prior deposits and service-member exceptions depend on transaction facts."
        repeal = re.search(rf"remain in effect (?:only )?until ({DATE})", text)
        if repeal:
            r["end_date"] = (date.fromisoformat(parse_date(repeal[1])) - timedelta(days=1)).isoformat()
            r["end_date_evidence"] = ground_quote(repeal[0], d["text"])
            notes.append(evidence(d, repeal[0], "Repeal on the stated day; final operative day is previous day"))
        if (r["jurisdiction"] == "MA" and r["category"] == "rent_increase_limits" and
                r["status"] == "enacted" and not r.get("caps_rent")):
            r.update(exemption_max_units=None, facts_required=[])
            r["coverage_text"] = "Statewide bar on mandatory local rent control; voluntary programs do not impose a cap."
        if "Guide to Coverage under Berkeley" in text:
            # Keep every table row as its own branch. Rooms are not dwelling
            # units, and the model's May 31 cutoff is not stated in this guide.
            if "built before 1980" in q:
                r["built_on_or_before"] = "1979-12-31"
                notes.append(evidence(d, r["quote"], "Guide says before 1980; no May 31 cutoff is supported"))
            if "Rooming house:" in q:
                r["min_units"] = None
                r["facts_required"] = [f for f in r.get("facts_required", []) if f != "units"]
                r["uncertainty_note"] = "Five rented rooms with separate leases is not five dwelling units; room/lease facts are absent."
            r["facts_required"] = sorted(set(r.get("facts_required", []) + ["other"]))
            exceptions = re.search(r'"Golden Duplex".*?Nonprofit Cooperative Exempt No No No No', text)
            if exceptions:
                notes.append(evidence(d, exceptions[0], "Guide-wide unit/owner/use exemptions need verification in each coverage branch"))
        # In-force local rate bulletins require local rent-control coverage.
        if r["jurisdiction"] == "San Francisco, CA" and r["category"] == "rent_increase_limits":
            if "rent-controlled" in text.lower() or "Allowable Rent Increase" in text:
                authority = supp["S-SF-RATES"]
                m = re.search(r"Newly constructed rental units.*?June 13, 1979.*?(?:\n\n|;)", authority["text"], re.S | re.I)
                if not m:
                    # The public ordinance contains this as clause (5).
                    m = re.search(r"An owner of a residential dwelling or unit which is newly constructed.*?substantial rehabilitation", authority["text"], re.S)
                if not m:
                    raise ValueError("SF coverage evidence missing")
                r["built_on_or_before"] = "1979-06-13"
                r["facts_required"] = ["year_built", "other"]
                r["coverage_text"] = "Rent-controlled units; certificate cutoff and rehabilitation, subsidy or unit-level exemptions require verification."
                notes.append(evidence(authority, m[0], "Rent-control certificate cutoff"))
        if r["jurisdiction"] == "Los Angeles, CA" and r["category"] == "rent_increase_limits":
            anchor = next((x for x in rules if x["jurisdiction"] == r["jurisdiction"] and x.get("built_on_or_before")), None)
            if anchor:
                r["built_on_or_before"] = anchor["built_on_or_before"]
                r["facts_required"] = ["year_built", "use_code"]
                r["coverage_text"] = anchor.get("coverage_text")
                ad = all_docs[anchor["source_doc_id"]]
                span = ground_quote(anchor.get("coverage_text") or "", ad["text"])
                if span:
                    notes.append(evidence(ad, span, "RSO building cutoff"))
        # A civil code reference in a city guide yields to the actual statute.
        if r["jurisdiction"] == "CA" and "1950.6" in r["citation"]:
            official = next((x for x in rules if x["source_doc_id"] == "D026"), None)
            if official:
                r = copy.deepcopy(official)
                r["also_found_in"] = sorted(set(r.get("also_found_in", []) + ["D005"]))
                r["uncertainty_note"] = "No single official 2026 dollar cap in the pack. $30 statutory base is CPI-adjustable; do not treat a secondary $68.96 estimate as authoritative."
        if r["jurisdiction"] == "NJ" and r["category"] == "algorithmic_rent_setting":
            approval = re.search(rf"approved ({DATE})", text, re.I)
            clause = re.search(r"take effect on the first day of the twelfth month next following.*?enactment", text, re.I)
            if approval and clause:
                start = date.fromisoformat(parse_date(approval[1]))
                r["effective_date"] = date(start.year + 1, start.month, 1).isoformat()
                r["effective_date_derivation"] = "First day of twelfth month following enactment: enactment month excluded, +12 calendar months."
                r["effective_date_evidence"] = ground_quote(clause[0], d["text"])
                notes.extend([evidence(d, approval[0], "Approval anchor"),
                              evidence(d, clause[0], "Relative commencement clause")])
            r["possible_local_preemption"] = True
        if r["category"] == "application_screening_fees" and "one-family or two-family dwelling" in text:
            r["unconditional_small_building_exemption"] = True
            r["facts_required"] = [f for f in r.get("facts_required", []) if f != "owner_type"]
            m = re.search(r"located in a one-family or two-family dwelling.*?for rent", text)
            notes.append(evidence(d, m[0], "Dwelling-size exemption is not conditioned on owner occupancy"))
        # Relative statutory commencement is parsed for any NJ provision, not
        # just the FAIR Act. The fourth-month screening-fee law uses the same
        # construction as the twelfth-month FAIR Act.
        if r["jurisdiction"] == "NJ":
            anchor = re.search(rf"Approved ({DATE})", text, re.I)
            relative = re.search(r"take effect on the first day of the (first|second|third|fourth|sixth|twelfth) month next following the date of enactment", text, re.I)
            if anchor and relative:
                offset = {"first": 1, "second": 2, "third": 3, "fourth": 4, "sixth": 6, "twelfth": 12}[relative[1].lower()]
                start = date.fromisoformat(parse_date(anchor[1].title()))
                index = start.year * 12 + start.month - 1 + offset
                r["effective_date"] = date(index // 12, index % 12 + 1, 1).isoformat()
                r["effective_date_evidence"] = ground_quote(relative[0], d["text"])
                r["effective_date_derivation"] = f"First day of {relative[1].lower()} month following enactment: excludes enactment month and adds {offset} calendar months."
                notes.extend([evidence(d, anchor[0], "Approval anchor"),
                              evidence(d, relative[0], "Calendar-month commencement calculation")])
        if r["jurisdiction"] == "San Diego, CA" and r["category"] == "algorithmic_rent_setting" and r["source_doc_id"] != "S-SD-ALG":
            audit.append({"decision": "replaced", "source_doc_id": r["source_doc_id"],
                          "reason": "Draft ordinance with blank passage replaced by published municipal code and actual effective day"})
            continue
        if r["jurisdiction"] == "Berkeley, CA" and r["category"] == "algorithmic_rent_setting":
            r["effective_date"] = None
            r["effective_date_evidence"] = None
            r["historical_start_unverified"] = True
            r["uncertainty_note"] = "Current adopted prohibition verified in municipal code. The earlier ordinance deferred commencement to March 1, 2026, but the subsequent amendment has no verified commencement day here; historical applicability is unknown."
            notes.append(evidence(supp["S-BRK-DATE"],
                "The provisions of this Chapter shall not take effect until March 1, 2026.",
                "Prior-version deferral; not attributed to the later amended ordinance"))
            if "S-BRK-CODE" in supp:
                notes.append(evidence(supp["S-BRK-CODE"],
                    "Ord. 7992-NS", "Published codification confirms adoption of amendment, unlike passed-to-print draft"))
        # A dated introductory phrase in a quotation is stronger than its footer.
        if not r.get("effective_date"):
            explicit = re.search(rf"(?:Starting|Beginning|Effective|For tenancies that begin on or after)\s+({DATE})", q, re.I)
            if explicit:
                r["effective_date"] = parse_date(explicit[1].title())
                r["effective_date_evidence"] = ground_quote(explicit[0], d["text"])
                notes.append(evidence(d, explicit[0], "Provision-specific commencement phrase"))
        # Owner-unit totals and building unit counts must not be conflated.
        if r.get("exemption_max_units") and "collectively" in text and r["category"] == "security_deposits":
            r["unit_exemption_scope"] = "owner_portfolio"
        out.append(r)
    # Supplement current LA annual rate, and recover previous SF annual rate.
    for sid, jur, category, pattern in [
        ("S-LA-RATES", "Los Angeles, CA", "rent_increase_limits",
         rf"THE CALCULATED ANNUAL INCREASE.*?({DATE}) THROUGH ({DATE}) IS THREE.*?PERCENT \(3%\)"),
    ]:
        d = supp[sid]
        m = re.search(pattern, d["text"], re.I | re.S)
        if not m:
            raise ValueError(f"Rate interval missing: {sid}")
        template = next(r for r in out if r["jurisdiction"] == jur and r["category"] == category)
        r = copy.deepcopy(template)
        r.update(source_doc_id=sid, source_url=d["url"], retrieved_at=d["retrieved_at"],
                 citation="Rent Stabilization Ordinance", title="RSO annual allowable increase",
                 quote=m[0], summary="RSO-covered rental units have a 3% annual allowable increase during this period.",
                 effective_date=parse_date(m[1].title()), end_date=parse_date(m[2].title()),
                 key_value="3%", also_found_in=[], effective_date_derivation=None,
                 effective_date_evidence=m[0], end_date_evidence=m[0],
                 supporting_evidence=template.get("supporting_evidence", []) + [evidence(d, m[0], "Current annual rate")])
        out.append(r)
    # LA's official chronology provides historical operative versions, including
    # the period immediately after the moratorium. No invented rate fills gaps.
    d = supp["S-LA-RATES"]
    template = next(r for r in out if r["source_doc_id"] == "S-LA-RATES")
    for m in re.finditer(r"(\d{1,2}/\d{1,2}/\d{2})\s*-\s*(\d{1,2}/\d{1,2}/\d{2})\s*\|\s*(\d+)%", d["text"]):
        def table_date(value):
            month, day, yy = map(int, value.split("/"))
            return date(1900 + yy if yy >= 70 else 2000 + yy, month, day).isoformat()
        start, end = table_date(m[1]), table_date(m[2])
        if any(r["jurisdiction"] == template["jurisdiction"] and r["category"] == template["category"] and
               r.get("effective_date") == start and r.get("end_date") == end for r in out):
            continue
        r = copy.deepcopy(template)
        r.update(quote=m[0], effective_date=start, end_date=end,
                 effective_date_evidence=m[0], end_date_evidence=m[0], key_value=f"{m[3]}%",
                 title="Historical RSO annual allowable increase",
                 summary=f"Annual allowable increase for RSO-covered units is {m[3]}% during this period.",
                 supporting_evidence=template.get("supporting_evidence", [])[:1] + [
                     evidence(d, m[0], "Historical chronology; two-digit years interpreted in published 1979-onward chronology")])
        out.append(r)
    d = all_docs["D080"]
    m = re.search(rf"The annual allowable increase amount effective ({DATE}) through ({DATE}) is ([\d.]+)%", normalize(d["text"]))
    if m:
        template = next(r for r in out if r["source_doc_id"] == "D080")
        r = copy.deepcopy(template)
        r.update(quote=ground_quote(m[0], d["text"]), effective_date=parse_date(m[1]),
                 end_date=parse_date(m[2]), effective_date_evidence=ground_quote(m[0], d["text"]),
                 end_date_evidence=ground_quote(m[0], d["text"]), key_value=f"{m[3]}%",
                 summary=f"Annual allowable increase for rent-controlled units is {m[3]}% during this period.",
                 title="Historical annual allowable increase")
        out.append(r)
    # Only equivalent obligations AND conditions can be merged. A citation is a
    # container for multiple obligations; it is not a provision identity.
    grouped = {}
    for r in out:
        shared = (r["jurisdiction"], r["category"], r.get("effective_date"),
                  r.get("end_date"), coverage_identity(r))
        # Rate announcements can restate the same rate in different words, but
        # the number, period AND covered branch must all agree.
        key = shared + ("rate", r["key_value"]) if (
            r["category"] == "rent_increase_limits" and r.get("end_date") and
            r.get("caps_rent") and r.get("key_value")) else shared + (
            "obligation", citation_key(r["citation"]), normalize(r["quote"]))
        if key not in grouped:
            grouped[key] = r
        else:
            g = grouped[key]
            priority = lambda x: ("codes_display" in x["source_url"], "BillNavClient" in x["source_url"], x.get("_hint_match", False))
            if priority(r) > priority(g):
                r["also_found_in"] = sorted(set(r.get("also_found_in", []) + [g["source_doc_id"]]))
                grouped[key], g = r, r
            g.setdefault("supporting_evidence", []).append(evidence(all_docs[r["source_doc_id"]], r["quote"],
                                                    "Additional grounded wording for the same provision"))
            g["also_found_in"] = sorted(set(g.get("also_found_in", []) + [r["source_doc_id"]]))
            audit.append({"decision": "merged", "source_doc_id": r["source_doc_id"],
                          "reason": "Equivalent provision and operative interval", "into": g["source_doc_id"]})
    return list(grouped.values())


def stable_id(rule):
    identity = "|".join([rule["jurisdiction"], rule["category"], rule["citation"],
                         normalize(rule["quote"]), coverage_identity(rule),
                         rule.get("effective_date") or "", rule.get("end_date") or ""])
    if rule.get("incoming"):
        identity += "|optional-incoming"
    return "r-" + hashlib.sha256(identity.encode()).hexdigest()[:12]


def inventory():
    """Disclose every missing source, even where supplementation closed a gap."""
    import csv
    from .config import MANIFEST
    with MANIFEST.open(newline="") as f:
        records = list(csv.DictReader(f))
    available = [r["doc_id"] for r in records if r["status"] == "ok" and r["text_file"]]
    missing = [{k: r.get(k) for k in ("doc_id", "jurisdictions", "categories", "title", "url", "status", "notes")}
               for r in records if r["doc_id"] not in available]
    return {"available_corpus_documents": available, "missing_or_link_only": missing,
            "supplemental_sources": [{k: v for k, v in d.items() if k != "text"} for d in sources().values()],
            "limitation": "Missing text is not evidence that a law does not exist. Supplements are targeted public captures, not exhaustive legal updates."}