"""
HyperDataBank — Monthly Panel Builder
──────────────────────────────────────
Combines returns, risk metrics, and metadata into the
panel_monthly table.

This is the primary analysis-ready output of HyperDataBank.
Each row represents one instrument-month observation with:
    - Returns in local, USD, and EUR
    - Excess returns (local and USD)
    - Risk metrics (beta, volatility, correlation)
    - Liquidity measures (price, volume, trading days)
    - Quality flags (informational, not filters)

NO FILTERING is applied. The panel contains every instrument-month
for which we have valid data. Researchers filter downstream.
"""

import pandas as pd
import numpy as np
import duckdb

from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.transform.returns import compute_monthly_returns
from src.transform.risk import estimate_betas

logger = get_logger("hyperdb.panel")


def build_panel(exchange_code: str) -> None:
    """Build the panel monthly panel for a specific exchange.

    This combines:
        1. Monthly returns (local, USD, EUR)
        2. Beta estimates (local, global)
        3. Liquidity metrics
        4. Quality flags

    Results are stored in panel_monthly.

    Args:
        exchange_code: The exchange to process.
    """
    init_schema()
    conn = get_connection()

    logger.info("Building monthly panel for %s...", exchange_code)

    # Step 1: Compute monthly returns
    returns_df = compute_monthly_returns(exchange_code)
    if returns_df.empty:
        logger.warning("No returns data for %s — skipping.", exchange_code)
        conn.close()
        return

    # Step 2: Estimate betas
    risk_df = estimate_betas(exchange_code)

    # Step 3: Load monthly risk-free rate for excess returns
    region_map = {
        "US": "US", "LSE": "Europe", "XETRA": "Europe", "PA": "Europe",
        "AS": "Europe", "HK": "Asia-Pacific",
    }
    region = region_map.get(exchange_code, "Global")

    rf_monthly = conn.execute("""
        SELECT
            DATE_TRUNC('month', date) AS month,
            SUM(value) AS rf_monthly
        FROM factor_return
        WHERE region = ? AND factor_name = 'rf' AND frequency = 'daily'
        GROUP BY DATE_TRUNC('month', date)
    """, [region]).fetchdf()

    # Step 4: Merge everything
    panel = returns_df.copy()
    panel["month"] = pd.to_datetime(panel["month"])

    # Merge risk metrics
    if not risk_df.empty:
        risk_df["month"] = pd.to_datetime(risk_df["month"])
        panel = panel.merge(
            risk_df[["asset_id", "month", "beta_local", "beta_local_ts",
                      "sigma_i", "sigma_m", "rho_im", "n_daily", "n_3day"]],
            on=["asset_id", "month"],
            how="left",
        )
    else:
        for col in ["beta_local", "beta_local_ts", "sigma_i", "sigma_m",
                     "rho_im", "n_daily", "n_3day"]:
            panel[col] = np.nan

    # Merge risk-free rate for excess returns
    if not rf_monthly.empty:
        rf_monthly["month"] = pd.to_datetime(rf_monthly["month"])
        panel = panel.merge(rf_monthly, on="month", how="left")
        panel["rf_monthly"] = panel["rf_monthly"].fillna(0)
    else:
        panel["rf_monthly"] = 0.0

    # Compute excess returns
    panel["excess_return_local"] = panel["return_local"] - panel["rf_monthly"]
    panel["excess_return_usd"] = panel["return_usd"] - panel["rf_monthly"]
    panel["excess_return_eur"] = panel.get("return_eur", np.nan)

    # Quality flag based on data characteristics
    panel["data_quality_flag"] = "clean"
    panel.loc[panel["trading_days"] < 10, "data_quality_flag"] = "thin"
    panel.loc[panel["return_local"].abs() > 2.0, "data_quality_flag"] = "extreme"
    panel.loc[panel["beta_local"].isna(), "data_quality_flag"] = "no_beta"

    # Global beta placeholder (requires global market data)
    panel["beta_global"] = np.nan
    panel["turnover_ratio"] = np.nan

    # Step 5: Write to panel_monthly
    # Delete existing data for this exchange (idempotent)
    conn.execute("""
        DELETE FROM panel_monthly
        WHERE asset_id IN (
            SELECT asset_id FROM dim_asset WHERE exchange_code = ?
        )
    """, [exchange_code])

    # Insert row by row (DuckDB doesn't support executemany with DataFrames
    # well for REPLACE operations, and we want exact control)
    columns = [
        "asset_id", "month", "exchange_code", "asset_class", "currency",
        "return_local", "excess_return_local",
        "return_usd", "excess_return_usd",
        "return_eur", "excess_return_eur",
        "beta_local", "beta_local_ts", "sigma_i", "sigma_m", "rho_im",
        "beta_global",
        "median_price_local", "mean_volume", "trading_days", "turnover_ratio",
        "n_daily", "n_3day", "data_quality_flag",
    ]

    # Ensure all columns exist
    for col in columns:
        if col not in panel.columns:
            panel[col] = np.nan

    # Use DuckDB's DataFrame insert for efficiency
    panel_out = panel[columns].copy()
    panel_out["month"] = panel_out["month"].dt.strftime("%Y-%m-%d")

    conn.execute("""
        INSERT INTO panel_monthly
        SELECT * FROM panel_out
    """)

    count = conn.execute("""
        SELECT COUNT(*) FROM panel_monthly
        WHERE asset_id IN (
            SELECT asset_id FROM dim_asset WHERE exchange_code = ?
        )
    """, [exchange_code]).fetchone()[0]

    conn.close()

    logger.info("Panel for %s: %d monthly observations, %d instruments",
                exchange_code, count,
                panel["asset_id"].nunique())


def build_panel_all(exchanges: list[str] | None = None) -> None:
    """Build the monthly panel for multiple exchanges.

    Args:
        exchanges: List of exchange codes. None = all exchanges with data.
    """
    conn = get_connection()

    if exchanges is None:
        rows = conn.execute("""
            SELECT DISTINCT a.exchange_code
            FROM clean_price_daily p
            JOIN dim_asset a ON p.asset_id = a.asset_id
            WHERE a.exchange_code NOT IN ('FOREX', 'CC', 'INDX',
                                           'COMM', 'BOND', 'MONEY')
        """).fetchall()
        exchanges = [r[0] for r in rows]

    conn.close()

    logger.info("Building panels for %d exchanges...", len(exchanges))
    for ex_code in exchanges:
        build_panel(ex_code)

    logger.info("All panels built.")
