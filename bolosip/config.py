"""All BoloSIP settings in one place (architecture §16).

Two kinds of settings live here:

* **Runtime settings** come from environment variables, with safe defaults, so
  the app runs with no environment set at all. Read them with ``load_settings()``
  (or the module-level ``SETTINGS``).
* **Constants** are fixed values: retrieval weights and thresholds (tuned in
  Phase 8), request limits, the LLM call shape, and the official links used in
  refusal / performance / privacy replies.

Local settings and secrets (e.g. ``GROQ_API_KEY``) go in a ``.env`` file in the
project root. Copy ``.env.example`` to ``.env`` and fill it in. ``.env`` is
git-ignored. It is read once at import; a variable already set in the real
environment always wins over the file.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from bolosip import DISCLAIMER

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / ".env"

# ---------------------------------------------------------------------------
# .env file loading (standard library only; no python-dotenv dependency)
# ---------------------------------------------------------------------------

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines. Supports comments (#), blank lines, ``export``,
    and single- or double-quoted values. Unquoted values may end with `` # comment``."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            value = raw[1:-1]
        else:
            value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        values[key] = value
    return values


def load_env_file(path: Path = ENV_FILE, environ: dict | None = None) -> list[str]:
    """Copy variables from ``path`` into ``environ`` (default ``os.environ``)
    without overriding ones that are already set. Returns the names loaded
    (never the values). A missing file is not an error."""
    environ = os.environ if environ is None else environ
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    loaded = []
    for key, value in parse_env_file(text).items():
        if key not in environ:
            environ[key] = value
            loaded.append(key)
    return loaded


if os.environ.get("BOLOSIP_SKIP_DOTENV") != "1":
    load_env_file()

# ---------------------------------------------------------------------------
# Runtime settings (environment variables)
# ---------------------------------------------------------------------------

LLM_MODES = ("auto", "on", "off")

# Default Groq model. A Groq *production* model as of Nov 2026; Groq retires
# models over time, so check console.groq.com/docs/models before a release.
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    corpus_path: Path
    llm_mode: str           # auto | on | off
    model: str              # Groq model ID
    rate_msg_per_min: int
    rate_all_per_min: int
    groq_key_present: bool  # only whether a key is set; the key itself is never stored here


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from ``env`` (defaults to ``os.environ``).

    Raises ``ValueError`` with a clear message for an invalid value, so a bad
    setting fails at start-up instead of halfway through a request.
    """
    env = os.environ if env is None else env

    llm_mode = (env.get("BOLOSIP_LLM") or "auto").strip().lower()
    if llm_mode not in LLM_MODES:
        raise ValueError(f"BOLOSIP_LLM must be one of {', '.join(LLM_MODES)}, got {llm_mode!r}")

    return Settings(
        host=(env.get("BOLOSIP_HOST") or "127.0.0.1").strip(),
        port=_int(env, "BOLOSIP_PORT", 8000, 1, 65535),
        db_path=_path(env, "BOLOSIP_DB", DATA_DIR / "bolosip.sqlite3"),
        corpus_path=_path(env, "BOLOSIP_CORPUS", DATA_DIR / "corpus.json"),
        llm_mode=llm_mode,
        model=(env.get("BOLOSIP_MODEL") or DEFAULT_GROQ_MODEL).strip(),
        rate_msg_per_min=_int(env, "BOLOSIP_RATE_MSG", 30, 1, 10_000),
        rate_all_per_min=_int(env, "BOLOSIP_RATE_ALL", 120, 1, 100_000),
        groq_key_present=bool((env.get("GROQ_API_KEY") or "").strip()),
    )


SETTINGS = load_settings()

# ---------------------------------------------------------------------------
# Request limits (architecture §13)
# ---------------------------------------------------------------------------

MAX_BODY_BYTES = 4096
MAX_TEXT_CHARS = 500
THREAD_TITLE_CHARS = 60

# ---------------------------------------------------------------------------
# Retrieval (architecture §8). Starting values; tuned in Phase 8.
# ---------------------------------------------------------------------------

BM25_K1 = 1.5
BM25_B = 0.75
W_SCHEME = 3.0      # boost: chunk belongs to the resolved scheme
W_TOPIC = 3.0       # boost: chunk topic equals the detected topic
W_OTHER = 5.0       # penalty: chunk belongs to a different scheme
MIN_SCORE = 0.0     # set in Phase 3, tuned in Phase 8
MIN_LEXICAL = 0.0   # set in Phase 3, tuned in Phase 8
MAX_CLARIFY_CANDIDATES = 5

# ---------------------------------------------------------------------------
# Optional LLM rephrasing via Groq (architecture §9.2)
# ---------------------------------------------------------------------------

LLM_TIMEOUT_S = 15.0
LLM_MAX_RETRIES = 1
LLM_TEMPERATURE = 0
LLM_MAX_COMPLETION_TOKENS = 200

# ---------------------------------------------------------------------------
# Fixed links used in non-answer replies (architecture §10.1)
# ---------------------------------------------------------------------------

AMFI_INVESTOR_URL = "https://www.amfiindia.com/investor"
SEBI_INVESTOR_URL = "https://investor.sebi.gov.in/"
HDFC_FACTSHEET_URL = "https://www.hdfcfund.com/mutual-funds/factsheets"

# Domains a reply may cite (besides the 27 Groww scheme pages). Used by tests
# and the evaluation runner to check citations (AC 3).
OFFICIAL_DOMAINS = (
    "hdfcfund.com",
    "amfiindia.com",
    "sebi.gov.in",
    "camsonline.com",
    "mfcentral.com",
)

# ---------------------------------------------------------------------------
# Other fund houses (architecture §7 step 0, GAP-01). A message naming one of
# these, and not HDFC, gets a not_found reply instead of an HDFC answer.
# Matched on whole words after normalisation (Phase 3).
# ---------------------------------------------------------------------------

OTHER_AMC_NAMES = (
    "sbi", "axis", "icici", "icici prudential", "nippon", "kotak", "mirae",
    "parag parikh", "ppfas", "uti", "aditya birla", "absl", "dsp", "tata",
    "quant", "motilal", "motilal oswal", "franklin", "franklin templeton",
    "edelweiss", "canara robeco", "bandhan", "invesco", "hsbc", "whiteoak",
    "white oak", "mahindra manulife", "baroda bnp", "bnp paribas", "sundaram",
    "lic", "union", "pgim", "360 one", "navi", "bajaj finserv", "helios",
    "samco", "jm financial", "iti", "shriram", "quantum", "nj",
)

# ---------------------------------------------------------------------------
# UI text (problem statement §5)
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "Welcome to BoloSIP. I answer factual questions about 27 HDFC Mutual Fund "
    "schemes, such as expense ratio, exit load, minimum SIP, riskometer and "
    "benchmark, and how to download statements. Every answer links to its source."
)
EXAMPLE_QUESTIONS = (
    "What is the expense ratio of HDFC Mid Cap Fund?",
    "What is the ELSS lock-in period?",
    "How do I download my account statement?",
)
PRIVACY_HINT = "Don't share PAN, Aadhaar, phone or OTP."

__all__ = [
    "DISCLAIMER", "Settings", "load_settings", "SETTINGS", "ROOT", "DATA_DIR",
]
