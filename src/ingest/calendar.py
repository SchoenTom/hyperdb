"""
HyperDataBank — Trading Calendar Builder
─────────────────────────────────────────
Builds exchange-specific trading calendars from actual price data.

Rather than relying on EODHD's trading hours endpoint (which gives
current hours but not historical holidays), we infer the trading
calendar from the price data itself:

    A date is a trading day for exchange X if at least one instrument
    on exchange X has a price observation on that date.

This is the most reliable method for historical calendars.
"""

import duckdb
import pandas as pd

from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.calendar")


def build_calendar(exchange_code: str | None = None) -> None:
    """Build the trading calendar from actual price observations.

    Args:
        exchange_code: Build for a specific exchange. None = all exchanges.
    """
    init_schema()
    conn = get_connection()

    # Get target exchanges
    if exchange_code:
        exchanges = [(exchange_code,)]
    else:
        exchanges = conn.execute("""
            SELECT DISTINCT exchange_code FROM dim_asset
            WHERE exchange_code NOT IN ('FOREX', 'CC', 'INDX', 'COMM',
                                         'BOND', 'MONEY')
        """).fetchall()

    logger.info("Building trading calendar for %d exchanges...",
                len(exchanges))

    for (ex_code,) in exchanges:
        # Find all unique dates with price data for this exchange
        trading_dates = conn.execute("""
            SELECT DISTINCT p.date
            FROM bronze_price_daily p
            JOIN dim_asset a ON p.asset_id = a.asset_id
            WHERE a.exchange_code = ?
            ORDER BY p.date
        """, [ex_code]).fetchall()

        if not trading_dates:
            logger.debug("  %s: no price data yet", ex_code)
            continue

        trading_set = set(row[0] for row in trading_dates)

        # Generate full date range
        min_date = min(trading_set)
        max_date = max(trading_set)
        all_dates = pd.date_range(start=min_date, end=max_date, freq="D")

        # Insert into dim_calendar
        rows = []
        for d in all_dates:
            date_str = d.strftime("%Y-%m-%d")
            is_trading = d.date() in trading_set
            rows.append((date_str, ex_code, is_trading))

        # Batch insert
        conn.executemany("""
            INSERT OR REPLACE INTO dim_calendar
                (date, exchange_code, is_trading_day)
            VALUES (?, ?, ?)
        """, rows)

        n_trading = sum(1 for r in rows if r[2])
        logger.info("  %s: %s to %s, %d trading days / %d calendar days",
                     ex_code, min_date, max_date, n_trading, len(rows))

    conn.close()
    logger.info("Trading calendar build complete.")
