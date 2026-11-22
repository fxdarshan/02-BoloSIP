"""Browser tests of the chat page with Playwright (the `webapp-testing` skill's approach).

The real server runs in-process on a free port (eval/api_harness.LiveServer, BM25, a
temporary database) and headless Chromium drives web/index.html like a user: examples,
next-step chips, typing suggestions with the keyboard, repeated "not found", XSS text,
the phone drawer, console errors, and an overflow scan at 1440 / 768 / 375 / 320 px.

Skipped when Playwright isn't installed (the default laptop setup). The CI `ui` job sets
BOLOSIP_UI_TESTS=1, so there a missing browser fails instead of skipping.
    pip install playwright && python -m playwright install chromium
"""
import os
import tempfile
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

from bolosip.retriever import Retriever
from eval.api_harness import LiveServer

REQUIRED = os.environ.get("BOLOSIP_UI_TESTS") == "1"

# Every visible element: off-screen, outside its parent's box, or content spilling out.
OVERFLOW_SCAN = r"""() => {
  const vw = document.documentElement.clientWidth, issues = [];
  const sb = document.getElementById('sidebar');
  const drawerClosed = !sb.classList.contains('open') && getComputedStyle(sb).position === 'fixed';
  const label = e => (typeof e.className === 'string' && e.className ? '.' + e.className.split(' ').join('.') : e.tagName.toLowerCase());
  for (const e of document.querySelectorAll('.app *')) {
    if (e.closest('svg') && e.tagName !== 'svg') continue;
    if (drawerClosed && e.closest('#sidebar')) continue;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = e.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    if (r.right > vw + 0.5 || r.left < -0.5) issues.push('off-screen ' + label(e));
    let p = e.parentElement;
    while (p && getComputedStyle(p).display === 'contents') p = p.parentElement;
    if (p && !p.closest('svg')) {
      const pr = p.getBoundingClientRect();
      if (getComputedStyle(p).overflowX === 'visible' && (r.right > pr.right + 1 || r.left < pr.left - 1)
          && !['absolute', 'fixed'].includes(cs.position)) issues.push('outside parent ' + label(e));
    }
    if (cs.overflowX === 'visible' && e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0
        && !(e instanceof SVGElement)) issues.push('content spills ' + label(e));
  }
  return { sideways: document.documentElement.scrollWidth > vw, issues: [...new Set(issues)] };
}"""


@unittest.skipUnless(HAVE_PLAYWRIGHT or REQUIRED, "Playwright not installed (pip install playwright)")
class TestChatPageInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.api = LiveServer(Path(cls.tmp.name) / "ui.sqlite3", Retriever(mode="bm25")).__enter__()
        cls.url = f"http://127.0.0.1:{cls.api.port}/"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.api.__exit__(None, None, None)
        cls.tmp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.page = self.context.new_page()
        self.errors, self.dialogs = [], []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        self.page.goto(self.url)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_selector(".example")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], "console errors")
        self.assertEqual(self.dialogs, [], "a dialog opened (script ran?)")

    # --- helpers --------------------------------------------------------------
    def replies(self):
        return self.page.locator(".reply")

    def ask(self, text):
        before = self.replies().count()
        self.page.fill("#input", text)
        self.page.press("#input", "Escape")              # close suggestions so Enter sends the text
        self.page.press("#input", "Enter")
        self.page.wait_for_function(f"document.querySelectorAll('.reply').length > {before}")
        return self.replies().last

    # --- tests ----------------------------------------------------------------
    def test_welcome_and_disclaimer(self):                                   # AC 9
        self.assertEqual(self.page.locator(".example").count(), 3)
        self.assertTrue(self.page.locator(".disclaimer", has_text="Facts-only. No investment advice.").is_visible())

    def test_example_gives_cited_answer_and_next_steps(self):
        self.page.locator(".example").first.click()
        reply = self.replies().last
        reply.wait_for()
        self.assertEqual(reply.get_attribute("data-kind"), "answer")
        self.assertIn("groww.in/mutual-funds/hdfc-mid-cap", reply.locator("a.source").get_attribute("href"))
        self.assertEqual(reply.locator("a.source").get_attribute("rel"), "noopener noreferrer")
        self.assertIn("Last updated from sources:", reply.locator(".footer").inner_text())
        chips = self.page.locator(".nextsteps .chip")
        self.assertEqual(chips.count(), 3)
        before = self.replies().count()
        chips.first.click()
        self.page.wait_for_function(f"document.querySelectorAll('.reply').length > {before}")
        self.assertIn("HDFC Mid Cap Fund", self.replies().last.inner_text())
        self.assertEqual(self.page.locator(".nextsteps").count(), 1)        # only under the latest reply

    def test_typing_suggestions_with_keyboard(self):
        self.page.click("#input")
        self.page.keyboard.type("liquid exit")
        listbox = self.page.locator("#suggestions")
        listbox.wait_for(state="visible")
        self.assertEqual(self.page.get_attribute("#input", "aria-expanded"), "true")
        self.assertIn("What is the exit load of HDFC Liquid Fund?", listbox.inner_text())
        self.page.keyboard.press("ArrowDown")
        self.assertEqual(self.page.get_attribute("#input", "aria-activedescendant"), "sug-0")
        before = self.replies().count()
        self.page.keyboard.press("Enter")
        self.page.wait_for_function(f"document.querySelectorAll('.reply').length > {before}")
        self.assertIn("HDFC Liquid Fund", self.replies().last.inner_text())
        self.assertTrue(listbox.is_hidden())
        # Escape closes the list without sending; Tab fills without sending.
        self.page.keyboard.type("gilt nav")
        listbox.wait_for(state="visible")
        self.page.keyboard.press("Escape")
        self.assertTrue(listbox.is_hidden())
        self.page.fill("#input", "")
        self.page.keyboard.type("gilt nav")
        listbox.wait_for(state="visible")
        self.page.keyboard.press("ArrowDown")
        self.page.keyboard.press("Tab")
        self.assertEqual(self.page.input_value("#input"), "What is the NAV of HDFC Gilt Fund?")

    def test_repeated_not_found_shows_what_i_can_answer(self):           # layered fallback
        self.ask("weather in Mumbai")
        self.assertEqual(self.replies().last.get_attribute("data-kind"), "not_found")
        self.assertTrue(self.page.locator(".nextsteps", has_text="Try instead").is_visible())
        self.assertEqual(self.page.locator(".capability-note").count(), 0)
        self.ask("bitcoin price today")
        self.assertTrue(self.page.locator(".capability-note").is_visible())

    def test_script_text_is_shown_not_run(self):                          # UI-01
        payload = "<script>alert(1)</script><img src=x onerror=alert(2)>"
        self.ask(payload)
        self.assertEqual(self.page.locator(".msg-user").last.inner_text(), payload)
        self.assertEqual(self.page.locator(".messages script, .messages img").count(), 0)

    def test_no_overflow_at_any_width(self):
        self.page.locator(".example").first.click()
        self.page.wait_for_selector(".nextsteps .chip")
        for width, height in ((1440, 900), (768, 1024), (375, 812), (320, 640)):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.fill("#input", "small cap")
                self.page.locator("#suggestions").wait_for(state="visible")
                result = self.page.evaluate(OVERFLOW_SCAN)
                self.assertFalse(result["sideways"])
                self.assertEqual(result["issues"], [])
                self.page.fill("#input", "")

    def test_phone_drawer(self):                                          # UI-06
        self.page.set_viewport_size({"width": 375, "height": 812})
        self.page.locator(".example").first.click()
        self.page.wait_for_selector(".reply")
        self.page.click("#menuBtn")
        self.page.wait_for_function("document.getElementById('sidebar').getBoundingClientRect().left >= 0")
        self.assertEqual(self.page.get_attribute("#menuBtn", "aria-expanded"), "true")
        self.assertGreaterEqual(self.page.locator(".thread").count(), 1)
        self.page.keyboard.press("Escape")
        self.assertEqual(self.page.get_attribute("#menuBtn", "aria-expanded"), "false")


if __name__ == "__main__":
    unittest.main()
