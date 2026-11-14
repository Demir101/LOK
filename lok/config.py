"""Application configuration.

Configuration is read from environment variables. A local ``.env`` file in the
project root is also honoured (simple ``KEY=VALUE`` lines, no shell expansion).
Environment variables that are already set take precedence over ``.env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "lok.db"
SEED_PATH = Path(__file__).resolve().parent / "seed" / "scenarios.json"

#: Maximum accepted size of an imported scenario JSON file, in bytes (2 MiB).
DEFAULT_MAX_IMPORT_BYTES = 2 * 1024 * 1024
#: Number of rows per page in the Evaluation History.
DEFAULT_HISTORY_PAGE_SIZE = 25


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal ``.env`` file. Invalid lines are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings."""

    db_path: Path
    max_import_bytes: int
    history_page_size: int

    @classmethod
    def load(cls) -> Settings:
        env = {**_read_dotenv(PROJECT_ROOT / ".env"), **os.environ}
        db_raw = env.get("LOK_DB_PATH", "").strip()
        db_path = Path(db_raw) if db_raw else DEFAULT_DB_PATH
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        return cls(
            db_path=db_path,
            max_import_bytes=_positive_int(env.get("LOK_MAX_IMPORT_BYTES"), DEFAULT_MAX_IMPORT_BYTES),
            history_page_size=_positive_int(env.get("LOK_HISTORY_PAGE_SIZE"), DEFAULT_HISTORY_PAGE_SIZE),
        )


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return value if value > 0 else default
