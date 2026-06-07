# examples.py – Quick-start query examples for HyperDB
#
# Run any section independently to explore the database.
# All queries are read-only — the database is never modified.
#
# Usage: python examples.py

import duckdb
import pandas as pd

DB = "hyperdb.duckdb"


def example_1_basic_query():
    """Load AAPL daily prices for the last 5 years."""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""
        SELECT date, open, high, low, close, adjusted_close, volume
        FROM bronze_price_daily
        WHERE asset_id = 'US:AAPL:equity'
          AND date >= '2020-01-01'
        ORDER BY date
    """).fetchdf()
    con.close()

    print("Example 1: AAPL daily prices (2020+)")
    print(f"  Rows: {len(df):,}")
    print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"  Latest close: ${df['close'].iloc[-1]:.2f}")
    print()


def example_2_monthly_panel():
    """Access the analysis-ready monthly panel."""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""
        SELECT asset_id, month, return_local, beta_local,
               median_price_local, mean_volume, trading_days
        FROM gold_monthly_panel
        WHERE exchange_code = 'US'
          AND month >= '2020-01-01'
          AND data_quality_flag IN ('clean', 'no_beta')
          AND return_local BETWEEN -1.0 AND 2.0
        ORDER BY asset_id, month
    """).fetchdf()
    con.close()

    print("Example 2: US monthly panel (2020+, plausible returns)")
    print(f"  Rows: {len(df):,}")
    print(f"  Instruments: {df['asset_id'].nunique():,}")
    print(f"  Mean monthly return: {df['return_local'].mean()*100:.2f}%")
    print()


def example_3_cross_sectional():
    """Cross-sectional snapshot: all US equities in one month."""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""
        SELECT g.asset_id, a.name, g.return_local, g.beta_local,
               g.median_price_local, g.mean_volume
        FROM gold_monthly_panel g
        JOIN dim_asset a ON g.asset_id = a.asset_id
        WHERE g.exchange_code = 'US'
          AND g.month = '2024-12-01'
          AND g.data_quality_flag IN ('clean', 'no_beta')
          AND g.return_local BETWEEN -1.0 AND 2.0
        ORDER BY g.return_local DESC
    """).fetchdf()
    con.close()

    print("Example 3: US cross-section December 2024")
    print(f"  Instruments: {len(df):,}")
    print(f"  Top 5 performers:")
    for _, r in df.head(5).iterrows():
        print(f"    {r['asset_id']:25s} {r['return_local']*100:+.1f}%")
    print()


def example_4_factor_model():
    """Load Fama-French factors for regression analysis."""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""
        SELECT date, factor_name, value
        FROM gold_factor_return
        WHERE model = 'FF3'
          AND region = 'US'
          AND frequency = 'daily'
          AND date >= '2020-01-01'
        ORDER BY date, factor_name
    """).fetchdf()
    con.close()

    pivot = df.pivot(index="date", columns="factor_name", values="value")
    print("Example 4: FF3 daily factors (US, 2020+)")
    print(f"  Days: {len(pivot):,}")
    print(f"  Factors: {list(pivot.columns)}")
    mkt_col = [c for c in pivot.columns if 'mkt' in c.lower()][0]
    print(f"  {mkt_col} mean: {pivot[mkt_col].mean():.4f}")
    print()


def example_5_corporate_actions():
    """Find all stock splits for a company."""
    con = duckdb.connect(DB, read_only=True)
    splits = con.execute("""
        SELECT s.date, s.split_ratio, a.name
        FROM bronze_split s
        JOIN dim_asset a ON s.asset_id = a.asset_id
        WHERE s.asset_id = 'US:AAPL:equity'
        ORDER BY s.date
    """).fetchdf()

    divs = con.execute("""
        SELECT date, value, currency
        FROM bronze_dividend
        WHERE asset_id = 'US:AAPL:equity'
          AND date >= '2020-01-01'
        ORDER BY date
    """).fetchdf()
    con.close()

    print("Example 5: AAPL corporate actions")
    print(f"  Splits:")
    for _, r in splits.iterrows():
        print(f"    {r['date']}: {r['split_ratio']}")
    print(f"  Dividends (2020+): {len(divs)} payments")
    if len(divs) > 0:
        print(f"    Average: ${divs['value'].mean():.4f} per share")
    print()


def example_6_multi_exchange():
    """Compare data coverage across exchanges."""
    con = duckdb.connect(DB, read_only=True)
    df = con.execute("""
        SELECT a.exchange_code,
               e.exchange_name,
               e.region,
               COUNT(DISTINCT p.asset_id) AS instruments,
               COUNT(*) AS observations,
               MIN(p.date) AS first_date,
               MAX(p.date) AS last_date
        FROM bronze_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        JOIN dim_exchange e ON a.exchange_code = e.exchange_code
        GROUP BY 1, 2, 3
        ORDER BY observations DESC
        LIMIT 10
    """).fetchdf()
    con.close()

    print("Example 6: Top 10 exchanges by data volume")
    for _, r in df.iterrows():
        print(f"  {r['exchange_code']:>6s} ({r['region']:15s}): "
              f"{r['instruments']:>7,} instruments, "
              f"{r['observations']:>12,} observations")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("  HyperDB — Quick Start Examples")
    print("=" * 60)
    print()

    example_1_basic_query()
    example_2_monthly_panel()
    example_3_cross_sectional()
    example_4_factor_model()
    example_5_corporate_actions()
    example_6_multi_exchange()

    print("All examples completed successfully.")
    print("See README.md for full documentation.")
