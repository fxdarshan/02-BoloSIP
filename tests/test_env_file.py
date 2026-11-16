"""Tests for reading local settings from a .env file."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bolosip import config


class TestParseEnvFile(unittest.TestCase):
    def test_formats(self):
        text = "\n".join([
            "# comment line",
            "",
            "GROQ_API_KEY=gsk_abc",
            "BOLOSIP_PORT = 9000",
            'BOLOSIP_MODEL="llama-3.1-8b-instant"',
            "BOLOSIP_HOST='localhost'",
            "export BOLOSIP_LLM=off",
            "BOLOSIP_DB=data/x.sqlite3   # inline comment",
            'QUOTED_HASH="a # not a comment"',
            "EMPTY=",
            "not a valid line",
        ])
        self.assertEqual(config.parse_env_file(text), {
            "GROQ_API_KEY": "gsk_abc",
            "BOLOSIP_PORT": "9000",
            "BOLOSIP_MODEL": "llama-3.1-8b-instant",
            "BOLOSIP_HOST": "localhost",
            "BOLOSIP_LLM": "off",
            "BOLOSIP_DB": "data/x.sqlite3",
            "QUOTED_HASH": "a # not a comment",
            "EMPTY": "",
        })


class TestLoadEnvFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / ".env"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_is_fine(self):
        self.assertEqual(config.load_env_file(self.path, environ={}), [])

    def test_loads_without_overriding_real_environment(self):
        self.path.write_text("GROQ_API_KEY=from_file\nBOLOSIP_PORT=9000\n", encoding="utf-8")
        environ = {"BOLOSIP_PORT": "7000"}
        loaded = config.load_env_file(self.path, environ=environ)
        self.assertEqual(loaded, ["GROQ_API_KEY"])          # names only, never values
        self.assertEqual(environ["GROQ_API_KEY"], "from_file")
        self.assertEqual(environ["BOLOSIP_PORT"], "7000")   # real environment wins

    def test_utf8_bom_from_windows_notepad(self):
        self.path.write_bytes("﻿GROQ_API_KEY=k\n".encode("utf-8"))
        environ = {}
        config.load_env_file(self.path, environ=environ)
        self.assertEqual(environ, {"GROQ_API_KEY": "k"})

    def test_settings_see_key_from_file(self):
        self.path.write_text("GROQ_API_KEY=gsk_test\n", encoding="utf-8")
        environ = {}
        config.load_env_file(self.path, environ=environ)
        s = config.load_settings(environ)
        self.assertTrue(s.groq_key_present)
        self.assertNotIn("gsk_test", repr(s))


class TestProjectEnvFiles(unittest.TestCase):
    def test_example_exists_and_has_no_real_key(self):
        example = config.ROOT / ".env.example"
        self.assertTrue(example.exists(), ".env.example is missing")
        values = config.parse_env_file(example.read_text(encoding="utf-8"))
        self.assertIn("GROQ_API_KEY", values)
        self.assertEqual(values["GROQ_API_KEY"], "", ".env.example must not contain a real key")

    def test_example_values_are_valid_settings(self):
        values = config.parse_env_file((config.ROOT / ".env.example").read_text(encoding="utf-8"))
        s = config.load_settings(values)
        self.assertEqual(s.port, 8000)
        self.assertEqual(s.model, config.DEFAULT_GROQ_MODEL)

    def test_dot_env_is_git_ignored(self):
        try:
            proc = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=config.ROOT,
                                  capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("git not available")
        if proc.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(proc.returncode, 0, ".env must be listed in .gitignore")


if __name__ == "__main__":
    unittest.main()
