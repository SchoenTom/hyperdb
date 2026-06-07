"""
HyperDataBank — Corporate Actions Downloader
──────────────────────────────────────────────
Downloads splits and dividends from EODHD into bronze tables.

ALL fields from EODHD are stored without modification:
    Splits:     date, split (ratio string)
    Dividends:  date, value, unadjustedValue, currency,
                declarationDate, recordDate, paymentDate, period
"""

import duckdb
from tqdm import tqdm

from src.core.config import load_settings
from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.corporate_actions")


def _already_downloaded(conn, asset_id, data_type):
    row = conn.execute("""
        SELECT 1 FROM meta_download_log
        WHERE asset_id = ? AND data_type = ? AND status = 'ok' LIMIT 1
    """, [asset_id, data_type]).fetchone()
    return row is not None


def _load_done_set(conn, data_type, exchange_code=None):
    """Batch-load all already-downloaded asset_ids into a set."""
    query = """
        SELECT DISTINCT asset_id FROM meta_download_log
        WHERE data_type = ? AND status = 'ok'
    """
    params = [data_type]
    if exchange_code:
        query += " AND exchange_code = ?"
        params.append(exchange_code)
    return {r[0] for r in conn.execute(query, params).fetchall()}


def _log_download(conn, asset_id, exchange_code, data_type, status,
                  record_count=0, error=None):
    conn.execute("""
        INSERT INTO meta_download_log
            (asset_id, exchange_code, data_type, status,
             record_count, error_message, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [asset_id, exchange_code, data_type, status, record_count, error])


def download_splits(exchange_code: str | None = None,
                    resume: bool = True) -> None:
    """Download split history for all equities.

    Args:
        exchange_code: Limit to a specific exchange. None = all.
        resume: Skip assets already downloaded successfully.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    from_date = settings["sample"]["corporate_action_start"]
    to_date = settings["sample"]["price_end"]

    # Only download splits for tickers that have price data downloaded
    from src.core.config import load_exchange_blacklist
    blacklist = load_exchange_blacklist()

    query = """
        SELECT a.asset_id, a.ticker_api, a.exchange_code FROM dim_asset a
        WHERE a.asset_class IN ('equity', 'etf')
        AND a.exchange_code NOT IN ('FOREX', 'CC')
        AND a.asset_id IN (
            SELECT asset_id FROM meta_download_log
            WHERE data_type = 'prices' AND status = 'ok'
        )
    """
    params = []
    if exchange_code:
        query += " AND a.exchange_code = ?"
        params.append(exchange_code)
    else:
        placeholders = ", ".join(["?" for _ in blacklist])
        query += f" AND a.exchange_code NOT IN ({placeholders})"
        params.extend(blacklist)
    query += " ORDER BY a.exchange_code, a.ticker"

    assets = conn.execute(query, params).fetchall()
    logger.info("Split download: %d instruments (only those with price data)", len(assets))

    done_set = _load_done_set(conn, "splits", exchange_code) if resume else set()

    for asset_id, ticker_api, ex_code in tqdm(assets, desc="Splits"):
        if resume and asset_id in done_set:
            continue

        data = client.get_splits(ticker_api, from_date, to_date)

        if data is None:
            _log_download(conn, asset_id, ex_code, "splits", "failed")
            continue

        rows = []
        for s in data:
            if "date" not in s:
                continue
            rows.append((asset_id, s["date"], s.get("split")))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO bronze_split
                    (asset_id, date, split_ratio)
                VALUES (?, ?, ?)
            """, rows)

        _log_download(conn, asset_id, ex_code, "splits", "ok", len(rows))

    conn.close()
    logger.info("Split download complete. API calls: %d", client.request_count)


def download_dividends(exchange_code: str | None = None,
                       resume: bool = True) -> None:
    """Download dividend history for all equities and ETFs.

    Args:
        exchange_code: Limit to a specific exchange. None = all.
        resume: Skip assets already downloaded successfully.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()
    settings = load_settings()

    from_date = settings["sample"]["corporate_action_start"]
    to_date = settings["sample"]["price_end"]

    # Only download dividends for tickers that have price data downloaded
    from src.core.config import load_exchange_blacklist
    blacklist = load_exchange_blacklist()

    query = """
        SELECT a.asset_id, a.ticker_api, a.exchange_code FROM dim_asset a
        WHERE a.asset_class IN ('equity', 'etf')
        AND a.exchange_code NOT IN ('FOREX', 'CC')
        AND a.asset_id IN (
            SELECT asset_id FROM meta_download_log
            WHERE data_type = 'prices' AND status = 'ok'
        )
    """
    params = []
    if exchange_code:
        query += " AND a.exchange_code = ?"
        params.append(exchange_code)
    else:
        placeholders = ", ".join(["?" for _ in blacklist])
        query += f" AND a.exchange_code NOT IN ({placeholders})"
        params.extend(blacklist)
    query += " ORDER BY a.exchange_code, a.ticker"

    assets = conn.execute(query, params).fetchall()
    logger.info("Dividend download: %d instruments (only those with price data)", len(assets))

    done_set = _load_done_set(conn, "dividends", exchange_code) if resume else set()

    for asset_id, ticker_api, ex_code in tqdm(assets, desc="Dividends"):
        if resume and asset_id in done_set:
            continue

        data = client.get_dividends(ticker_api, from_date, to_date)

        if data is None:
            _log_download(conn, asset_id, ex_code, "dividends", "failed")
            continue

        rows = []
        for d in data:
            if "date" not in d:
                continue
            rows.append((
                asset_id,
                d["date"],
                d.get("value"),
                d.get("unadjustedValue"),
                d.get("currency"),
                d.get("declarationDate") or None,
                d.get("recordDate") or None,
                d.get("paymentDate") or None,
                d.get("period"),
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO bronze_dividend
                    (asset_id, date, value, unadjusted_value, currency,
                     declaration_date, record_date, payment_date, period)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)

        _log_download(conn, asset_id, ex_code, "dividends", "ok", len(rows))

    conn.close()
    logger.info("Dividend download complete. API calls: %d",
                client.request_count)
