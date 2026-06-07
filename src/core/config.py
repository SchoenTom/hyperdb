"""
HyperDataBank — Configuration Loader
─────────────────────────────────────
Loads and validates YAML configuration files.
All project parameters are defined in config/*.yaml — never hardcoded.
"""

from pathlib import Path
from functools import lru_cache
import yaml

# Project root is two levels up from this file (src/core/config.py → HyperDB/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


@lru_cache(maxsize=None)
def _load_yaml(filename: str) -> dict:
    """Load a YAML file from the config directory (cached after first read)."""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Config file is empty or invalid: {path}")
    return data


def load_settings() -> dict:
    """Load central project settings (API, paths, parameters)."""
    return _load_yaml("settings.yaml")


def load_exchanges() -> dict:
    """Load the exchange registry with metadata.

    Returns dict mapping exchange_code → {name, country, region, currency,
    timezone, tier, notes}.
    """
    data = _load_yaml("exchanges.yaml")
    return data.get("exchanges", {})


def load_asset_classes() -> dict:
    """Load asset class definitions and EODHD type mappings.

    Returns dict mapping our canonical class name → {description,
    eodhd_types, subclasses}.
    """
    data = _load_yaml("asset_classes.yaml")
    return data.get("asset_classes", {})


def eodhd_type_to_class(eodhd_type: str) -> str:
    """Map an EODHD security type string to our canonical asset class.

    Returns the canonical class name (e.g., 'equity', 'etf', 'bond').
    Falls back to 'other' for unmapped types.
    """
    classes = load_asset_classes()
    for class_name, definition in classes.items():
        if eodhd_type in definition.get("eodhd_types", []):
            return class_name
    return "other"


def load_exchange_blacklist() -> list[str]:
    """Load the exchange blacklist from settings.

    Returns list of exchange codes to skip during price backfill.
    Returns empty list if not configured.
    """
    settings = load_settings()
    return settings.get("exchange_blacklist", [])


def load_universe_skip_codes() -> set[str]:
    """Load the set of exchange codes to skip during universe building.

    These are non-standard exchanges (FOREX, CC, etc.) that have
    their own dedicated universe-building paths.
    Returns the default hardcoded set if not configured.
    """
    settings = load_settings()
    codes = settings.get("universe_skip_codes", None)
    if codes is None:
        return {"FOREX", "CC", "COMM", "BOND", "MONEY"}
    return set(codes)


def load_regions() -> list[dict]:
    """Load regional download priority configuration.

    Returns list of dicts, each with:
        name: str, asset_classes: list[str], exchanges: list[str]
    """
    settings = load_settings()
    return settings.get("regions", [])


def load_supplementary() -> dict:
    """Load supplementary download configuration (indices, bonds).

    Returns dict mapping name -> {exchange, description}.
    """
    settings = load_settings()
    return settings.get("supplementary", {})


def get_data_dir() -> Path:
    """Return the absolute path to the data directory, creating it if needed."""
    settings = load_settings()
    data_dir = PROJECT_ROOT / settings["paths"]["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Return the absolute path to the DuckDB database file."""
    settings = load_settings()
    db_path = PROJECT_ROOT / settings["paths"]["db_file"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def get_reports_dir() -> Path:
    """Return the absolute path to the reports directory."""
    settings = load_settings()
    reports_dir = PROJECT_ROOT / settings["paths"]["reports_dir"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir
