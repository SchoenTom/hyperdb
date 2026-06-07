"""
HyperDataBank — Data Cleaning (Raw → Cleaned)
────────────────────────────────────────────────
Minimal, transparent cleaning rules. We remove only data that is
physically impossible or clearly corrupt. We never apply opinionated
filters (price floors, volume floors, exchange filters, etc.).

Cleaning rules:
    C1: Remove rows where adjusted_close is NULL or <= 0
    C2: Remove rows where close is NULL or <= 0
    C3: Remove rows where date is NULL
    C4: Flag (but do NOT remove) extreme daily returns (|r| > 200%)
    C5: Flag (but do NOT remove) EODHD sentinel values ($99,999)
    C6: Compute daily returns and log returns

The clean_price_daily table contains every valid price observation
with precomputed returns and quality flags.

What we do NOT do here:
    - No penny stock removal
    - No volume filtering
    - No exchange filtering
    - No seasoning requirements
    - No exclusion of specific security types
    These all belong in downstream research scripts.
"""

import duckdb
import numpy as np

from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.clean")


def clean_prices(exchange_code: str | None = None) -> None:
    """Clean raw prices into cleaned layer.

    This operation is idempotent — it replaces all clean_price_daily
    rows for the specified exchange (or all exchanges).

    Args:
        exchange_code: Clean a specific exchange. None = all exchanges.
    """
    init_schema()
    conn = get_connection()

    # Determine scope
    where_clause = ""
    params = []
    if exchange_code:
        where_clause = "AND a.exchange_code = ?"
        params.append(exchange_code)

    logger.info("Cleaning prices (Raw → Cleaned) for %s...",
                exchange_code or "ALL exchanges")

    # Delete existing cleaned data for this scope (idempotent)
    if exchange_code:
        conn.execute("""
            DELETE FROM clean_price_daily
            WHERE asset_id IN (
                SELECT asset_id FROM dim_asset WHERE exchange_code = ?
            )
        """, [exchange_code])
    else:
        conn.execute("DELETE FROM clean_price_daily")

    # Insert cleaned data with computed returns.
    # Window function computes daily return within each asset.
    #
    # Cleaning rules applied:
    #   - adjusted_close > 0  (C1)
    #   - close > 0           (C2)
    #   - date IS NOT NULL    (C3)
    #
    # Flags:
    #   - 'extreme' if |daily_return| > 2.0 (200%)
    #   - 'sentinel' if close > 99000 or adjusted_close > 99000
    #   - 'clean' otherwise
    conn.execute(f"""
        INSERT INTO clean_price_daily
            (asset_id, date, open, high, low, close, adjusted_close,
             volume, daily_return, log_return, return_flag)
        SELECT
            p.asset_id,
            p.date,
            p.open,
            p.high,
            p.low,
            p.close,
            p.adjusted_close,
            p.volume,
            -- Daily return: (P_t / P_lag) - 1
            (p.adjusted_close / LAG(p.adjusted_close)
                OVER (PARTITION BY p.asset_id ORDER BY p.date)) - 1.0
                AS daily_return,
            -- Log return: ln(P_t / P_lag)
            LN(p.adjusted_close / LAG(p.adjusted_close)
                OVER (PARTITION BY p.asset_id ORDER BY p.date))
                AS log_return,
            -- Quality flag
            CASE
                WHEN p.close > 99000 OR p.adjusted_close > 99000
                    THEN 'sentinel'
                WHEN ABS((p.adjusted_close / LAG(p.adjusted_close)
                    OVER (PARTITION BY p.asset_id ORDER BY p.date)) - 1.0) > 2.0
                    THEN 'extreme'
                ELSE 'clean'
            END AS return_flag
        FROM raw_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        WHERE p.adjusted_close > 0
          AND p.close > 0
          AND p.date IS NOT NULL
          {where_clause}
        ORDER BY p.asset_id, p.date
    """, params)

    # Count results
    if exchange_code:
        stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN return_flag = 'clean' THEN 1 ELSE 0 END) AS clean,
                SUM(CASE WHEN return_flag = 'extreme' THEN 1 ELSE 0 END) AS extreme,
                SUM(CASE WHEN return_flag = 'sentinel' THEN 1 ELSE 0 END) AS sentinel
            FROM clean_price_daily
            WHERE asset_id IN (
                SELECT asset_id FROM dim_asset WHERE exchange_code = ?
            )
        """, [exchange_code]).fetchone()
    else:
        stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN return_flag = 'clean' THEN 1 ELSE 0 END) AS clean,
                SUM(CASE WHEN return_flag = 'extreme' THEN 1 ELSE 0 END) AS extreme,
                SUM(CASE WHEN return_flag = 'sentinel' THEN 1 ELSE 0 END) AS sentinel
            FROM clean_price_daily
        """).fetchone()

    total, clean, extreme, sentinel = stats
    logger.info("Cleaned prices: %d total rows", total)
    logger.info("  Clean: %d  |  Extreme returns: %d  |  Sentinel values: %d",
                clean, extreme, sentinel)

    conn.close()


def clean_fx(conn: duckdb.DuckDBPyConnection | None = None) -> None:
    """Clean raw FX rates into clean_fx_daily.

    Computes the closing rate and log returns for each currency pair.
    """
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    logger.info("Cleaning FX rates (Raw → Cleaned)...")

    conn.execute("DELETE FROM clean_fx_daily")

    conn.execute("""
        INSERT INTO clean_fx_daily (date, base_currency, quote_currency,
                                      rate, log_return)
        SELECT
            date,
            base_currency,
            quote_currency,
            close AS rate,
            LN(close / LAG(close)
                OVER (PARTITION BY base_currency, quote_currency
                      ORDER BY date)) AS log_return
        FROM raw_fx_daily
        WHERE close > 0 AND close IS NOT NULL
        ORDER BY base_currency, quote_currency, date
    """)

    count = conn.execute("SELECT COUNT(*) FROM clean_fx_daily").fetchone()[0]
    logger.info("Cleaned FX: %d rows", count)

    if close_after:
        conn.close()
