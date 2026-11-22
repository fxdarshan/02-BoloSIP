"""Phase 6 tests: the web page itself (architecture §14; edge cases UI-01, UI-06; AC 9).

Static checks on web/index.html (no browser needed) plus the page as the server
serves it. The interactive checks (clicking, phone width, two tabs, network failure)
were run in a browser and are recorded in eval/manual/phase6_ui_check.json.
"""
import re
import tempfile
import unittest
from pathlib import Path

from bolosip import config
from bolosip.retriever import Retriever
from eval.api_harness import LiveServer

PAGE = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
SCRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", PAGE, re.S))


def theme(name: str) -> dict[str, str]:
    block = re.search(r'\[data-theme="%s"\]\s*\{(.*?)\n\}' % name, PAGE, re.S).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestSelfContained(unittest.TestCase):
    def test_no_external_scripts_fonts_or_trackers(self):                   # arch §14
        self.assertNotRegex(PAGE, r"<script[^>]+src=")
        self.assertNotRegex(PAGE, r"<link[^>]+href=\"https?:")
        self.assertNotRegex(PAGE, r"@import|url\(\s*['\"]?https?:")
        self.assertNotRegex(PAGE, r"(?i)googleapis|gstatic|tailwindcss|googletagmanager|analytics")
        for url in re.findall(r"https?://[^\s\"'<>)]+", PAGE):
            self.assertIn(url, ("http://www.w3.org/2000/svg",), "only the SVG namespace URL may appear")

    def test_no_unsafe_dom_writes(self):                                     # UI-01 (XSS)
        for sink in ("innerHTML", "outerHTML =", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, SCRIPT, sink)
        self.assertIn("textContent", SCRIPT)

    def test_links_open_safely(self):
        self.assertIn('a.rel = "noopener noreferrer"', SCRIPT)
        self.assertIn('a.target = "_blank"', SCRIPT)
        self.assertIn("/^https:\\/\\//.test(r.source.url)", SCRIPT)        # only https sources become links

    def test_storage_is_optional(self):                                      # arch §14
        # Every localStorage call sits inside a try on the same line.
        for line in PAGE.splitlines():
            if "localStorage." in line:
                self.assertIn("try {", line, line.strip()[:80])
        self.assertRegex(PAGE, r"get\(k\) \{ try \{ return localStorage\.getItem\(k\); \} catch")
        self.assertRegex(PAGE, r"set\(k, v\) \{ try \{")


class TestContent(unittest.TestCase):
    def test_disclaimer_in_sticky_header(self):                              # AC 9, CMP-05
        self.assertIn("Facts-only. No investment advice.", PAGE)
        header_css = re.search(r"\.header \{(.*?)\}", PAGE, re.S).group(1)
        self.assertIn("position: sticky", header_css)
        header = re.search(r'<header class="header">(.*?)</header>', PAGE, re.S).group(1)
        self.assertIn('class="disclaimer"', header)

    def test_input_limits_and_privacy_hint(self):
        self.assertIn('maxlength="500"', PAGE)
        self.assertIn("Don't share PAN, Aadhaar, phone or OTP.", PAGE)
        self.assertIn('aria-live="polite"', PAGE)
        self.assertIn('<label class="sr-only" for="input">', PAGE)

    def test_suggestions_are_an_accessible_combobox(self):
        for attr in ('role="combobox"', 'aria-autocomplete="list"', 'aria-controls="suggestions"',
                     'aria-expanded="false"', 'role="listbox"'):
            self.assertIn(attr, PAGE)
        for js in ("aria-activedescendant", '"ArrowDown"', '"Escape"', "state.config.suggest"):
            self.assertIn(js, SCRIPT)

    def test_examples_and_welcome_come_from_the_api(self):
        self.assertIn('api("GET", "/api/config")', SCRIPT)
        self.assertIn("cfg.examples", SCRIPT)

    def test_every_reply_kind_has_an_icon_and_label(self):
        for kind in ("answer", "refusal", "performance", "privacy", "clarify", "not_found", "help"):
            self.assertRegex(SCRIPT, rf'\b{kind}:\s*\{{ icon: "\w+",\s*label: "[^"]+"\s*\}}', kind)

    def test_no_claims_the_project_cannot_back(self):
        """The Stitch draft had badges such as 'SEBI-compliant' and 'AMFI live feed'."""
        for claim in ("SEBI-compliant", "SEBI compliant", "Live Feed", "Verified Snapshot", "Fact Checked",
                      "AI Engine", "Research Engine", "Zero Commission", "Guardrail"):
            self.assertNotIn(claim.lower(), PAGE.lower(), claim)


class TestContrast(unittest.TestCase):
    """WCAG AA, in both themes: 4.5:1 for text (icons and labels are held to the same bar)."""

    def test_text_and_icon_colours(self):
        for name in ("dark", "light"):
            t = theme(name)
            surfaces = [t["bg"], t["panel"], t["card"], t["card-hi"]]
            with self.subTest(theme=name):
                for fg in ("text", "muted", "faint"):
                    for bg in surfaces:
                        self.assertGreaterEqual(contrast(t[fg], bg), 4.5, f"{name}: {fg} on {bg}")
                for k in ("k-answer", "k-refusal", "k-perf", "k-privacy", "k-clarify", "k-notfound", "accent"):
                    for bg in (t["card"], t["bg"]):
                        self.assertGreaterEqual(contrast(t[k], bg), 4.5, f"{name}: {k} on {bg}")
                self.assertGreaterEqual(contrast(t["on-accent"], t["accent"]), 4.5, f"{name}: button text")
                self.assertGreaterEqual(contrast(t["on-danger"], t["danger-bg"]), 4.5, f"{name}: delete button")

    def test_hairline_borders_only(self):
        """The Stitch mobile draft drew 2px light-grey borders; every border here is 1px."""
        self.assertNotRegex(PAGE, r"border(?:-(?:top|right|bottom|left))?:\s*[2-9]px")
        for name in ("dark", "light"):
            block = re.search(r'\[data-theme="%s"\]\s*\{(.*?)\n\}' % name, PAGE, re.S).group(1)
            alpha = [float(a) for a in re.findall(r"--line(?:-strong)?:\s*rgba\([^)]*,\s*([\d.]+)\)", block)]
            self.assertTrue(alpha and max(alpha) <= 0.2, name)


class TestServedPage(unittest.TestCase):
    def test_served_with_security_headers(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                LiveServer(Path(tmp) / "t.sqlite3", Retriever(mode="bm25")) as api:
            status, body, headers = api.request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b"Facts-only. No investment advice.", body)
            self.assertTrue(headers["Content-Type"].startswith("text/html"))
            csp = headers["Content-Security-Policy"]
            for rule in ("default-src 'self'", "connect-src 'self'", "frame-ancestors 'none'"):
                self.assertIn(rule, csp)
            self.assertEqual(headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
