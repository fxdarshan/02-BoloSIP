"""Phase 0 smoke tests: the package imports and settings behave."""
import importlib
import unittest
from pathlib import Path

from bolosip import DISCLAIMER, config


class TestPackage(unittest.TestCase):
    def test_disclaimer_text(self):
        self.assertEqual(DISCLAIMER, "Facts-only. No investment advice.")

    def test_package_modules_import(self):
        for name in ("bolosip", "bolosip.config", "bolosip.guards"):
            with self.subTest(module=name):
                importlib.import_module(name)


class TestConsoleEncoding(unittest.TestCase):
    def test_symbols_print_on_legacy_windows_code_page(self):
        import os, subprocess, sys
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        code = "from bolosip.textutil import utf8_output; utf8_output(); print('≥ ₹ – fine')"
        proc = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, env=env, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertIn("fine", proc.stdout.decode("utf-8", "replace"))


class TestSettingsDefaults(unittest.TestCase):
    def setUp(self):
        self.s = config.load_settings({})

    def test_defaults(self):
        self.assertEqual(self.s.host, "127.0.0.1")
        self.assertEqual(self.s.port, 8000)
        self.assertEqual(self.s.llm_mode, "auto")
        self.assertEqual(self.s.model, config.DEFAULT_GROQ_MODEL)
        self.assertEqual(self.s.rate_msg_per_min, 30)
        self.assertEqual(self.s.rate_all_per_min, 120)
        self.assertFalse(self.s.groq_key_present)

    def test_default_paths_inside_data_dir(self):
        self.assertEqual(self.s.db_path, config.DATA_DIR / "bolosip.sqlite3")
        self.assertEqual(self.s.corpus_path, config.DATA_DIR / "corpus.json")


class TestSettingsFromEnv(unittest.TestCase):
    def test_overrides(self):
        s = config.load_settings({
            "BOLOSIP_HOST": "0.0.0.0",
            "BOLOSIP_PORT": "9001",
            "BOLOSIP_LLM": "OFF",
            "BOLOSIP_MODEL": "llama-3.1-8b-instant",
            "BOLOSIP_RATE_MSG": "10",
            "BOLOSIP_DB": "tmp/test.sqlite3",
            "GROQ_API_KEY": "gsk_test_not_real",
        })
        self.assertEqual(s.host, "0.0.0.0")
        self.assertEqual(s.port, 9001)
        self.assertEqual(s.llm_mode, "off")
        self.assertEqual(s.model, "llama-3.1-8b-instant")
        self.assertEqual(s.rate_msg_per_min, 10)
        self.assertEqual(s.db_path, config.ROOT / "tmp" / "test.sqlite3")
        self.assertTrue(s.groq_key_present)

    def test_key_value_is_never_stored(self):
        s = config.load_settings({"GROQ_API_KEY": "gsk_secret_value"})
        self.assertNotIn("gsk_secret_value", repr(s))

    def test_blank_values_use_defaults(self):
        s = config.load_settings({"BOLOSIP_PORT": "  ", "BOLOSIP_MODEL": "", "GROQ_API_KEY": "   "})
        self.assertEqual(s.port, 8000)
        self.assertEqual(s.model, config.DEFAULT_GROQ_MODEL)
        self.assertFalse(s.groq_key_present)

    def test_absolute_path_kept(self):
        absolute = Path(config.ROOT.anchor) / "elsewhere" / "c.json"
        s = config.load_settings({"BOLOSIP_CORPUS": str(absolute)})
        self.assertEqual(s.corpus_path, absolute)


class TestSettingsInvalid(unittest.TestCase):
    def test_bad_values_raise_clear_errors(self):
        cases = {
            "BOLOSIP_PORT": ["abc", "0", "70000"],
            "BOLOSIP_LLM": ["maybe"],
            "BOLOSIP_RATE_MSG": ["-1", "x"],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError) as ctx:
                        config.load_settings({name: value})
                    self.assertIn(name, str(ctx.exception))


class TestConstants(unittest.TestCase):
    def test_fixed_links_are_official_https(self):
        for url in (config.AMFI_INVESTOR_URL, config.SEBI_INVESTOR_URL, config.HDFC_FACTSHEET_URL):
            with self.subTest(url=url):
                self.assertTrue(url.startswith("https://"))
                self.assertTrue(any(d in url for d in config.OFFICIAL_DOMAINS))

    def test_three_examples(self):
        self.assertEqual(len(config.EXAMPLE_QUESTIONS), 3)

    def test_other_amc_list_excludes_hdfc(self):
        self.assertNotIn("hdfc", config.OTHER_AMC_NAMES)
        self.assertEqual(len(config.OTHER_AMC_NAMES), len(set(config.OTHER_AMC_NAMES)))

    def test_limits(self):
        self.assertEqual(config.MAX_TEXT_CHARS, 500)
        self.assertEqual(config.MAX_BODY_BYTES, 4096)


if __name__ == "__main__":
    unittest.main()
