"""
HyperDataBank — Multi-Currency Return Computation
──────────────────────────────────────────────────
Computes returns in multiple currencies for cross-market comparability.

For each instrument, returns exist in three dimensions:
    1. Local currency (as traded on the exchange)
    2. USD (global reference currency)
    3. EUR (European reference currency)

Currency conversion formula:
    return_usd = (1 + return_local) * (FX_t / FX_{t-1}) - 1

    where FX = local_currency per USD

For USD-denominated instruments, return_usd = return_local.
For EUR-denominated instruments, return_eur = return_local.

Excess returns subtract the risk-free rate of the respective currency:
    excess_return_local = return_local - rf_local
    excess_return_usd   = return_usd - rf_usd
"""

import pandas as pd
import numpy as np
import duckdb

from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.returns")


def compute_monthly_returns(exchange_code: str | None = None) -> pd.DataFrame:
    """Compute monthly total returns in local, USD, and EUR.

    Returns a DataFrame with columns:
        asset_id, month, exchange_code, asset_class, currency,
        return_local, return_usd, return_eur

    Args:
        exchange_code: Compute for a specific exchange. None = all.
    """
    init_schema()
    conn = get_connection()

    logger.info("Computing monthly returns for %s...",
                exchange_code or "ALL exchanges")

    # Build query for silver prices with asset metadata
    where_clause = ""
    params = []
    if exchange_code:
        where_clause = "AND a.exchange_code = ?"
        params.append(exchange_code)

    # Compute monthly returns from daily silver prices
    # Monthly return = (last_adj / first_adj) - 1
    monthly_local = conn.execute(f"""
        WITH daily AS (
            SELECT
                p.asset_id,
                a.exchange_code,
                a.asset_class,
                a.currency,
                p.date,
                p.adjusted_close,
                p.close,
                p.volume,
                DATE_TRUNC('month', p.date) AS month
            FROM silver_price_daily p
            JOIN dim_asset a ON p.asset_id = a.asset_id
            WHERE p.adjusted_close > 0
              {where_clause}
        ),
        windowed AS (
            SELECT
                asset_id,
                exchange_code,
                asset_class,
                currency,
                month,
                close,
                volume,
                FIRST_VALUE(adjusted_close)
                    OVER (PARTITION BY asset_id, month
                          ORDER BY date) AS first_adj,
                LAST_VALUE(adjusted_close)
                    OVER (PARTITION BY asset_id, month
                          ORDER BY date
                          ROWS BETWEEN UNBOUNDED PRECEDING
                          AND UNBOUNDED FOLLOWING) AS last_adj
            FROM daily
        )
        SELECT
            asset_id,
            ANY_VALUE(exchange_code) AS exchange_code,
            ANY_VALUE(asset_class) AS asset_class,
            ANY_VALUE(currency) AS currency,
            month,
            (ANY_VALUE(last_adj) / ANY_VALUE(first_adj)) - 1.0 AS return_local,
            MEDIAN(close) AS median_price_local,
            AVG(volume) AS mean_volume,
            COUNT(*) AS trading_days
        FROM windowed
        WHERE first_adj > 0
        GROUP BY asset_id, month
    """, params).fetchdf()

    if monthly_local.empty:
        logger.warning("No monthly returns computed — no silver price data.")
        conn.close()
        return monthly_local

    logger.info("  Computed %d local monthly returns", len(monthly_local))

    # Load FX rates for currency conversion
    fx_monthly = conn.execute("""
        SELECT
            base_currency,
            DATE_TRUNC('month', date) AS month,
            LAST_VALUE(rate)
                OVER (PARTITION BY base_currency, DATE_TRUNC('month', date)
                      ORDER BY date
                      ROWS BETWEEN UNBOUNDED PRECEDING
                      AND UNBOUNDED FOLLOWING) AS fx_last,
            FIRST_VALUE(rate)
                OVER (PARTITION BY base_currency, DATE_TRUNC('month', date)
                      ORDER BY date) AS fx_first
        FROM silver_fx_daily
        WHERE quote_currency = 'USD'
    """).fetchdf()

    if not fx_monthly.empty:
        fx_monthly = fx_monthly.drop_duplicates(
            subset=["base_currency", "month"]
        )
        fx_monthly["fx_return"] = (
            fx_monthly["fx_last"] / fx_monthly["fx_first"]
        ) - 1.0

    # Merge FX returns with local returns
    df = monthly_local.copy()

    # USD returns
    df["return_usd"] = df["return_local"]  # default for USD assets

    if not fx_monthly.empty:
        # For non-USD assets, adjust by FX return
        fx_map = fx_monthly.set_index(["base_currency", "month"])["fx_return"]

        for idx in df.index:
            ccy = df.at[idx, "currency"]
            month = df.at[idx, "month"]
            if ccy == "USD":
                continue
            # Handle GBX → GBP
            lookup_ccy = ccy
            if ccy == "GBX":
                lookup_ccy = "GBP"
            elif ccy == "ILA":
                lookup_ccy = "ILS"

            try:
                fx_ret = fx_map.loc[(lookup_ccy, month)]
                local_ret = df.at[idx, "return_local"]
                df.at[idx, "return_usd"] = (
                    (1 + local_ret) * (1 + fx_ret) - 1.0
                )
            except KeyError:
                df.at[idx, "return_usd"] = np.nan

    # EUR returns (via USD cross)
    eur_fx = fx_monthly[fx_monthly["base_currency"] == "EUR"].copy()
    if not eur_fx.empty:
        eur_map = eur_fx.set_index("month")["fx_return"]
        df["return_eur"] = df.apply(
            lambda row: (
                row["return_usd"]  # already in USD, now convert to EUR
                if pd.isna(row.get("return_usd"))
                else _usd_to_eur(row["return_usd"], row["month"], eur_map)
            ),
            axis=1,
        )
    else:
        df["return_eur"] = np.nan

    conn.close()
    logger.info("  Monthly returns with FX: %d rows, %d with USD, %d with EUR",
                len(df),
                df["return_usd"].notna().sum(),
                df["return_eur"].notna().sum())

    return df


def _usd_to_eur(return_usd: float, month, eur_map: pd.Series) -> float:
    """Convert a USD return to EUR return using EUR/USD FX."""
    try:
        eur_fx_ret = eur_map.loc[month]
        # EUR/USD rate: if EUR strengthened, USD return in EUR is lower
        return (1 + return_usd) / (1 + eur_fx_ret) - 1.0
    except KeyError:
        return np.nan
