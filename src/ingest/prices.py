"""
HyperDataBank — Price Downloader
─────────────────────────────────
Downloads end-of-day price data from EODHD into raw_price_daily.

Two modes:
    1. BACKFILL: Per-ticker historical download (initial load).
       Uses /eod/{ticker} endpoint. Slower but gets full history.

    2. BULK UPDATE: Per-exchange daily update.
       Uses /eod-bulk-last-day/{exchange} endpoint.
       One API call = all tickers for one day. Extremely efficient.

ALL fields from EODHD are stored: open, high, low, close, adjusted_close, volume.
No fields are dropped, no filtering is applied.
"""

import duckdb
from datetime import date
from tqdm import tqdm

from src.core.config import load_settings
from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.prices")


def _already_downloaded(conn: duckdb.DuckDBPyConnection,
                        asset_id: str, data_type: str) -> bool:
    """Check if this asset has already been downloaded (for resume support)."""
    row = conn.execute("""
        SELECT 1 FROM meta_download_log
        WHERE asset_id = ? AND data_type = ? AND status = 'ok'
        LIMIT 1
    """, [asset_id, data_type]).fetchone()
    return row is not None


def _log_download(conn: duckdb.DuckDBPyConnection,
                  asset_id: str, exchange_code: str,
                  data_type: str, status: str,
                  record_count: int = 0, error: str = None) -> None:
    """Record a download attempt in the meta log."""
    conn.execute("""
        INSERT INTO meta_download_log
            (asset_id, exchange_code, data_type, status,
             record_count, error_message, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [asset_id, exchange_code, data_type, status, record_count, error])


def _load_done_set(conn: duckdb.DuckDBPyConnection,
                   data_type: str,
                   exchange_code: str | None = None) -> set[str]:
    """Batch-load all already-downloaded asset_ids into a set.

    One query instead of thousands of individual lookups.
    """
    query = """
        SELECT DISTINCT asset_id FROM meta_download_log
        WHERE data_type = ? AND status = 'ok'
    """
    params: list = [data_type]
    if exchange_code:
        query += " AND exchange_code = ?"
        params.append(exchange_code)
    rows = conn.execute(query, params).fetchall()
    return {r[0] for r in rows}


def backfill_prices(exchange_code: str | None = None,
                    asset_class: str | None = None,
                    asset_classes: list[str] | None = None,
                    exchange_blacklist: list[str] | None = None,
                    resume: bool = True) -> None:
    """Download full historical prices for all instruments.

    Args:
        exchange_code: Limit to a specific exchange. None = all exchanges.
        asset_class: Limit to a specific asset class (single). None = all.
        asset_classes: Limit to multiple asset classes (e.g. ['equity', 'etf']).
                       Takes precedence over asset_class if both provided.
        exchange_blacklist: List of exchange codes to skip. Only applied when
                           exchange_code is not set (i.e. multi-exchange mode).
        resume: Skip tickers that were already downloaded successfully.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    from_date = settings["sample"]["price_start"]
    to_date = settings["sample"]["price_end"]

    # Build query to get target assets
    query = "SELECT asset_id, ticker_api, exchange_code FROM dim_asset WHERE 1=1"
    params = []

    if exchange_code:
        query += " AND exchange_code = ?"
        params.append(exchange_code)

    # Asset class filtering: list takes precedence over single value
    if asset_classes:
        placeholders = ", ".join(["?" for _ in asset_classes])
        query += f" AND asset_class IN ({placeholders})"
        params.extend(asset_classes)
    elif asset_class:
        query += " AND asset_class = ?"
        params.append(asset_class)

    # Skip FOREX and CC — they use different download paths
    query += " AND exchange_code NOT IN ('FOREX', 'CC')"

    # Apply exchange blacklist (only in multi-exchange mode)
    effective_blacklist = exchange_blacklist or []
    if effective_blacklist and not exchange_code:
        placeholders = ", ".join(["?" for _ in effective_blacklist])
        query += f" AND exchange_code NOT IN ({placeholders})"
        params.extend(effective_blacklist)

    query += " ORDER BY exchange_code, ticker"

    assets = conn.execute(query, params).fetchall()
    logger.info("Price backfill: %d instruments to process", len(assets))

    # Batch-load resume set — one query instead of N individual lookups
    done_set: set[str] = set()
    if resume:
        done_set = _load_done_set(conn, "prices", exchange_code)
        logger.info("  Resume: %d already downloaded", len(done_set))

    # --- Staging DB approach ---
    # The main DB's raw_price_daily PK index (348M+ rows) exceeds
    # available RAM (8GB machine). Write new prices into a staging DB
    # without PK constraints, then merge later.
    from src.core.config import get_db_path
    staging_path = str(get_db_path()).replace('.duckdb', '_staging.duckdb')
    staging = duckdb.connect(staging_path, config={'threads': '1', 'memory_limit': '2GB'})
    staging.execute("SET preserve_insertion_order = false")
    staging.execute("""
        CREATE TABLE IF NOT EXISTS raw_price_staging (
            asset_id        VARCHAR NOT NULL,
            date            DATE NOT NULL,
            open            DOUBLE,
            high            DOUBLE,
            low             DOUBLE,
            close           DOUBLE,
            adjusted_close  DOUBLE,
            volume          BIGINT,
            downloaded_at   TIMESTAMP DEFAULT current_timestamp
        )
    """)
    logger.info("Using staging DB at %s", staging_path)

    downloaded = 0
    skipped = 0
    failed = 0
    dirty = 0  # rows inserted since last commit
    flush_interval = settings["chunks"]["price_flush_interval"]

    for i, (asset_id, ticker_api, ex_code) in enumerate(
        tqdm(assets, desc="Downloading prices")
    ):
        # Resume support — O(1) set lookup instead of SQL query
        if resume and asset_id in done_set:
            skipped += 1
            continue

        # Fetch from EODHD
        data = client.get_eod_prices(ticker_api, from_date, to_date)

        if data is None:
            _log_download(conn, asset_id, ex_code, "prices", "failed",
                          error="API returned None")
            failed += 1
            dirty += 1
            continue

        if len(data) == 0:
            _log_download(conn, asset_id, ex_code, "prices", "no_data")
            skipped += 1
            dirty += 1
            continue

        # Insert into staging (no PK = no memory pressure)
        rows = []
        for p in data:
            if "date" not in p:
                continue
            rows.append((
                asset_id,
                p.get("date"),
                p.get("open"),
                p.get("high"),
                p.get("low"),
                p.get("close"),
                p.get("adjusted_close"),
                p.get("volume"),
            ))

        if rows:
            staging.executemany("""
                INSERT INTO raw_price_staging
                    (asset_id, date, open, high, low, close,
                     adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

        # Log download in main DB (small table, no memory issue)
        _log_download(conn, asset_id, ex_code, "prices", "ok", len(rows))
        downloaded += 1
        dirty += 1

        # Periodic commit
        if dirty >= flush_interval:
            staging.commit()
            conn.commit()
            dirty = 0
            logger.info("  Progress: %d/%d | exchange: %s | "
                        "downloaded: %d, skipped: %d, "
                        "failed: %d, API calls: %d",
                        i + 1, len(assets), ex_code,
                        downloaded, skipped, failed,
                        client.request_count)

    staging.commit()
    conn.commit()
    staging.close()
    conn.close()
    logger.info("Price backfill complete. Downloaded: %d, Skipped: %d, "
                "Failed: %d, Total API calls: %d",
                downloaded, skipped, failed, client.request_count)
    if downloaded > 0:
        logger.info("New prices are in staging DB: %s", staging_path)
        logger.info("Merge into main DB later with: "
                     "ATTACH '%s' AS stg; "
                     "INSERT OR IGNORE INTO raw_price_daily "
                     "SELECT * FROM stg.raw_price_staging;",
                     staging_path)


def bulk_update_prices(exchange_code: str,
                       target_date: str | None = None) -> None:
    """Download prices for ALL tickers on an exchange for a single day.

    Uses the bulk API endpoint — one call per exchange.
    This is the primary method for daily/weekly updates.

    Args:
        exchange_code: Exchange to update.
        target_date: Date string 'YYYY-MM-DD'. None = latest available.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()

    logger.info("Bulk price update for %s (date: %s)",
                exchange_code, target_date or "latest")

    data = client.get_eod_bulk(exchange_code, date=target_date)

    if data is None:
        logger.error("Bulk API returned None for %s", exchange_code)
        conn.close()
        return

    logger.info("  Received %d records from bulk API", len(data))

    inserted = 0
    for record in data:
        code = record.get("code", "")
        # Look up asset_id
        row = conn.execute(
            "SELECT asset_id FROM dim_asset WHERE ticker = ? AND exchange_code = ?",
            [code, exchange_code]
        ).fetchone()

        if row is None:
            # Unknown ticker — might be new listing. Skip for now,
            # will be picked up on next universe rebuild.
            continue

        asset_id = row[0]
        try:
            conn.execute("""
                INSERT OR IGNORE INTO raw_price_daily
                    (asset_id, date, open, high, low, close,
                     adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                asset_id,
                record.get("date"),
                record.get("open"),
                record.get("high"),
                record.get("low"),
                record.get("close"),
                record.get("adjusted_close"),
                record.get("volume"),
            ])
            inserted += 1
        except Exception as e:
            logger.debug("Insert error for %s: %s", asset_id, e)

    conn.close()
    logger.info("Bulk update complete for %s: %d records inserted",
                exchange_code, inserted)


def bulk_update_all_exchanges(target_date: str | None = None) -> None:
    """Run bulk price update for ALL exchanges with data in the universe."""
    from src.core.config import load_exchange_blacklist
    blacklist = load_exchange_blacklist()
    static_skip = ['FOREX', 'CC', 'INDX', 'COMM', 'BOND', 'MONEY', 'GBOND']
    all_skip = list(set(static_skip + blacklist))
    placeholders = ", ".join(["?" for _ in all_skip])

    conn = get_connection()
    exchanges = conn.execute(f"""
        SELECT DISTINCT exchange_code FROM dim_asset
        WHERE exchange_code NOT IN ({placeholders})
    """, all_skip).fetchall()
    conn.close()

    logger.info("Bulk updating %d exchanges...", len(exchanges))
    for (ex_code,) in exchanges:
        bulk_update_prices(ex_code, target_date)


def _backfill_exchange(exchange_code: str, client: EODHDClient,
                       conn, from_date: str, to_date: str,
                       desc: str, resume: bool = True) -> dict:
    """Download historical prices for all assets on a single exchange.

    Shared logic for download_indices() and download_bonds().
    Returns dict with counts: {downloaded, skipped, failed}.
    """
    assets = conn.execute("""
        SELECT asset_id, ticker_api, exchange_code
        FROM dim_asset
        WHERE exchange_code = ?
        ORDER BY ticker
    """, [exchange_code]).fetchall()

    if not assets:
        logger.warning("No %s instruments in dim_asset. "
                       "Run 'universe' first.", exchange_code)
        return {"downloaded": 0, "skipped": 0, "failed": 0}

    logger.info("%s: %d instruments to process", desc, len(assets))

    # Batch-load resume set
    done_set: set[str] = set()
    if resume:
        done_set = _load_done_set(conn, "prices", exchange_code)

    downloaded = 0
    skipped = 0
    failed = 0

    for asset_id, ticker_api, ex_code in tqdm(assets, desc=desc):
        if resume and asset_id in done_set:
            skipped += 1
            continue

        data = client.get_eod_prices(ticker_api, from_date, to_date)

        if data is None:
            _log_download(conn, asset_id, ex_code, "prices", "failed",
                          error="API returned None")
            failed += 1
            continue

        if len(data) == 0:
            _log_download(conn, asset_id, ex_code, "prices", "no_data")
            skipped += 1
            continue

        rows = []
        for p in data:
            if "date" not in p:
                continue
            rows.append((
                asset_id, p.get("date"), p.get("open"), p.get("high"),
                p.get("low"), p.get("close"), p.get("adjusted_close"),
                p.get("volume"),
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO raw_price_daily
                    (asset_id, date, open, high, low, close,
                     adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

        _log_download(conn, asset_id, ex_code, "prices", "ok", len(rows))
        downloaded += 1

    logger.info("%s complete. Downloaded: %d, Skipped: %d, "
                "Failed: %d, API calls: %d",
                desc, downloaded, skipped, failed, client.request_count)
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def download_indices(resume: bool = True) -> None:
    """Download historical price data for all world indices (INDX exchange)."""
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    _backfill_exchange(
        "INDX", client, conn,
        settings["sample"]["price_start"],
        settings["sample"]["price_end"],
        desc="Indices", resume=resume,
    )
    conn.close()


def download_bonds(resume: bool = True) -> None:
    """Download historical price data for government bonds (GBOND exchange)."""
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    _backfill_exchange(
        "GBOND", client, conn,
        settings["sample"]["price_start"],
        settings["sample"]["price_end"],
        desc="Bonds", resume=resume,
    )
    conn.close()
