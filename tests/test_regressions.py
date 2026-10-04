import copy
import json
import unittest

from fastapi.testclient import TestClient

from src import apply, extract
from src.config import CACHE, DEFAULT_AS_OF, OUTPUTS
from src.submission import active_records
from src.web import app


class CoverageTests(unittest.TestCase):
    def test_cutoff_precision(self):
        self.assertEqual(apply._year_test(None, "1978-10-01", True)[0], apply.UNKNOWN)
        self.assertEqual(apply._year_test(1978, "1978-10-01", True)[0], apply.UNKNOWN)
        self.assertEqual(apply._year_test(1977, "1978-10-01", True)[0], apply.COVERED)
        self.assertEqual(apply._year_test(1979, "1978-10-01", True)[0], apply.NOT_COVERED)
        self.assertEqual(apply._year_test(1978, "1978-12-31", True)[0], apply.COVERED)

    def test_rolling_exemption_changes_with_date(self):
        r = {"coverage_conditions": {"exempt_if_newer_than_years": 15}}
        self.assertEqual(apply.coverage(r, {"year_built": 2011}, "2026-01-01")[0], apply.UNKNOWN)
        self.assertEqual(apply.coverage(r, {"year_built": 2011}, "2025-01-01")[0], apply.NOT_COVERED)
        self.assertEqual(apply.coverage(r, {"year_built": 2011}, "2027-01-01")[0], apply.COVERED)

    def test_missing_units_owner_and_use(self):
        r = {"coverage_conditions": {"exemption_max_units": 4, "facts_required": ["units", "owner_type"]}}
        for facts in ({}, {"units": 2}):
            self.assertEqual(apply.coverage(r, facts, DEFAULT_AS_OF)[0], apply.UNKNOWN)
        self.assertEqual(apply.coverage(r, {"units": 5}, DEFAULT_AS_OF)[0], apply.COVERED)
        self.assertEqual(apply.coverage(r, {"units": 5, "unit_conflict": True}, DEFAULT_AS_OF)[0], apply.UNKNOWN)
        for facts_required in (["use_code"], ["other"], ["owner_type"]):
            self.assertEqual(apply.coverage({"coverage_conditions": {"facts_required": facts_required}},
                                            {}, DEFAULT_AS_OF)[0], apply.UNKNOWN)

    def test_unconditional_small_building_exemption(self):
        r = {"coverage_conditions": {"exemption_max_units": 2}, "unconditional_small_building_exemption": True}
        self.assertEqual(apply.coverage(r, {"units": 2}, DEFAULT_AS_OF)[0], apply.NOT_COVERED)
        self.assertEqual(apply.coverage(r, {"units": 3}, DEFAULT_AS_OF)[0], apply.COVERED)

    def test_partial_fabricated_quote_rejected(self):
        doc = {"doc_id": "test", "hint": "CA", "url": "https://example.org", "retrieved_at": "2026-10-01", "incoming": False}
        text = "Section 123: It is unlawful for landlords to coordinate rental pricing."
        raw = {"category": "algorithmic_rent_setting", "jurisdiction": "CA", "citation": "Section 123",
               "quote": "It is unlawful for landlords to coordinate rental pricing. All tenants receive a million dollars."}
        self.assertIsNone(extract.validate(raw, doc, text, []))


class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads((OUTPUTS / "rules_internal.json").read_text())["rules"]
        cls.stacks = json.loads((CACHE / "stacks.json").read_text())
        cls.client = TestClient(app)

    def result(self, rule, rec, when):
        return next((e["result"] for e in apply.evaluate(self.rules, rec, when)
                     if e["team_rule_id"] == rule["team_rule_id"]), None)

    def test_cached_distinct_obligations_are_independently_exported(self):
        from src.extract import cache_path, load_documents, normalize, validate
        docs = load_documents()
        current_ids = {r["team_rule_id"] for r in active_records(self.rules)}
        for sid, expected in (("D052", 5), ("D006", 6), ("D009", 19)):
            doc = next(d for d in docs if d["doc_id"] == sid)
            proposals = json.loads(cache_path("claude-sonnet-4-5", doc).read_text())["rules"]
            original = [validate(p, doc, doc["path"].read_text(), []) for p in proposals]
            original = [r for r in original if r]
            self.assertEqual(len(original), expected)
            actual = [r for r in self.rules if r["source_doc_id"] == sid]
            self.assertEqual(len(actual), expected, sid)
            # Exact obligation text AND original requirement are retained, not
            # hidden as supporting quotes of a different rule.
            self.assertEqual({(r["category"], normalize(r["quote"]), r["summary"]) for r in original},
                             {(r["category"], normalize(r["quoted_span"]), r["requirement"]) for r in actual}, sid)
            self.assertTrue(all(r["team_rule_id"] in current_ids for r in actual), sid)
            for r in actual:
                rec = next(s for s in self.stacks.values() if
                           r["jurisdiction"] in (s["stack"]["state"], s["stack"]["city"]))
                missing = copy.deepcopy(rec)
                missing.update(year_built=None, units=None, unit_conflict=False, use_code=None)
                self.assertIn(self.result(r, missing, DEFAULT_AS_OF), ("applies", "unknown"), r["title"])
        # Room counts cannot be silently treated as dwelling-unit counts.
        room_branches = [r for r in self.rules if r["source_doc_id"] == "D009" and "Rooming house:" in r["quoted_span"]]
        self.assertEqual(len(room_branches), 3)
        self.assertTrue(all(r["coverage_conditions"]["min_units"] is None and
                            "other" in r["coverage_conditions"]["facts_required"] for r in room_branches))

    def test_same_citation_and_quote_with_different_coverage_is_not_merged(self):
        from src.evidence import coverage_identity, stable_id
        a = {"jurisdiction": "CA", "category": "just_cause_eviction",
             "citation": "Section 1", "quote": "Landlords cannot evict without a just cause.",
             "min_units": 2, "facts_required": ["units"]}
        b = {**a, "min_units": 5}
        self.assertNotEqual(coverage_identity(a), coverage_identity(b))
        self.assertNotEqual(stable_id(a), stable_id(b))
        self.assertEqual(len(extract.dedupe([dict(a, _hint_match=True, source_doc_id="test-a"),
                                           dict(b, _hint_match=True, source_doc_id="test-b")])), 2)

    def test_jersey_city_adoption_is_not_commencement(self):
        r = next(r for r in self.rules if r["source_doc_id"] == "S-JC-ALG")
        rec = next(s for s in self.stacks.values() if s["stack"]["city"] == r["jurisdiction"])
        self.assertEqual(self.result(r, rec, "2025-05-20"), "pending")
        self.assertEqual(self.result(r, rec, "2025-05-21"), "unknown")
        self.assertEqual(self.result(r, rec, "2025-05-22"), "unknown")
        self.assertEqual(self.result(r, rec, "2025-09-23"), "unknown")
        self.assertEqual(self.result(r, rec, "2025-09-24"), "applies")
        self.assertEqual(self.result(r, rec, DEFAULT_AS_OF), "applies")
        self.assertTrue(any(e["source_doc_id"] == "S-JC-STATUS" for e in r["supporting_evidence"]))

    def test_all_expiry_boundaries(self):
        bounded = [r for r in self.rules if r.get("end_date") and r["category"] == "rent_increase_limits"]
        from datetime import date, timedelta
        for rule in bounded:
            rec = next(s for s in self.stacks.values() if
                       rule["jurisdiction"] in (s["stack"]["state"], s["stack"]["city"]))
            final = rule["end_date"]
            after = (date.fromisoformat(final) + timedelta(days=1)).isoformat()
            self.assertIsNone(self.result(rule, rec, after), (rule["team_rule_id"], after))
            # A known covered synthetic fact set tests interval semantics, not
            # a fabricated claim about one of the supplied buildings.
            facts = copy.deepcopy(rec)
            facts.update(year_built=1900, units=100, unit_conflict=False, use_code="residential")
            self.assertIn(self.result(rule, facts, final), ("applies", "unknown", "superseded"))

    def test_la_moratorium_expired_and_rates_change(self):
        rec = copy.deepcopy(next(s for s in self.stacks.values() if s["stack"]["city"] == "Los Angeles, CA"))
        rec.update(year_built=1900, units=100, use_code="residential")
        moratorium = next(r for r in self.rules if r.get("end_date") == "2024-01-31" and r["jurisdiction"] == "Los Angeles, CA")
        self.assertEqual(self.result(moratorium, rec, "2024-01-31"), "applies")
        self.assertIsNone(self.result(moratorium, rec, "2024-02-01"))
        self.assertIsNone(self.result(moratorium, rec, DEFAULT_AS_OF))
        old = next(r for r in self.rules if r.get("end_date") == "2026-06-30" and r["jurisdiction"] == "Los Angeles, CA")
        current = next(r for r in self.rules if r.get("effective_date") == "2026-07-01" and r["jurisdiction"] == "Los Angeles, CA")
        self.assertEqual(self.result(old, rec, "2026-06-30"), "applies")
        self.assertIsNone(self.result(old, rec, "2026-07-01"))
        self.assertEqual(self.result(current, rec, "2026-07-01"), "applies")

    def test_san_diego_actual_effective_day(self):
        r = next(r for r in self.rules if r["source_doc_id"] == "S-SD-ALG")
        rec = next(s for s in self.stacks.values() if s["stack"]["city"] == r["jurisdiction"])
        self.assertEqual(self.result(r, rec, "2025-06-20"), "not_yet_effective")
        self.assertEqual(self.result(r, rec, "2025-06-21"), "applies")

    def test_ma_failed_ballot_never_applies(self):
        r = next(r for r in self.rules if r["source_doc_id"] == "S-MA-BALLOT")
        for rec in self.stacks.values():
            if rec["stack"]["state"] != "MA":
                continue
            self.assertEqual(self.result(r, rec, "2026-06-22"), "pending")
            self.assertIsNone(self.result(r, rec, "2026-06-23"))
            self.assertIsNone(self.result(r, rec, DEFAULT_AS_OF))

    def test_nj_fee_relative_start_and_exemption(self):
        r = next(r for r in self.rules if r["source_doc_id"] == "D066")
        rec = copy.deepcopy(next(s for s in self.stacks.values() if s["stack"]["state"] == "NJ"))
        rec.update(units=5, unit_conflict=False)
        self.assertEqual(r["effective_date"], "2026-05-01")
        self.assertEqual(self.result(r, rec, "2026-04-30"), "not_yet_effective")
        self.assertEqual(self.result(r, rec, "2026-05-01"), "applies")
        rec["units"] = 2
        self.assertIsNone(self.result(r, rec, DEFAULT_AS_OF))

    def test_incoming_does_not_change_required_submission(self):
        r = copy.deepcopy(self.rules[0])
        r.update(incoming=True, team_rule_id="optional-new-rule")
        self.assertEqual(active_records(self.rules + [r]), active_records(self.rules))

    def test_optional_rule_ids_cannot_collide_with_required_ids(self):
        from src.evidence import stable_id
        r = {"jurisdiction": "CA", "category": "algorithmic_rent_setting",
             "citation": "Section 1", "quote": "It is unlawful to coordinate rent."}
        self.assertNotEqual(stable_id(r), stable_id({**r, "incoming": True}))

    def test_all_current_answers_with_missing_facts_remain_conservative(self):
        from src.apply import UNKNOWN, NOT_COVERED
        for r in self.rules:
            c = r["coverage_conditions"]
            if any(c.get(k) for k in ("built_on_or_before", "built_after", "exempt_if_newer_than_years",
                                     "min_units", "max_units", "exemption_max_units", "facts_required")):
                result, _ = apply.coverage(r, {"city_resolved": True}, DEFAULT_AS_OF)
                self.assertIn(result, (UNKNOWN, NOT_COVERED), r["team_rule_id"])

    def test_method_note_is_one_page(self):
        import pymupdf
        from src.config import ROOT
        with pymupdf.open(ROOT / "docs/method-note.pdf") as pdf:
            self.assertEqual(pdf.page_count, 1)
            self.assertIn("Module A", pdf[0].get_text())
        self.assertEqual(self.client.get("/method-note").status_code, 200)

    def test_web_and_api_retain_traceability_and_conflicts(self):
        for city in ("Los Angeles, CA", "Hoboken, NJ", "Jersey City, NJ", "Boston, MA"):
            aid = next(a for a, s in self.stacks.items() if s["stack"]["city"] == city)
            page = self.client.get("/", params={"address_id": aid}).text
            self.assertIn("Not legal advice", page)
            self.assertIn("as of 2026-10-01", page)
            self.assertIn("retrieved", page)
            if city in ("Hoboken, NJ", "Jersey City, NJ"):
                self.assertIn("Human review flagged", page)
            response = self.client.get(f"/api/lookup/{aid}")
            self.assertEqual(response.status_code, 200)
            for r in response.json()["rules"]:
                self.assertTrue(r["quoted_span"] and r["source_url"] and r["retrieved_at"])
        aid = next(iter(self.stacks))
        self.assertEqual(self.client.get("/", params={"as_of": "2026-02-30"}).status_code, 400)
        self.assertEqual(self.client.get("/api/lookup/" + aid, params={"as_of": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get("/?address_id=not-in-sample").status_code, 404)
        self.assertEqual(self.client.get("/downloads/rules.json").status_code, 200)
        self.assertEqual(self.client.get("/downloads/rules_internal.json").status_code, 404)
        self.assertEqual(self.client.get("/downloads/changes.json").status_code, 200)

    def test_rendered_historical_not_current_moratorium(self):
        aid = next(a for a, s in self.stacks.items() if s["stack"]["city"] == "Los Angeles, CA" and (s["year_built"] or 9999) < 1978)
        current = self.client.get("/", params={"address_id": aid}).text
        history = self.client.get("/", params={"address_id": aid, "as_of": "2023-10-01"}).text
        self.assertNotIn("0% (prohibition)", current)
        self.assertIn("0% (prohibition)", history)


if __name__ == "__main__":
    unittest.main()