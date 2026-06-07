"""
HyperDataBank — Data Quality Scoring
─────────────────────────────────────
Computes a quality score (0.00 to 1.00) for each instrument
across five dimensions:

    completeness  (30%)  % of expected trading days with data
    consistency   (25%)  % of returns within plausible range
    timeliness    (15%)  How recent is the latest observation?
    accuracy      (20%)  Splits correctly adjusted? No sentinel values?
    depth         (10%)  How far back does the history go?

Quality scores are stored in meta_data_quality and summarized
in dim_asset.data_quality_score.

These scores are INFORMATIONAL — they do not filter data.
Researchers can use them to assess reliability of specific
markets or instruments for their analysis.
"""

import duckdb
import pandas as pd
import numpy as np
from datetime import date

from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.quality")


def compute_quality_scores(exchange_code: str | None = None) -> None:
    """Compute quality scores for all instruments.

    Args:
        exchange_code: Score a specific exchange. None = all.
    """
    init_schema()
    conn = get_connection()

    where_clause = ""
    params = []
    if exchange_code:
        where_clause = "AND a.exchange_code = ?"
        params.append(exchange_code)

    logger.info("Computing quality scores for %s...",
                exchange_code or "ALL exchanges")

    # Get all instruments with price data
    assets = conn.execute(f"""
        SELECT
            a.asset_id,
            a.exchange_code,
            MIN(p.date) AS first_date,
            MAX(p.date) AS last_date,
            COUNT(*) AS n_obs,
            SUM(CASE WHEN p.return_flag = 'extreme' THEN 1 ELSE 0 END) AS n_extreme,
            SUM(CASE WHEN p.return_flag = 'sentinel' THEN 1 ELSE 0 END) AS n_sentinel
        FROM silver_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        WHERE 1=1 {where_clause}
        GROUP BY a.asset_id, a.exchange_code
    """, params).fetchdf()

    if assets.empty:
        logger.warning("No data to score.")
        conn.close()
        return

    # Get trading day counts per exchange from calendar
    cal_counts = conn.execute("""
        SELECT exchange_code,
               MIN(date) AS cal_start,
               MAX(date) AS cal_end,
               SUM(CASE WHEN is_trading_day THEN 1 ELSE 0 END) AS total_trading_days
        FROM dim_calendar
        GROUP BY exchange_code
    """).fetchdf()

    cal_map = {}
    if not cal_counts.empty:
        cal_map = cal_counts.set_index("exchange_code")[
            "total_trading_days"
        ].to_dict()

    today = date.today()

    for _, row in assets.iterrows():
        asset_id = row["asset_id"]
        ex_code = row["exchange_code"]
        n_obs = row["n_obs"]
        n_extreme = row["n_extreme"]
        n_sentinel = row["n_sentinel"]
        first_date = pd.to_datetime(row["first_date"]).date()
        last_date = pd.to_datetime(row["last_date"]).date()

        # ── Completeness (30%) ──
        # What fraction of expected trading days have data?
        expected_days = cal_map.get(ex_code)
        if expected_days and expected_days > 0:
            # Scale by the fraction of calendar covered by this asset
            total_cal_days = (today - first_date).days
            if total_cal_days > 0:
                expected_for_asset = expected_days * min(
                    total_cal_days / max((today - first_date).days, 1), 1.0
                )
                completeness = min(n_obs / max(expected_for_asset, 1), 1.0)
            else:
                completeness = 0.0
        else:
            # Estimate: ~252 trading days/year
            years = max((last_date - first_date).days / 365.25, 0.1)
            expected = years * 252
            completeness = min(n_obs / max(expected, 1), 1.0)

        # ── Consistency (25%) ──
        # % of returns that are not extreme
        if n_obs > 1:
            consistency = 1.0 - (n_extreme / max(n_obs - 1, 1))
        else:
            consistency = 0.0

        # ── Timeliness (15%) ──
        # How recently was data last observed?
        days_since_last = (today - last_date).days
        if days_since_last <= 5:
            timeliness = 1.0
        elif days_since_last <= 30:
            timeliness = 0.8
        elif days_since_last <= 90:
            timeliness = 0.6
        elif days_since_last <= 365:
            timeliness = 0.3
        else:
            timeliness = 0.1

        # ── Accuracy (20%) ──
        # Penalize sentinel values (EODHD data errors)
        if n_sentinel == 0:
            accuracy = 1.0
        else:
            accuracy = max(1.0 - (n_sentinel / max(n_obs, 1)) * 10, 0.0)

        # ── Depth (10%) ──
        # How many years of history?
        years_history = (last_date - first_date).days / 365.25
        if years_history >= 20:
            depth = 1.0
        elif years_history >= 10:
            depth = 0.8
        elif years_history >= 5:
            depth = 0.6
        elif years_history >= 2:
            depth = 0.4
        elif years_history >= 1:
            depth = 0.2
        else:
            depth = 0.1

        # Weighted total
        total_score = (
            0.30 * completeness +
            0.25 * consistency +
            0.15 * timeliness +
            0.20 * accuracy +
            0.10 * depth
        )

        # Store individual dimension scores
        for dim_name, dim_score in [
            ("completeness", completeness),
            ("consistency", consistency),
            ("timeliness", timeliness),
            ("accuracy", accuracy),
            ("depth", depth),
            ("total", total_score),
        ]:
            conn.execute("""
                INSERT OR REPLACE INTO meta_data_quality
                    (asset_id, dimension, score, detail, computed_at)
                VALUES (?, ?, ?, ?, current_timestamp)
            """, [
                asset_id, dim_name, round(dim_score, 4),
                f"n_obs={n_obs}, extreme={n_extreme}, sentinel={n_sentinel}",
            ])

    # Summary statistics
    stats = conn.execute("""
        SELECT
            AVG(score) AS mean_score,
            MEDIAN(score) AS median_score,
            MIN(score) AS min_score,
            MAX(score) AS max_score
        FROM meta_data_quality
        WHERE dimension = 'total'
    """).fetchone()

    conn.close()

    if stats[0] is not None:
        logger.info("Quality scores computed for %d instruments", len(assets))
        logger.info("  Total score: mean=%.3f, median=%.3f, "
                     "min=%.3f, max=%.3f",
                     stats[0], stats[1], stats[2], stats[3])
    else:
        logger.info("Quality scores computed for %d instruments", len(assets))
