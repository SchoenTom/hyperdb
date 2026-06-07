"""
HyperDataBank — FX Rate Downloader
───────────────────────────────────
Downloads daily foreign exchange rates from EODHD.

FX rates are critical for multi-currency return computation.
All rates are stored as QUOTE/BASE (e.g., EUR/USD = 1.08 means 1 EUR = 1.08 USD).

We download rates for every currency that appears in dim_asset
against the configured base currencies (USD, EUR by default).
"""

import duckdb
from tqdm import tqdm

from src.core.config import load_settings
from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.fx")

# Major FX pairs to always include, even if no assets trade in that currency
CORE_CURRENCIES = [
    "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK",
    "HKD", "SGD", "KRW", "TWD", "INR", "BRL", "ZAR", "MXN", "TRY", "PLN",
    "CZK", "HUF", "ILS", "SAR", "AED", "THB", "MYR", "IDR", "PHP", "CNY",
    "RUB", "CLP", "COP", "PEN", "ARS", "EGP", "NGN", "KES", "PKR", "BDT",
    "LKR", "VND", "QAR", "KWD",
]


def download_fx_rates(from_date: str | None = None,
                      to_date: str | None = None) -> None:
    """Download daily FX rates for all relevant currency pairs.

    Determines which currencies are needed by scanning dim_asset,
    then downloads historical rates from EODHD FOREX endpoint.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    if from_date is None:
        from_date = settings["sample"]["price_start"]
    if to_date is None:
        to_date = settings["sample"]["price_end"]

    # Find all currencies used in the universe
    db_currencies = conn.execute("""
        SELECT DISTINCT currency FROM dim_asset
        WHERE currency IS NOT NULL AND currency != ''
    """).fetchall()
    currencies = set(c[0] for c in db_currencies)

    # Add core currencies
    currencies.update(CORE_CURRENCIES)

    # Remove USD (base) — we download X/USD pairs
    currencies.discard("USD")

    # Special cases: GBX (pence) → GBP
    if "GBX" in currencies:
        currencies.discard("GBX")
        currencies.add("GBP")
    if "ILA" in currencies:  # Israeli Agorot → ILS
        currencies.discard("ILA")
        currencies.add("ILS")

    logger.info("Downloading FX rates for %d currencies against USD",
                len(currencies))

    for ccy in tqdm(sorted(currencies), desc="FX pairs"):
        pair = f"{ccy}-USD"

        data = client.get_forex_history(pair, from_date, to_date)

        if data is None or len(data) == 0:
            # Try reverse pair
            pair_rev = f"USD-{ccy}"
            data = client.get_forex_history(pair_rev, from_date, to_date)
            if data is None or len(data) == 0:
                logger.warning("  No FX data for %s or %s", pair, pair_rev)
                continue
            # Invert the rate
            for row in data:
                if row.get("close") and row["close"] != 0:
                    row["close"] = 1.0 / row["close"]
                    row["adjusted_close"] = 1.0 / row.get("adjusted_close",
                                                           row["close"])

        rows = []
        for d in data:
            if "date" not in d:
                continue
            rows.append((
                d["date"],
                ccy,
                "USD",
                d.get("open"),
                d.get("high"),
                d.get("low"),
                d.get("close"),
                d.get("adjusted_close"),
                d.get("volume"),
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO raw_fx_daily
                    (date, base_currency, quote_currency,
                     open, high, low, close, adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

        logger.debug("  %s: %d daily rates", pair, len(rows))

    # Also download EUR/USD cross for EUR-based returns
    logger.info("Downloading EUR-USD cross rate...")
    eur_data = client.get_forex_history("EUR-USD", from_date, to_date)
    if eur_data:
        rows = []
        for d in eur_data:
            if "date" not in d:
                continue
            rows.append((
                d["date"], "EUR", "USD",
                d.get("open"), d.get("high"), d.get("low"),
                d.get("close"), d.get("adjusted_close"), d.get("volume"),
            ))
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO raw_fx_daily
                    (date, base_currency, quote_currency,
                     open, high, low, close, adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

    conn.close()
    logger.info("FX download complete. API calls: %d", client.request_count)
