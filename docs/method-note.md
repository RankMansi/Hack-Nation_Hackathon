# Rental Housing Law Navigator — Method Note

**Scope.** The no-hour-16 participant pack; six housing categories; 500 public
assessor addresses in California, New Jersey and Massachusetts. Default date:
2026-10-01. This is an evidence navigator, not legal advice or certification.

**Module A: automated extraction.** Structured model responses are cached by
document content, model and prompt version. Rebuilding uses all 54 valid caches,
without paid calls. Code accepts only source-grounded quotations and citation
identifiers, rejects non-operative headings and employment-only provisions,
merges only equivalent obligations with identical coverage, preserving separate
statutory duties, coverage branches and intervals. Exact source slices and
quotations remain in the audit.

**Module B: jurisdiction and coverage.** Cached public Census geography resolves
state, county and incorporated city. Mailing cities never select laws. Seven
unmatched addresses receive state-only results. Assessor construction years are
proxies, not certificate dates; cutoff-year and missing unit/owner/use/subsidy
facts remain unknown. Conflicting unit descriptions need review. State rules
yield only to warranted protective local provisions. County laws are out of scope.

**Dates and provenance.** Inclusive end dates stop governing the next day.
LA moratorium/annual rates and SF annual-rate versions remain internal for
historical queries, not current submission answers. San Diego's published code
supplies its actual commencement. California's general commencement is supported
separately by Constitution Article IV section 8(c)(2); NJ dates use approval and
calendar-month clauses. Derived dates are labelled calculations, not purported
corpus quotations. The latest section amendment is not automatically the start
of each unchanged requirement.

**Module C and exports.** Change sets come from the evaluator and supplied test
definitions, not hand-listed addresses. T1 covers 250 CA addresses; T2 separates
40 Hoboken and 50 Jersey City addresses; T3 covers 140 NJ addresses and flags 90
possible local conflicts; T4 reports both pending bills for 110 MA addresses;
T5 imposes no rent cap and has an empty set. Required JSON follows schema/template
fields and exports exactly T1–T5. Rich history, joined evidence, penalties and
diagnostics are separate. Rule IDs are stable content identities.

**Source limits.** The pack has 33 missing/link-only sources. Twelve targeted
public captures, outside the unchanged raw pack, include URLs, retrieval times,
methods and hashes. They close specific gaps, not all missing laws; no
prohibited publisher bulk scraping is used. Hoboken/Jersey City exact
commencement remains uncertain; Jersey City is verified in force by 2025-09-24,
not on adoption day. Berkeley's amended historical start is also unknown. Building
facts are never invented. A missing result does not mean no legal protection.

**Reproduce and verify.** Run `uv sync --frozen`, then
`ANTHROPIC_MODEL=claude-sonnet-4-5 uv run --frozen python -m src.pipeline`;
`uv run --frozen python -m unittest discover -s tests -v`. Replit Run starts
the FastAPI demo on port 5000. JSON Schema, exact grounding, all-address T1–T5,
date boundaries, missing facts and demo/API regressions are checked.
`outputs/validation.json` is local evidence, not an official score: the official
scorer/answer key is unavailable. No GitHub push, PR or deployment is performed.