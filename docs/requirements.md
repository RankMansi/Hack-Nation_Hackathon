# Published-requirement checklist

Inputs: participant no-hour-16 PDF (including visual review of the build/submission
page), `data/raw/README.md`, schema/sample, submission templates, manifest,
addresses and `dev/change_tests.json`. Attached notes were hypotheses: this
checkout already applied T1 to 250 CA addresses; original rules numbered 78,
not the count in those notes.

| Published requirement / smaller risk | Implementation and verification |
|---|---|
| Automated extraction, six categories, public text only | Cache revalidation plus evidence grammars; no hand-listed rules/address answer key; exact-source checks |
| No invented citation or non-housing law | Grounding validation; employment criminal-screening provision removed; proposed record drops preserved in audit |
| State/county/incorporated city, no mailing-city inference | Cached Census geography; all 500 IDs checked; seven city-unresolved state-only records |
| Construction/certificate cutoffs and rolling exemptions | Conservative cutoff-year unknown; construction proxy disclosed; boundary/missing-fact tests |
| Unit/owner/use uncertainty | Small-building versus owner-conditioned exemptions distinguished; conflicting recorded unit counts flagged; missing/use/subsidy/rehabilitation facts unknown |
| Appropriate precedence | Protective local rules only; non-cap state bar and pending proposals do not replace enacted caps; no invented global hierarchy |
| Date-sensitive laws, expired/history/failure | Inclusive intervals, chronological LA rates, previous SF rate, actual SD day, MA disposition; every known expiry boundary tested |
| Commencement derivations are public-source supported | CA Constitution Art. IV §8(c)(2) separately captured; NJ approval + relative clause; auditable anchors and exact quotes |
| T1 | All 250 CA addresses: not yet effective 2025-12-31; applies 2026-01-01 and 2026-01-02 |
| T2 | Separate sets: Hoboken 40, Jersey City 50; no Newark leakage |
| T3 | All 140 NJ addresses; before/at/after 2027-07-01; exactly 90 possible local conflicts propagated to lookups |
| T4 | Both distinct S.2983 and H.5222 pending at each of 110 MA addresses |
| T5 | Failed IP 25-21 supported by court disposition; empty affected set; no enacted Boston/Cambridge cap |
| Source/quote/retrieval/as-of/explanation per answer | Internal joined lookups and demo; schema-only submission joins rules by stable ID |
| Minimal schema and templates | Real Draft 2020-12 validation; allowed fields, IDs, sorted sets, five permitted lookup values and exactly T1–T5 |
| Diagnostics outside required files | Internal history/lookups/changes, audit, source inventory, validation, unresolved/failure logs |
| Missing/link-only sources and access terms | All 33 raw gaps disclosed; twelve targeted public captures outside raw; no publisher terms-review/bulk scraping bypass |
| Distinct statutory duties / coverage branches | Original cached D052, D006 and D009 obligations independently retained and exported; same-citation merges require identical obligation and conditions |
| Jersey City historical commencement | Adoption is not commencement; pre-2025-09-24 post-adoption results are unknown, then supported by the later adopted amendment's in-force-by evidence |
| Working plain-language live demo | Existing FastAPI workflow; selector, date, exact quote and temporal evidence details, human-review warnings, downloads, explicit request errors |
| One-page method note and reproducibility | Markdown source + generated one-page PDF; locked dependencies and documented cache-only commands |
| Raw preservation / workspace-only / no hour-16 requirement | No raw modifications, pushes, PRs or deployments; optional incoming excluded from minimal exports and demo |
| Official score | Unavailable, not represented by the local checker |

## Deliberate uncertainty, not claimed completion of missing legal knowledge

The source inventory is exhaustive **for missing pack rows**, not for all laws
in these jurisdictions. Sources requiring publisher access/terms review stay
missing. Current code verifies Berkeley's amendment exists, but the former
March 1 deferral cannot safely establish the amended provision's commencement.
The historical answer stays unknown rather than inventing a start. Adopted
Hoboken/Jersey City ordinances are available, but their precise publication/start
days are not both documented. Those uncertainty notes are retained.

Assessor construction years are not exact certificate dates; there are no owner,
tenancy, registration, subsidy or unit-specific rehabilitation records in this
sample. The system cannot establish those facts, certify legal compliance or
guarantee hidden scoring. Dates outside a captured operative version may have no
answer or an explicit unknown; this does not imply that no legal protection
existed.