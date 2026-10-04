"""Presentation contracts; legal applicability is tested separately."""

import re
import unittest

from fastapi.testclient import TestClient

from src.config import ROOT
from src.web import STATUS, app, card, load


def contrast(foreground, background):
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))
    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + .05) / (a + .05)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_local_styles_and_accessible_lookup(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        self.assertIn('href="/static/styles.css"', page)
        self.assertNotIn("cdn.tailwindcss.com", page)
        self.assertIn('href="#main"', page)
        self.assertIn('id="main"', page)
        self.assertIn('name="address_id"', page)
        self.assertIn('name="as_of"', page)
        self.assertIn("Not legal advice.", page)
        css = self.client.get("/static/styles.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn(":focus-visible", css.text)
        self.assertIn("prefers-reduced-motion", css.text)
        self.assertIn("@media (max-width: 680px)", css.text)
        for link in ("/method-note", "/downloads/rules.json", "/downloads/lookups.json", "/downloads/changes.json"):
            self.assertIn(f'href="{link}"', page)
            self.assertEqual(self.client.get(link).status_code, 200)

    def test_rule_states_preserve_evidence_and_review_warnings(self):
        rules, _ = load()
        rule = rules[0]
        for status, (label, style) in STATUS.items():
            entry = {"result": status, "explanation": "Evidence-backed explanation", "conflict_flag": True}
            html = card(entry, rule, "2026-10-01")
            self.assertIn(label, html)
            self.assertIn(style, html)
            self.assertIn("Human review flagged.", html)
            self.assertIn("Quoted text from the law", html)
            self.assertIn("retrieved", html)
            self.assertIn("Evidence-backed explanation", html)

    def test_theme_text_contrast(self):
        css = (ROOT / "web" / "styles.css").read_text()
        colors = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]{6});", css))
        for foreground, background in [
            ("ink", "page"), ("muted", "surface"), ("ink-soft", "pistachio"),
            ("surface", "forest"), ("amber-ink", "amber-bg"),
            ("alert-ink", "alert-bg"), ("unknown-ink", "unknown-bg"),
            ("pending-ink", "pending-bg"),
        ]:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast(colors[foreground], colors[background]), 4.5)
        self.assertGreaterEqual(contrast("#89621f", colors["pistachio"]), 3)


if __name__ == "__main__":
    unittest.main()