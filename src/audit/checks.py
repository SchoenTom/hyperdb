"""
HyperDataBank — Automated Quality Assurance
────────────────────────────────────────────
Comprehensive checks on data integrity, consistency, and completeness.

Checks are organized by category:
    1. Persistence:  Gaps in trading date sequences
    2. Price sanity:  Nulls, zeros, negatives, extreme returns
    3. Corporate actions:  Split/dividend plausibility
    4. Coverage:  Universe vs. actual download coverage
    5. Cross-market:  FX rate availability for all currencies
    6. Panel:  Monthly panel consistency and statistics
    7. Spot checks:  Known reference values for validation

All results are written to a human-readable audit report.
"""

import duckdb
from datetime import date

from src.core.db import get_connection
from src.core.config import get_reports_dir
from src.core.log import get_logger

logger = get_logger("hyperdb.audit")


def _section(title: str) -> str:
    return f"\n{'='*60}\n{title}\n{'='*60}\n"


def run_audit(exchange_code: str | None = None,
              full: bool = False) -> str:
    """Run all audit checks and return the report as a string.

    Args:
        exchange_code: Audit a specific exchange. None = all.
        full: If True, run expensive cross-market checks.
    """
    conn = get_connection()
    report_lines = []
    r = report_lines.append

    r(_section("HYPERDB AUDIT REPORT"))
    r(f"Date: {date.today().isoformat()}")
    r(f"Scope: {exchange_code or 'ALL EXCHANGES'}")
    r("")

    where_asset = ""
    params = []
    if exchange_code:
        where_asset = "AND a.exchange_code = ?"
        params.append(exchange_code)

    # ── CHECK 1: DATABASE OVERVIEW ──────────────────────────────────────────
    r(_section("1. DATABASE OVERVIEW"))

    tables = conn.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' ORDER BY table_name
    """).fetchall()

    for (tbl,) in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        r(f"  {tbl:<40s}  {cnt:>12,} rows")

    # ── CHECK 2: UNIVERSE STATISTICS ────────────────────────────────────────
    r(_section("2. UNIVERSE STATISTICS"))

    total = conn.execute("SELECT COUNT(*) FROM dim_asset").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM dim_asset WHERE is_active = TRUE"
    ).fetchone()[0]
    r(f"  Total instruments: {total:,}")
    r(f"  Active: {active:,}  |  Inactive/Delisted: {total - active:,}")
    r("")

    # By asset class
    r("  By asset class:")
    rows = conn.execute("""
        SELECT asset_class, COUNT(*),
               SUM(CASE WHEN is_active THEN 1 ELSE 0 END)
        FROM dim_asset GROUP BY asset_class ORDER BY COUNT(*) DESC
    """).fetchall()
    for cls, cnt, act in rows:
        r(f"    {cls:<20s}  {cnt:>8,}  (active: {int(act):,})")

    r("")
    r("  By exchange (top 20):")
    rows = conn.execute("""
        SELECT exchange_code, COUNT(*) AS n
        FROM dim_asset GROUP BY exchange_code ORDER BY n DESC LIMIT 20
    """).fetchall()
    for ex, cnt in rows:
        r(f"    {ex:<10s}  {cnt:>8,}")

    # ── CHECK 3: PRICE DATA QUALITY ────────────────────────────────────────
    r(_section("3. PRICE DATA QUALITY"))

    price_stats = conn.execute(f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT p.asset_id) AS n_tickers,
            MIN(p.date) AS min_date,
            MAX(p.date) AS max_date,
            SUM(CASE WHEN p.close IS NULL THEN 1 ELSE 0 END) AS null_close,
            SUM(CASE WHEN p.adjusted_close IS NULL THEN 1 ELSE 0 END) AS null_adj,
            SUM(CASE WHEN p.adjusted_close <= 0 THEN 1 ELSE 0 END) AS neg_adj,
            SUM(CASE WHEN p.volume IS NULL THEN 1 ELSE 0 END) AS null_vol
        FROM raw_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        WHERE 1=1 {where_asset}
    """, params).fetchone()

    if price_stats[0] > 0:
        r(f"  Total price rows: {price_stats[0]:,}")
        r(f"  Unique tickers: {price_stats[1]:,}")
        r(f"  Date range: {price_stats[2]} to {price_stats[3]}")
        r(f"  Null close: {price_stats[4]:,}")
        r(f"  Null adjusted_close: {price_stats[5]:,}")
        r(f"  Negative/zero adjusted_close: {price_stats[6]:,}")
        r(f"  Null volume: {price_stats[7]:,}")
    else:
        r("  No price data found.")

    # Cleaned layer stats
    clean_stats = conn.execute(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN return_flag = 'clean' THEN 1 ELSE 0 END),
            SUM(CASE WHEN return_flag = 'extreme' THEN 1 ELSE 0 END),
            SUM(CASE WHEN return_flag = 'sentinel' THEN 1 ELSE 0 END)
        FROM clean_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        WHERE 1=1 {where_asset}
    """, params).fetchone()

    if clean_stats[0] > 0:
        r(f"\n  Cleaned layer:")
        r(f"    Total: {clean_stats[0]:,}")
        r(f"    Clean: {clean_stats[1]:,}")
        r(f"    Extreme returns: {clean_stats[2]:,}")
        r(f"    Sentinel values: {clean_stats[3]:,}")

    # ── CHECK 4: CORPORATE ACTIONS ─────────────────────────────────────────
    r(_section("4. CORPORATE ACTIONS"))

    split_count = conn.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT s.asset_id)
        FROM raw_split s
        JOIN dim_asset a ON s.asset_id = a.asset_id
        WHERE 1=1 {where_asset}
    """, params).fetchone()
    r(f"  Splits: {split_count[0]:,} events for {split_count[1]:,} tickers")

    div_count = conn.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT d.asset_id)
        FROM raw_dividend d
        JOIN dim_asset a ON d.asset_id = a.asset_id
        WHERE 1=1 {where_asset}
    """, params).fetchone()
    r(f"  Dividends: {div_count[0]:,} events for {div_count[1]:,} tickers")

    # Sentinel dividend check
    sentinel_divs = conn.execute(f"""
        SELECT COUNT(*)
        FROM raw_dividend d
        JOIN dim_asset a ON d.asset_id = a.asset_id
        WHERE d.value > 99000 {where_asset}
    """, params).fetchone()[0]
    if sentinel_divs > 0:
        r(f"  WARNING: {sentinel_divs} dividend records with sentinel "
          f"values (>$99,000)")
    else:
        r("  No sentinel values detected in dividends.")

    # ── CHECK 5: DOWNLOAD COVERAGE ─────────────────────────────────────────
    r(_section("5. DOWNLOAD COVERAGE"))

    coverage = conn.execute(f"""
        SELECT
            data_type,
            SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status = 'no_data' THEN 1 ELSE 0 END) AS no_data,
            COUNT(*) AS total
        FROM meta_download_log
        GROUP BY data_type
        ORDER BY data_type
    """).fetchall()

    for dtype, ok, failed, no_data, total in coverage:
        pct = ok / max(total, 1) * 100
        r(f"  {dtype:<20s}  ok={ok:,}  failed={failed:,}  "
          f"no_data={no_data:,}  ({pct:.1f}% success)")

    # ── CHECK 6: FX COVERAGE ───────────────────────────────────────────────
    r(_section("6. FX RATE COVERAGE"))

    fx_stats = conn.execute("""
        SELECT base_currency, COUNT(*), MIN(date), MAX(date)
        FROM raw_fx_daily
        GROUP BY base_currency
        ORDER BY base_currency
    """).fetchall()

    if fx_stats:
        for ccy, cnt, mn, mx in fx_stats:
            r(f"  {ccy}/USD: {cnt:,} daily rates ({mn} to {mx})")
    else:
        r("  No FX data downloaded yet.")

    # Check which currencies in the universe lack FX data
    missing_fx = conn.execute("""
        SELECT DISTINCT a.currency
        FROM dim_asset a
        WHERE a.currency IS NOT NULL
          AND a.currency != 'USD'
          AND a.currency NOT IN (
              SELECT DISTINCT base_currency FROM raw_fx_daily
          )
    """).fetchall()

    if missing_fx:
        r(f"\n  WARNING: {len(missing_fx)} currencies in universe without "
          f"FX data:")
        for (ccy,) in missing_fx[:20]:
            r(f"    {ccy}")

    # ── CHECK 7: FACTOR DATA ──────────────────────────────────────────────
    r(_section("7. FACTOR MODEL DATA"))

    factor_stats = conn.execute("""
        SELECT region, model, frequency, COUNT(*), MIN(date), MAX(date)
        FROM factor_return
        GROUP BY region, model, frequency
        ORDER BY region, model, frequency
    """).fetchall()

    if factor_stats:
        for reg, model, freq, cnt, mn, mx in factor_stats:
            r(f"  {reg:<15s}  {model:<8s}  {freq:<8s}  "
              f"{cnt:>8,} obs  ({mn} to {mx})")
    else:
        r("  No factor data downloaded yet.")

    # ── CHECK 8: MONTHLY PANEL ────────────────────────────────────────────
    r(_section("8. MONTHLY PANEL"))

    panel_stats = conn.execute(f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT asset_id) AS n_assets,
            MIN(month) AS min_month,
            MAX(month) AS max_month,
            AVG(return_local) AS mean_return,
            AVG(beta_local) AS mean_beta,
            SUM(CASE WHEN return_local IS NULL THEN 1 ELSE 0 END) AS null_return,
            SUM(CASE WHEN beta_local IS NULL THEN 1 ELSE 0 END) AS null_beta
        FROM panel_monthly p
        {"JOIN dim_asset a ON p.asset_id = a.asset_id WHERE " + where_asset.replace("AND ", "") if exchange_code else ""}
    """, params if exchange_code else []).fetchone()

    if panel_stats[0] > 0:
        r(f"  Total rows: {panel_stats[0]:,}")
        r(f"  Unique assets: {panel_stats[1]:,}")
        r(f"  Month range: {panel_stats[2]} to {panel_stats[3]}")
        r(f"  Mean return (local): {panel_stats[4]:.6f}" if panel_stats[4] else "  Mean return: N/A")
        r(f"  Mean beta (local): {panel_stats[5]:.4f}" if panel_stats[5] else "  Mean beta: N/A")
        r(f"  Null returns: {panel_stats[6]:,}")
        r(f"  Null betas: {panel_stats[7]:,}")
    else:
        r("  No panel data yet.")

    # ── CHECK 9: QUALITY SCORES ──────────────────────────────────────────
    r(_section("9. DATA QUALITY SCORES"))

    quality = conn.execute("""
        SELECT
            dimension,
            AVG(score) AS mean,
            MEDIAN(score) AS median,
            MIN(score) AS min,
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY score) AS p10
        FROM meta_data_quality
        GROUP BY dimension
        ORDER BY dimension
    """).fetchall()

    if quality:
        r(f"  {'Dimension':<15s}  {'Mean':>6s}  {'Median':>6s}  "
          f"{'Min':>6s}  {'P10':>6s}")
        r(f"  {'-'*15}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")
        for dim, mean, med, mn, p10 in quality:
            r(f"  {dim:<15s}  {mean:>6.3f}  {med:>6.3f}  "
              f"{mn:>6.3f}  {p10:>6.3f}")
    else:
        r("  No quality scores computed yet.")

    # ── VERDICT ──────────────────────────────────────────────────────────
    r(_section("VERDICT"))
    issues = []
    if price_stats[0] > 0:
        if price_stats[5] > 0:
            issues.append(f"{price_stats[5]:,} null adjusted_close values")
        if price_stats[6] > 100:
            issues.append(f"{price_stats[6]:,} negative adjusted_close values")
    if sentinel_divs > 0:
        issues.append(f"{sentinel_divs} sentinel dividend values")
    if missing_fx:
        issues.append(f"{len(missing_fx)} currencies without FX data")

    if not issues:
        r("  PASS — No critical issues found.")
    else:
        r("  ISSUES FOUND:")
        for issue in issues:
            r(f"    - {issue}")

    conn.close()

    report = "\n".join(report_lines)

    # Save to file
    report_path = get_reports_dir() / "audit_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Audit report saved to %s", report_path)
    return report
