"""Central settings. Everything that matters can be overridden with environment variables."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent


def _user_data_dir() -> Path:
    """Where a normal install keeps its cache and exports: per user, never inside the program folder."""
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "INSTAT-Explorer"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "INSTAT-Explorer"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "instat-explorer"


def _data_dir() -> Path:
    if env := os.environ.get("INSTAT_DATA_DIR"):  # the portable launchers point this at a folder next to the program
        return Path(env).expanduser()
    return ROOT / "data" if (ROOT / "pyproject.toml").is_file() else _user_data_dir()  # source checkout vs installed


DATA_DIR = _data_dir()
RAW_DIR = DATA_DIR / "raw"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "instat.sqlite"


def ensure_data_dir() -> bool:
    """Make sure the data folder exists and can be written. On a locked-down PC where it cannot, a temporary folder is
    used for this session instead (the module-level paths are switched) and ``False`` is returned so the caller can say so."""
    global DATA_DIR, RAW_DIR, EXPORT_DIR, DB_PATH
    for candidate in (DATA_DIR, Path(tempfile.gettempdir()) / "INSTAT-Explorer"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError:
            continue
        usual = candidate == DATA_DIR
        DATA_DIR, RAW_DIR, EXPORT_DIR, DB_PATH = candidate, candidate / "raw", candidate / "exports", candidate / "instat.sqlite"
        return usual
    return False


BASE_URL = "https://www.instat.gov.al"
INSTAT_HOSTS = ("instat.gov.al",)
USER_AGENT = f"instatkit/{__version__} (free educational tool; one request at a time)"

# Networking: deliberately gentle. Nothing is fetched unless the user asks for it.
REQUEST_TIMEOUT = 30  # seconds per request
MIN_REQUEST_INTERVAL = 0.35  # seconds between requests to the same host
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# Reader guard rails: every reader is bounded, so a pathological or hostile file cannot exhaust memory or time.
MAX_ROWS = 20_000
MAX_COLS = 1_024
MAX_CELLS = 2_000_000  # rows x columns kept per sheet (a real INSTAT table is far below this)
MAX_OBSERVATIONS = 1_000_000  # tidy rows built per table
MAX_XML_BYTES = 150_000_000  # uncompressed XML read from one .xlsx, all its parts together
MAX_ZIP_ENTRIES = 2_000
MAX_SHEETS = 300

# Two-digit years up to this value are read as 20xx, above it as 19xx.
TWO_DIGIT_YEAR_PIVOT = 40
