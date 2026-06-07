"""
HyperDataBank — Risk Metric Estimation
───────────────────────────────────────
Computes rolling beta estimates using the Frazzini & Pedersen (2014)
methodology with Vasicek shrinkage, extended for international markets.

For each instrument, we estimate beta against:
    1. The LOCAL market (Fama-French MKT factor for the instrument's region)
    2. The GLOBAL market (Fama-French Global MKT factor)

Methodology (Frazzini & Pedersen 2014):
    beta_ts = rho(r_i, r_m) * sigma_i / sigma_m

    where:
        sigma_i = 1-year rolling std of daily excess returns
        sigma_m = 1-year rolling std of daily market excess returns
        rho     = 5-year rolling correlation of 3-day overlapping log returns

    Vasicek shrinkage:
        beta = w * beta_ts + (1 - w) * prior
        w     = 0.6 (configurable)
        prior = 1.0 (cross-sectional mean)

Parameters are configurable in config/settings.yaml under 'beta'.
"""

import pandas as pd
import numpy as np

from src.core.config import load_settings
from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.risk")

# Region mapping: exchange_code → FF factor region
EXCHANGE_TO_REGION = {
    # North America
    "US": "US", "TO": "US", "V": "US", "MX": "US",
    # Europe
    "LSE": "Europe", "XETRA": "Europe", "PA": "Europe", "AS": "Europe",
    "SW": "Europe", "MI": "Europe", "MC": "Europe", "BR": "Europe",
    "LS": "Europe", "IR": "Europe", "VI": "Europe", "HE": "Europe",
    "CO": "Europe", "ST": "Europe", "OL": "Europe",
    "F": "Europe", "STU": "Europe", "MU": "Europe",
    "BE": "Europe", "DU": "Europe", "HA": "Europe", "HM": "Europe",
    "WA": "Europe", "PR": "Europe", "BU": "Europe", "AT": "Europe",
    "IS": "Europe",
    # Japan — not available on EODHD as of 2026
    # Asia-Pacific (ex Japan)
    "HK": "Asia-Pacific", "AU": "Asia-Pacific", "SG": "Asia-Pacific",
    "KO": "Asia-Pacific", "TW": "Asia-Pacific", "NZ": "Asia-Pacific",
    "SHG": "Asia-Pacific", "SHE": "Asia-Pacific",
    "NSE": "Asia-Pacific", "BSE": "Asia-Pacific",
    "BK": "Asia-Pacific", "KLSE": "Asia-Pacific",
    "JK": "Asia-Pacific", "PSE": "Asia-Pacific",
    # Emerging (where no specific regional factor exists)
    "SA": "Emerging", "BA": "Emerging", "SN": "Emerging",
    "CL": "Emerging", "LM": "Emerging",
    "JSE": "Emerging", "CA": "Emerging", "LG": "Emerging",
    "TA": "Emerging", "SR": "Emerging", "QA": "Emerging",
    "ADX": "Emerging", "DFM": "Emerging",
    "MCX": "Emerging", "VN": "Emerging", "KAR": "Emerging",
    "DH": "Emerging", "CSE": "Emerging", "NBO": "Emerging",
    "KMSE": "Emerging",
}


def estimate_betas(exchange_code: str) -> pd.DataFrame:
    """Estimate rolling betas for all instruments on an exchange.

    Returns a DataFrame with monthly beta estimates:
        asset_id, month, beta_local, beta_local_ts, sigma_i, sigma_m,
        rho_im, n_daily, n_3day, beta_global

    Args:
        exchange_code: The exchange to process.
    """
    init_schema()
    conn = get_connection()
    settings = load_settings()
    beta_cfg = settings["beta"]

    vol_window = beta_cfg["vol_window"]
    vol_min_obs = beta_cfg["vol_min_obs"]
    corr_window = beta_cfg["corr_window"]
    corr_min_obs = beta_cfg["corr_min_obs"]
    shrinkage_w = beta_cfg["shrinkage_weight"]
    beta_prior = beta_cfg["beta_prior"]

    region = EXCHANGE_TO_REGION.get(exchange_code, "Global")

    logger.info("Estimating betas for %s (region: %s)", exchange_code, region)

    # Load local market factor (daily)
    mkt_local = conn.execute("""
        SELECT date, value AS mkt_rf
        FROM factor_return
        WHERE region = ? AND model IN ('FF3', 'FF5')
          AND factor_name = 'mkt_rf' AND frequency = 'daily'
        ORDER BY date
    """, [region]).fetchdf()

    # Load risk-free rate
    rf_data = conn.execute("""
        SELECT date, value AS rf
        FROM factor_return
        WHERE region = ? AND model IN ('FF3', 'FF5')
          AND factor_name = 'rf' AND frequency = 'daily'
        ORDER BY date
    """, [region]).fetchdf()

    # Load global market factor
    mkt_global = conn.execute("""
        SELECT date, value AS mkt_global
        FROM factor_return
        WHERE region = 'Global' AND model IN ('FF3', 'FF5')
          AND factor_name = 'mkt_rf' AND frequency = 'daily'
        ORDER BY date
    """).fetchdf()

    if mkt_local.empty:
        logger.warning("  No local market factor data for region %s. "
                        "Falling back to Global.", region)
        mkt_local = mkt_global.rename(columns={"mkt_global": "mkt_rf"})

    if mkt_local.empty:
        logger.error("  No market factor data available. Cannot estimate betas.")
        conn.close()
        return pd.DataFrame()

    # Prepare market data
    mkt_local["date"] = pd.to_datetime(mkt_local["date"])
    mkt_local["mkt_total"] = mkt_local["mkt_rf"]
    if not rf_data.empty:
        rf_data["date"] = pd.to_datetime(rf_data["date"])
        mkt_local = mkt_local.merge(rf_data[["date", "rf"]], on="date", how="left")
        mkt_local["rf"] = mkt_local["rf"].fillna(0)
        mkt_local["mkt_total"] = mkt_local["mkt_rf"] + mkt_local["rf"]
    else:
        mkt_local["rf"] = 0.0

    mkt_local["log_ret_mkt"] = np.log1p(mkt_local["mkt_total"])
    mkt_local["r3_mkt"] = (
        mkt_local["log_ret_mkt"].rolling(3, min_periods=3).sum()
    )
    mkt_local["sigma_m"] = (
        mkt_local["mkt_rf"].rolling(vol_window, min_periods=vol_min_obs).std()
    )

    mkt_local = mkt_local.set_index("date")

    # Load cleaned prices for this exchange
    prices = conn.execute("""
        SELECT p.asset_id, p.date, p.adjusted_close, p.daily_return
        FROM clean_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        WHERE a.exchange_code = ?
          AND p.adjusted_close > 0
        ORDER BY p.asset_id, p.date
    """, [exchange_code]).fetchdf()

    conn.close()

    if prices.empty:
        logger.warning("  No price data for %s", exchange_code)
        return pd.DataFrame()

    prices["date"] = pd.to_datetime(prices["date"])

    # Merge with market data
    prices = prices.merge(
        mkt_local[["rf", "mkt_rf", "r3_mkt", "sigma_m"]],
        left_on="date", right_index=True, how="inner"
    )

    # Compute per-ticker quantities
    all_monthly = []
    tickers = prices["asset_id"].unique()
    logger.info("  Processing %d instruments...", len(tickers))

    for asset_id in tickers:
        df = prices[prices["asset_id"] == asset_id].copy()

        if len(df) < vol_min_obs:
            continue

        # Excess return
        df["ret_excess"] = df["daily_return"] - df["rf"]

        # 3-day overlapping log return
        df["log_ret"] = np.log1p(df["daily_return"])
        df["r3_stock"] = df["log_ret"].rolling(3, min_periods=3).sum()

        # Rolling volatility (1-year)
        df["sigma_i"] = df["ret_excess"].rolling(
            vol_window, min_periods=vol_min_obs
        ).std()
        df["n_daily"] = df["ret_excess"].rolling(
            vol_window, min_periods=vol_min_obs
        ).count()

        # Rolling correlation (5-year, 3-day returns)
        df["rho_im"] = df["r3_stock"].rolling(
            corr_window, min_periods=corr_min_obs
        ).corr(df["r3_mkt"])
        df["n_3day"] = df["r3_stock"].rolling(
            corr_window, min_periods=corr_min_obs
        ).count()

        # Beta
        df["beta_ts"] = df["rho_im"] * (df["sigma_i"] / df["sigma_m"])
        df["beta"] = shrinkage_w * df["beta_ts"] + (1 - shrinkage_w) * beta_prior

        # Aggregate to monthly (end-of-month values)
        df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()

        monthly = df.groupby("month").agg(
            beta_local=("beta", "last"),
            beta_local_ts=("beta_ts", "last"),
            sigma_i=("sigma_i", "last"),
            sigma_m=("sigma_m", "last"),
            rho_im=("rho_im", "last"),
            n_daily=("n_daily", "last"),
            n_3day=("n_3day", "last"),
        ).reset_index()
        monthly["asset_id"] = asset_id

        # Drop rows where beta is NaN (not enough data yet)
        monthly = monthly.dropna(subset=["beta_local", "sigma_i"])

        if not monthly.empty:
            all_monthly.append(monthly)

    if not all_monthly:
        logger.warning("  No valid beta estimates for %s", exchange_code)
        return pd.DataFrame()

    result = pd.concat(all_monthly, ignore_index=True)
    logger.info("  Estimated betas: %d monthly observations for %d instruments",
                len(result), result["asset_id"].nunique())

    return result
