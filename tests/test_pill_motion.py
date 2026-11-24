"""The listening pill page offers four motions and a live transcript sheet."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "revoice_app" / "web"


class PillMotionTests(unittest.TestCase):
    def test_pill_page_has_four_motions_and_a_transcript(self):
        html = (WEB / "pill.html").read_text(encoding="utf-8")
        css = (WEB / "pill.css").read_text(encoding="utf-8")
        host = (ROOT / "revoice_app" / "webview.py").read_text(encoding="utf-8")
        styles = host.split("for name in", 1)[1]
        self.assertLess(styles.index("adapter.css"), styles.index("pill.css"))
        self.assertIn("window.renderState", html)
        for name in ("bars", "ribbon", "ink", "dots"):
            self.assertIn(name, html)
            self.assertIn(f".motion-{name}", css)
        self.assertIn("motion-bars", html)
        self.assertIn("motion-ribbon", html)
        self.assertIn("motion-ink", html)
        self.assertIn("motion-dots", html)
        self.assertIn("pill-text", html)
        self.assertIn('data-live="true"', css)
        self.assertIn('data-size="regular"', css)
        self.assertIn('data-size="large"', css)
        self.assertIn('data-paper="true"', css)
        self.assertIn("reduce-motion", css)
