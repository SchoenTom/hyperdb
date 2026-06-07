"""
HyperDataBank — Universe Builder
─────────────────────────────────
Builds the complete instrument universe across all exchanges.

Design principle: Store EVERY instrument EODHD knows about.
    - No asset class filtering (equities, ETFs, bonds, warrants — all stored)
    - No exchange filtering
    - No currency filtering
    - No domicile filtering

The dim_asset table is the authoritative master of all instruments.
Downstream research scripts filter as needed.
"""

import duckdb
from datetime import date
from tqdm import tqdm

from src.core.config import (load_exchanges, load_settings, eodhd_type_to_class,
                              load_universe_skip_codes)
from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.universe")


def _make_asset_id(ticker: str, exchange: str, asset_class: str) -> str:
    """Construct canonical asset_id: '{exchange}:{ticker}:{class}'"""
    return f"{exchange}:{ticker}:{asset_class}"


def _make_ticker_api(ticker: str, exchange: str) -> str:
    """Construct EODHD API ticker: '{ticker}.{exchange}'"""
    return f"{ticker}.{exchange}"


def build_exchange_universe(exchange_code: str,
                            client: EODHDClient,
                            conn: duckdb.DuckDBPyConnection) -> dict:
    """Download and store all instruments for a single exchange.

    Returns dict with counts: {active, delisted, total, new, updated}.
    """
    logger.info("Building universe for exchange: %s", exchange_code)

    # Fetch active tickers
    active_raw = client.get_exchange_symbols(exchange_code, delisted=False)
    if active_raw is None:
        logger.error("Failed to fetch active symbols for %s", exchange_code)
        return {"active": 0, "delisted": 0, "total": 0, "new": 0, "updated": 0}

    active_codes = {t.get("Code") for t in active_raw}
    for t in active_raw:
        t["_is_active"] = True

    # Fetch delisted tickers
    delisted_raw = client.get_exchange_symbols(exchange_code, delisted=True)
    delisted_list = []
    if delisted_raw:
        for t in delisted_raw:
            if t.get("Code") not in active_codes:
                t["_is_active"] = False
                delisted_list.append(t)

    all_tickers = active_raw + delisted_list

    logger.info("  %s: %d active, %d delisted, %d total",
                exchange_code, len(active_raw), len(delisted_list),
                len(all_tickers))

    new_count = 0
    updated_count = 0
    today = date.today().isoformat()

    for t in all_tickers:
        ticker = t.get("Code", "")
        name = t.get("Name", "")
        isin = t.get("Isin") or None
        currency = t.get("Currency", "")
        eodhd_type = t.get("Type", "")
        asset_class = eodhd_type_to_class(eodhd_type)
        is_active = t["_is_active"]
        country = t.get("Country") or None

        asset_id = _make_asset_id(ticker, exchange_code, asset_class)
        ticker_api = _make_ticker_api(ticker, exchange_code)

        # Check if asset already exists
        existing = conn.execute(
            "SELECT asset_id FROM dim_asset WHERE asset_id = ?",
            [asset_id]
        ).fetchone()

        if existing:
            # Update: refresh is_active status and last_seen
            conn.execute("""
                UPDATE dim_asset
                SET is_active = ?, last_seen = ?, name = ?,
                    isin = COALESCE(?, isin), updated_at = current_timestamp
                WHERE asset_id = ?
            """, [is_active, today, name, isin, asset_id])
            updated_count += 1
        else:
            # Insert new asset
            conn.execute("""
                INSERT INTO dim_asset
                    (asset_id, ticker, exchange_code, isin, name,
                     asset_class, eodhd_type, currency,
                     country_domicile, is_active, ticker_api,
                     first_seen, last_seen, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        current_timestamp)
            """, [asset_id, ticker, exchange_code, isin, name,
                  asset_class, eodhd_type, currency,
                  country, is_active, ticker_api,
                  today, today])
            new_count += 1

    return {
        "active": len(active_raw),
        "delisted": len(delisted_list),
        "total": len(all_tickers),
        "new": new_count,
        "updated": updated_count,
    }


def build_universe(exchanges: list[str] | None = None,
                   tier: int | None = None) -> None:
    """Build the instrument universe for specified exchanges.

    Args:
        exchanges: List of exchange codes. If None, uses tier parameter.
        tier: Maximum tier to include (1=core only, 4=all). If None, all.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()

    exchange_registry = load_exchanges()

    # Determine which exchanges to process
    if exchanges:
        target_exchanges = exchanges
    elif tier is not None:
        target_exchanges = [
            code for code, meta in exchange_registry.items()
            if meta.get("tier", 4) <= tier
        ]
    else:
        target_exchanges = list(exchange_registry.keys())

    # Filter out non-exchange entries — configurable via settings.yaml
    skip_codes = load_universe_skip_codes()
    equity_exchanges = [e for e in target_exchanges if e not in skip_codes]

    logger.info("Building universe for %d exchanges...", len(equity_exchanges))

    # Populate dim_exchange from registry
    for code in equity_exchanges:
        meta = exchange_registry.get(code, {})
        existing = conn.execute(
            "SELECT exchange_code FROM dim_exchange WHERE exchange_code = ?",
            [code]
        ).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO dim_exchange
                    (exchange_code, exchange_name, country_iso2, region,
                     default_currency, timezone, eodhd_code, tier, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [code, meta.get("name"), meta.get("country"),
                  meta.get("region"), meta.get("currency"),
                  meta.get("timezone"), code, meta.get("tier", 4),
                  meta.get("notes")])

    # Build universe per exchange
    total_stats = {"active": 0, "delisted": 0, "total": 0, "new": 0, "updated": 0}

    for ex_code in tqdm(equity_exchanges, desc="Exchanges"):
        stats = build_exchange_universe(ex_code, client, conn)
        for k in total_stats:
            total_stats[k] += stats[k]

    # Handle special asset classes: FOREX pairs
    if "FOREX" in target_exchanges or tier is None or exchanges is None:
        logger.info("Building FOREX universe...")
        fx_symbols = client.get_exchange_symbols("FOREX")
        if fx_symbols:
            for t in fx_symbols:
                ticker = t.get("Code", "")
                asset_id = f"FOREX:{ticker}:forex"
                existing = conn.execute(
                    "SELECT asset_id FROM dim_asset WHERE asset_id = ?",
                    [asset_id]
                ).fetchone()
                if not existing:
                    conn.execute("""
                        INSERT INTO dim_asset
                            (asset_id, ticker, exchange_code, name,
                             asset_class, eodhd_type, currency, is_active,
                             ticker_api, first_seen, last_seen)
                        VALUES (?, ?, 'FOREX', ?, 'forex', 'Currency', ?,
                                TRUE, ?, ?, ?)
                    """, [asset_id, ticker, t.get("Name", ""),
                          t.get("Currency", "USD"),
                          f"{ticker}.FOREX",
                          date.today().isoformat(),
                          date.today().isoformat()])
            logger.info("  FOREX: %d pairs", len(fx_symbols))

    # Handle crypto
    if "CC" in target_exchanges or tier is None or exchanges is None:
        logger.info("Building Crypto universe...")
        cc_symbols = client.get_exchange_symbols("CC")
        if cc_symbols:
            for t in cc_symbols:
                ticker = t.get("Code", "")
                asset_id = f"CC:{ticker}:crypto"
                existing = conn.execute(
                    "SELECT asset_id FROM dim_asset WHERE asset_id = ?",
                    [asset_id]
                ).fetchone()
                if not existing:
                    conn.execute("""
                        INSERT INTO dim_asset
                            (asset_id, ticker, exchange_code, name,
                             asset_class, eodhd_type, currency, is_active,
                             ticker_api, first_seen, last_seen)
                        VALUES (?, ?, 'CC', ?, 'crypto', 'Crypto', 'USD',
                                TRUE, ?, ?, ?)
                    """, [asset_id, ticker, t.get("Name", ""),
                          f"{ticker}.CC",
                          date.today().isoformat(),
                          date.today().isoformat()])
            logger.info("  Crypto: %d pairs", len(cc_symbols))

    # Handle INDX (world indices) — only if INDX is NOT in skip_codes
    if "INDX" not in skip_codes and (
        "INDX" in target_exchanges or tier is None or exchanges is None
    ):
        logger.info("Building INDX (indices) universe...")
        indx_symbols = client.get_exchange_symbols("INDX")
        if indx_symbols:
            for t in indx_symbols:
                ticker = t.get("Code", "")
                asset_id = f"INDX:{ticker}:index"
                existing = conn.execute(
                    "SELECT asset_id FROM dim_asset WHERE asset_id = ?",
                    [asset_id]
                ).fetchone()
                if not existing:
                    conn.execute("""
                        INSERT INTO dim_asset
                            (asset_id, ticker, exchange_code, name,
                             asset_class, eodhd_type, currency, is_active,
                             ticker_api, first_seen, last_seen)
                        VALUES (?, ?, 'INDX', ?, 'index', ?,
                                ?, TRUE, ?, ?, ?)
                    """, [asset_id, ticker, t.get("Name", ""),
                          t.get("Type", "Index"),
                          t.get("Currency", "USD"),
                          f"{ticker}.INDX",
                          date.today().isoformat(),
                          date.today().isoformat()])
            logger.info("  INDX: %d indices", len(indx_symbols))

    # Handle GBOND (government bonds)
    if "GBOND" not in skip_codes:
        gbond_in_scope = (
            (exchanges and "GBOND" in exchanges)
            or (tier is not None
                and exchange_registry.get("GBOND", {}).get("tier", 4) <= tier)
            or (exchanges is None and tier is None)
        )
        if gbond_in_scope:
            logger.info("Building GBOND (government bonds) universe...")
            gbond_symbols = client.get_exchange_symbols("GBOND")
            if gbond_symbols:
                for t in gbond_symbols:
                    ticker = t.get("Code", "")
                    asset_class = eodhd_type_to_class(t.get("Type", "Bond"))
                    asset_id = f"GBOND:{ticker}:{asset_class}"
                    existing = conn.execute(
                        "SELECT asset_id FROM dim_asset WHERE asset_id = ?",
                        [asset_id]
                    ).fetchone()
                    if not existing:
                        conn.execute("""
                            INSERT INTO dim_asset
                                (asset_id, ticker, exchange_code, name,
                                 asset_class, eodhd_type, currency,
                                 is_active, ticker_api, first_seen, last_seen)
                            VALUES (?, ?, 'GBOND', ?, ?, ?, ?,
                                    TRUE, ?, ?, ?)
                        """, [asset_id, ticker, t.get("Name", ""),
                              asset_class, t.get("Type", "Bond"),
                              t.get("Currency", "USD"),
                              f"{ticker}.GBOND",
                              date.today().isoformat(),
                              date.today().isoformat()])
                logger.info("  GBOND: %d instruments", len(gbond_symbols))

    conn.close()

    logger.info("Universe build complete. Total: %d instruments "
                "(%d new, %d updated)",
                total_stats["total"], total_stats["new"],
                total_stats["updated"])


def get_universe_summary(conn: duckdb.DuckDBPyConnection | None = None) -> str:
    """Return a human-readable summary of the current universe."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    lines = ["=" * 60, "HYPERDB UNIVERSE SUMMARY", "=" * 60, ""]

    # Total counts
    total = conn.execute("SELECT COUNT(*) FROM dim_asset").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM dim_asset WHERE is_active = TRUE"
    ).fetchone()[0]
    lines.append(f"Total instruments: {total:,}")
    lines.append(f"  Active: {active:,}")
    lines.append(f"  Delisted/Inactive: {total - active:,}")
    lines.append("")

    # By asset class
    lines.append("By asset class:")
    rows = conn.execute("""
        SELECT asset_class, COUNT(*), SUM(CASE WHEN is_active THEN 1 ELSE 0 END)
        FROM dim_asset GROUP BY asset_class ORDER BY COUNT(*) DESC
    """).fetchall()
    for cls, cnt, act in rows:
        lines.append(f"  {cls:<20s}  {cnt:>8,}  (active: {int(act):,})")
    lines.append("")

    # By exchange
    lines.append("By exchange (top 20):")
    rows = conn.execute("""
        SELECT exchange_code, COUNT(*),
               SUM(CASE WHEN is_active THEN 1 ELSE 0 END)
        FROM dim_asset GROUP BY exchange_code
        ORDER BY COUNT(*) DESC LIMIT 20
    """).fetchall()
    for ex, cnt, act in rows:
        lines.append(f"  {ex:<10s}  {cnt:>8,}  (active: {int(act):,})")

    if close_after:
        conn.close()

    return "\n".join(lines)
