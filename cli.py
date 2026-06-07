#!/usr/bin/env python3
"""
HyperDataBank — Unified Command-Line Interface
────────────────────────────────────────────────
2026

A worldwide, multi-asset-class financial database built on EODHD data.

Usage:
    python cli.py universe [--exchange CODE] [--tier N] [--all]
    python cli.py download prices [--exchange CODE] [--backfill] [--bulk]
    python cli.py download splits [--exchange CODE]
    python cli.py download dividends [--exchange CODE]
    python cli.py download fundamentals [--exchange CODE]
    python cli.py download fx
    python cli.py download factors
    python cli.py download macro [--country CODE]
    python cli.py download all [--exchange CODE] [--tier N]
    python cli.py download smart
    python cli.py download indices
    python cli.py download bonds
    python cli.py transform clean [--exchange CODE]
    python cli.py transform panel [--exchange CODE]
    python cli.py transform quality [--exchange CODE]
    python cli.py calendar [--exchange CODE]
    python cli.py audit [--exchange CODE]
    python cli.py status
    python cli.py migrate-legacy

Design principles:
    1. Store EVERY field EODHD returns — no data is dropped.
    2. No opinionated filtering — filtering belongs in research scripts.
    3. Every step is logged and traceable.
    4. Reproducibility is guaranteed.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def cmd_universe(args):
    """Build the instrument universe from EODHD."""
    from src.ingest.universe import build_universe, get_universe_summary
    from src.core.db import get_connection

    exchanges = [args.exchange] if args.exchange else None
    tier = args.tier if hasattr(args, "tier") and args.tier else None

    build_universe(exchanges=exchanges, tier=tier)

    # Print summary
    print(get_universe_summary())


def cmd_download_prices(args):
    """Download price data."""
    from src.ingest.prices import backfill_prices, bulk_update_prices

    if args.bulk:
        if args.exchange:
            bulk_update_prices(args.exchange, target_date=args.date)
        else:
            from src.ingest.prices import bulk_update_all_exchanges
            bulk_update_all_exchanges(target_date=args.date)
    else:
        # Support comma-separated asset classes
        asset_classes = None
        if hasattr(args, "asset_classes") and args.asset_classes:
            asset_classes = [c.strip() for c in args.asset_classes.split(",")]

        backfill_prices(
            exchange_code=args.exchange,
            asset_class=args.asset_class,
            asset_classes=asset_classes,
            resume=not args.no_resume,
        )


def cmd_download_splits(args):
    """Download split data."""
    from src.ingest.corporate_actions import download_splits
    download_splits(exchange_code=args.exchange, resume=not args.no_resume)


def cmd_download_dividends(args):
    """Download dividend data."""
    from src.ingest.corporate_actions import download_dividends
    download_dividends(exchange_code=args.exchange, resume=not args.no_resume)


def cmd_download_fundamentals(args):
    """Download fundamental data."""
    from src.ingest.fundamentals import download_fundamentals
    download_fundamentals(
        exchange_code=args.exchange,
        asset_class=args.asset_class,
        resume=not args.no_resume,
    )


def cmd_download_fx(args):
    """Download FX rates."""
    from src.ingest.fx import download_fx_rates
    download_fx_rates()


def cmd_download_factors(args):
    """Download factor model data."""
    from src.ingest.factors import download_all_factors
    download_all_factors()


def cmd_download_macro(args):
    """Download macroeconomic indicators."""
    from src.ingest.macro import download_macro
    countries = [args.country] if args.country else None
    download_macro(countries=countries)


def cmd_download_all(args):
    """Download everything for an exchange or tier."""
    from src.ingest.universe import build_universe
    from src.ingest.prices import backfill_prices
    from src.ingest.corporate_actions import download_splits, download_dividends
    from src.ingest.fx import download_fx_rates
    from src.ingest.factors import download_all_factors
    from src.ingest.macro import download_macro

    exchange = args.exchange
    tier = args.tier

    print("=" * 60)
    print("HYPERDB — FULL DOWNLOAD PIPELINE")
    print("=" * 60)

    # Step 1: Universe
    print("\n[1/7] Building universe...")
    exchanges = [exchange] if exchange else None
    build_universe(exchanges=exchanges, tier=tier)

    # Step 2: Prices
    print("\n[2/7] Downloading prices...")
    backfill_prices(exchange_code=exchange, resume=True)

    # Step 3: Splits
    print("\n[3/7] Downloading splits...")
    download_splits(exchange_code=exchange, resume=True)

    # Step 4: Dividends
    print("\n[4/7] Downloading dividends...")
    download_dividends(exchange_code=exchange, resume=True)

    # Step 5: FX rates
    print("\n[5/7] Downloading FX rates...")
    download_fx_rates()

    # Step 6: Factors
    print("\n[6/7] Downloading factor data...")
    download_all_factors()

    # Step 7: Macro
    print("\n[7/7] Downloading macro indicators...")
    download_macro()

    print("\n" + "=" * 60)
    print("DOWNLOAD PIPELINE COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  python cli.py transform clean")
    print("  python cli.py transform panel --exchange US")
    print("  python cli.py audit")


def cmd_download_smart(args):
    """Run the smart download pipeline — build the perfect database.

    Processes data in priority order:
        1. Universe build (all exchanges including INDX, GBOND)
        2. Regional equity+ETF prices (US -> Europe -> Asia -> ...)
        3. Index prices (INDX)
        4. Government bond prices (GBOND)
        5. Corporate actions (splits, dividends)
        6. FX rates
        7. Factor models
        8. Macro indicators

    Every step is resumable. Safe to Ctrl-C and restart.
    """
    from src.core.config import (load_regions, load_supplementary,
                                  load_exchange_blacklist)
    from src.ingest.universe import build_universe
    from src.ingest.prices import (backfill_prices, download_indices,
                                    download_bonds)
    from src.ingest.corporate_actions import download_splits, download_dividends
    from src.ingest.fx import download_fx_rates
    from src.ingest.factors import download_all_factors
    from src.ingest.macro import download_macro

    regions = load_regions()
    supplementary = load_supplementary()
    blacklist = load_exchange_blacklist()

    n_regions = len(regions)
    n_supp = len(supplementary)
    total_steps = 1 + n_regions + n_supp + 5
    step = 0

    print("=" * 70)
    print("HYPERDB — SMART DOWNLOAD PIPELINE")
    print("=" * 70)
    print(f"  Regions:        {n_regions} ({', '.join(r['name'] for r in regions)})")
    print(f"  Supplementary:  {n_supp} ({', '.join(supplementary.keys())})")
    print(f"  Blacklisted:    {blacklist}")
    print(f"  Total steps:    {total_steps}")
    print("=" * 70)

    # Step 1: Universe
    step += 1
    print(f"\n[{step}/{total_steps}] Building universe (all exchanges)...")
    build_universe()

    # Steps 2..N: Regional equity+ETF prices
    for region_cfg in regions:
        step += 1
        region_name = region_cfg["name"]
        region_exchanges = region_cfg["exchanges"]
        asset_classes = region_cfg.get("asset_classes", ["equity", "etf"])

        print(f"\n[{step}/{total_steps}] Downloading prices: {region_name} "
              f"({len(region_exchanges)} exchanges, "
              f"classes: {asset_classes})")

        for ex_code in region_exchanges:
            if ex_code in blacklist:
                print(f"  Skipping {ex_code} (blacklisted)")
                continue
            print(f"  --- Exchange: {ex_code} ---")
            backfill_prices(
                exchange_code=ex_code,
                asset_classes=asset_classes,
                resume=True,
            )

    # Supplementary: Indices
    if "indices" in supplementary:
        step += 1
        print(f"\n[{step}/{total_steps}] Downloading index prices (INDX)...")
        download_indices(resume=True)

    # Supplementary: Bonds
    if "bonds" in supplementary:
        step += 1
        print(f"\n[{step}/{total_steps}] Downloading government bond prices (GBOND)...")
        download_bonds(resume=True)

    # Splits
    step += 1
    print(f"\n[{step}/{total_steps}] Downloading splits...")
    download_splits(resume=True)

    # Dividends
    step += 1
    print(f"\n[{step}/{total_steps}] Downloading dividends...")
    download_dividends(resume=True)

    # FX
    step += 1
    print(f"\n[{step}/{total_steps}] Downloading FX rates...")
    download_fx_rates()

    # Factors
    step += 1
    print(f"\n[{step}/{total_steps}] Downloading factor models...")
    download_all_factors()

    # Macro
    step += 1
    print(f"\n[{step}/{total_steps}] Downloading macro indicators...")
    download_macro()

    print("\n" + "=" * 70)
    print("SMART DOWNLOAD PIPELINE COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("  python cli.py transform clean")
    print("  python cli.py transform panel")
    print("  python cli.py audit")


def cmd_download_indices(args):
    """Download index price data."""
    from src.ingest.prices import download_indices
    download_indices(resume=not args.no_resume)


def cmd_download_bonds(args):
    """Download government bond price data."""
    from src.ingest.prices import download_bonds
    download_bonds(resume=not args.no_resume)


def cmd_transform_clean(args):
    """Clean prices (Raw -> Cleaned)."""
    from src.transform.clean import clean_prices, clean_fx
    clean_prices(exchange_code=args.exchange)
    clean_fx()


def cmd_transform_panel(args):
    """Build monthly panel (Cleaned -> Panel)."""
    from src.transform.panel import build_panel, build_panel_all

    if args.exchange:
        build_panel(args.exchange)
    else:
        build_panel_all()


def cmd_transform_quality(args):
    """Compute data quality scores."""
    from src.transform.quality import compute_quality_scores
    compute_quality_scores(exchange_code=args.exchange)


def cmd_calendar(args):
    """Build trading calendars from price data."""
    from src.ingest.calendar import build_calendar
    build_calendar(exchange_code=args.exchange)


def cmd_audit(args):
    """Run quality assurance checks."""
    from src.audit.checks import run_audit
    report = run_audit(exchange_code=args.exchange, full=args.full)
    print(report)


def cmd_purge_ballast(args):
    """Delete price data for blacklisted exchanges to reclaim disk space.

    Removes rows from raw_price_daily and meta_download_log
    for exchanges in the blacklist. Then runs CHECKPOINT to
    allow DuckDB to reclaim disk space on next open.
    """
    from src.core.config import load_exchange_blacklist
    from src.core.db import get_connection, init_schema
    from src.core.log import get_logger

    logger = get_logger("hyperdb.purge")
    init_schema()
    conn = get_connection()
    blacklist = load_exchange_blacklist()

    # Allow targeting specific exchanges or use full blacklist
    targets = [args.exchange] if args.exchange else blacklist
    targets = [t for t in targets if t in blacklist] if args.exchange else targets

    if not targets:
        print("No exchanges to purge.")
        conn.close()
        return

    print(f"Purging price data for {len(targets)} exchanges: {targets}")
    print("This will DELETE rows from raw_price_daily and meta_download_log.")

    if not args.yes:
        confirm = input("Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            conn.close()
            return

    total_deleted = 0
    for ex_code in targets:
        # Count before delete
        count = conn.execute("""
            SELECT COUNT(*) FROM raw_price_daily
            WHERE asset_id IN (
                SELECT asset_id FROM dim_asset WHERE exchange_code = ?
            )
        """, [ex_code]).fetchone()[0]

        if count == 0:
            print(f"  {ex_code}: no price data — skipping")
            continue

        print(f"  {ex_code}: deleting {count:,} price rows...", end=" ", flush=True)

        conn.execute("""
            DELETE FROM raw_price_daily
            WHERE asset_id IN (
                SELECT asset_id FROM dim_asset WHERE exchange_code = ?
            )
        """, [ex_code])

        conn.execute("""
            DELETE FROM meta_download_log
            WHERE exchange_code = ?
        """, [ex_code])

        total_deleted += count
        print("done")

    print(f"\nTotal deleted: {total_deleted:,} rows")
    print("Running CHECKPOINT to prepare space reclamation...")
    conn.execute("CHECKPOINT")
    conn.close()

    print(f"Purge complete. Restart any DB connection to reclaim disk space.")
    print(f"Estimated space saved: ~{total_deleted * 54 / 1_073_741_824:.1f} GB")


def cmd_status(args):
    """Show database status overview."""
    from src.core.db import get_connection, get_table_stats
    from src.ingest.universe import get_universe_summary

    conn = get_connection()

    print("=" * 60)
    print("HYPERDB STATUS")
    print("=" * 60)

    # Table sizes
    print("\nTable row counts:")
    stats = get_table_stats(conn)
    for table, count in sorted(stats.items()):
        print(f"  {table:<40s}  {count:>12,}")

    # Universe summary
    print()
    print(get_universe_summary(conn))

    conn.close()


def cmd_migrate_legacy(args):
    """Migrate data from the legacy CSV pipeline into DuckDB.

    Reads the existing CSV files (daily_prices.csv, universe_combined.csv,
    metadata_splits.csv, metadata_dividends.csv) and imports them into
    the new DuckDB schema.
    """
    import pandas as pd
    from src.core.db import get_connection, init_schema
    from src.core.config import eodhd_type_to_class, PROJECT_ROOT
    from src.core.log import get_logger
    from datetime import date as dt_date

    logger = get_logger("hyperdb.migrate")

    init_schema()
    conn = get_connection()

    legacy_dir = PROJECT_ROOT / "data"

    # ── Migrate Universe ──
    universe_file = legacy_dir / "universe_combined.csv"
    if universe_file.exists():
        logger.info("Migrating universe from %s...", universe_file)
        df = pd.read_csv(universe_file)

        # Ensure exchange dimension exists
        conn.execute("""
            INSERT OR IGNORE INTO dim_exchange
                (exchange_code, exchange_name, country_iso2, default_currency,
                 eodhd_code, tier)
            VALUES ('US', 'United States', 'US', 'USD', 'US', 1)
        """)

        count = 0
        for _, row in df.iterrows():
            ticker = row.get("Code", "")
            eodhd_type = row.get("Type", "Common Stock")
            asset_class = eodhd_type_to_class(eodhd_type)
            asset_id = f"US:{ticker}:{asset_class}"
            is_active = not bool(row.get("is_delisted", False))

            conn.execute("""
                INSERT OR IGNORE INTO dim_asset
                    (asset_id, ticker, exchange_code, isin, name,
                     asset_class, eodhd_type, currency,
                     country_domicile, is_active, ticker_api,
                     first_seen, last_seen)
                VALUES (?, ?, 'US', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                asset_id, ticker, row.get("Isin"),
                row.get("Name", ""), asset_class, eodhd_type,
                row.get("Currency", "USD"),
                row.get("home_category"),
                is_active,
                row.get("ticker_api", f"{ticker}.US"),
                dt_date.today().isoformat(),
                dt_date.today().isoformat(),
            ])
            count += 1

        logger.info("  Migrated %d assets from universe.", count)
    else:
        logger.warning("  No universe_combined.csv found — skipping.")

    # ── Migrate Daily Prices ──
    prices_file = legacy_dir / "daily_prices.csv"
    if prices_file.exists():
        logger.info("Migrating prices from %s (chunked)...", prices_file)

        total = 0
        for chunk in pd.read_csv(prices_file, chunksize=500_000):
            rows = []
            for _, row in chunk.iterrows():
                ticker = row.get("ticker", "")
                asset_id = f"US:{ticker}:equity"
                rows.append((
                    asset_id,
                    row.get("date"),
                    None,  # open (not in legacy)
                    None,  # high (not in legacy)
                    None,  # low (not in legacy)
                    row.get("close"),
                    row.get("adjusted_close"),
                    int(row["volume"]) if pd.notna(row.get("volume")) else None,
                ))

            conn.executemany("""
                INSERT OR IGNORE INTO raw_price_daily
                    (asset_id, date, open, high, low, close,
                     adjusted_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            total += len(rows)
            logger.info("  Migrated %d price rows so far...", total)

        logger.info("  Total price rows migrated: %d", total)
    else:
        logger.warning("  No daily_prices.csv found — skipping.")

    # ── Migrate Splits ──
    splits_file = legacy_dir / "metadata_splits.csv"
    if splits_file.exists():
        logger.info("Migrating splits from %s...", splits_file)
        df = pd.read_csv(splits_file)
        rows = []
        for _, row in df.iterrows():
            ticker = row.get("ticker", "")
            asset_id = f"US:{ticker}:equity"
            rows.append((asset_id, row.get("date"), row.get("split_ratio")))

        conn.executemany("""
            INSERT OR IGNORE INTO raw_split
                (asset_id, date, split_ratio)
            VALUES (?, ?, ?)
        """, rows)
        logger.info("  Migrated %d split records.", len(rows))

    # ── Migrate Dividends ──
    divs_file = legacy_dir / "metadata_dividends.csv"
    if divs_file.exists():
        logger.info("Migrating dividends from %s...", divs_file)
        df = pd.read_csv(divs_file)
        rows = []
        for _, row in df.iterrows():
            ticker = row.get("ticker", "")
            asset_id = f"US:{ticker}:equity"
            rows.append((
                asset_id, row.get("date"), row.get("value"),
                None,  # unadjusted_value (not in legacy)
                row.get("currency"),
                row.get("declaration_date") if pd.notna(row.get("declaration_date")) else None,
                row.get("record_date") if pd.notna(row.get("record_date")) else None,
                row.get("payment_date") if pd.notna(row.get("payment_date")) else None,
                None,  # period (not in legacy)
            ))

        conn.executemany("""
            INSERT OR IGNORE INTO raw_dividend
                (asset_id, date, value, unadjusted_value, currency,
                 declaration_date, record_date, payment_date, period)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        logger.info("  Migrated %d dividend records.", len(rows))

    conn.close()
    logger.info("Legacy migration complete.")
    print("\nLegacy data migrated successfully!")
    print("Next: python cli.py transform clean --exchange US")


def main():
    parser = argparse.ArgumentParser(
        prog="hyperdb",
        description="HyperDataBank — Worldwide Financial Data Platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ── universe ──
    p_uni = subparsers.add_parser("universe", help="Build instrument universe")
    p_uni.add_argument("--exchange", "-e", help="Specific exchange code")
    p_uni.add_argument("--tier", "-t", type=int, choices=[1, 2, 3, 4],
                       help="Max exchange tier (1=core, 4=all)")
    p_uni.add_argument("--all", action="store_true",
                       help="All exchanges")
    p_uni.set_defaults(func=cmd_universe)

    # ── download ──
    p_dl = subparsers.add_parser("download", help="Download data from EODHD")
    dl_sub = p_dl.add_subparsers(dest="dl_command")

    # download prices
    p_prices = dl_sub.add_parser("prices", help="Download price data")
    p_prices.add_argument("--exchange", "-e", help="Exchange code")
    p_prices.add_argument("--asset-class", "-a", help="Asset class filter")
    p_prices.add_argument("--bulk", action="store_true",
                          help="Use bulk API (daily update mode)")
    p_prices.add_argument("--date", help="Target date for bulk (YYYY-MM-DD)")
    p_prices.add_argument("--no-resume", action="store_true",
                          help="Disable resume, re-download everything")
    p_prices.set_defaults(func=cmd_download_prices)

    # download splits
    p_splits = dl_sub.add_parser("splits", help="Download splits")
    p_splits.add_argument("--exchange", "-e", help="Exchange code")
    p_splits.add_argument("--no-resume", action="store_true")
    p_splits.set_defaults(func=cmd_download_splits)

    # download dividends
    p_divs = dl_sub.add_parser("dividends", help="Download dividends")
    p_divs.add_argument("--exchange", "-e", help="Exchange code")
    p_divs.add_argument("--no-resume", action="store_true")
    p_divs.set_defaults(func=cmd_download_dividends)

    # download fundamentals
    p_fund = dl_sub.add_parser("fundamentals", help="Download fundamentals")
    p_fund.add_argument("--exchange", "-e", help="Exchange code")
    p_fund.add_argument("--asset-class", "-a", help="Asset class filter")
    p_fund.add_argument("--no-resume", action="store_true")
    p_fund.set_defaults(func=cmd_download_fundamentals)

    # download fx
    p_fx = dl_sub.add_parser("fx", help="Download FX rates")
    p_fx.set_defaults(func=cmd_download_fx)

    # download factors
    p_factors = dl_sub.add_parser("factors", help="Download factor models")
    p_factors.set_defaults(func=cmd_download_factors)

    # download macro
    p_macro = dl_sub.add_parser("macro", help="Download macro indicators")
    p_macro.add_argument("--country", "-c", help="ISO alpha-2 country code")
    p_macro.set_defaults(func=cmd_download_macro)

    # download all
    p_all = dl_sub.add_parser("all", help="Full download pipeline")
    p_all.add_argument("--exchange", "-e", help="Exchange code")
    p_all.add_argument("--tier", "-t", type=int, choices=[1, 2, 3, 4])
    p_all.set_defaults(func=cmd_download_all)

    # download smart
    p_smart = dl_sub.add_parser("smart",
                                 help="Smart pipeline — build the perfect database")
    p_smart.set_defaults(func=cmd_download_smart)

    # download indices
    p_indices = dl_sub.add_parser("indices",
                                   help="Download index prices (INDX)")
    p_indices.add_argument("--no-resume", action="store_true")
    p_indices.set_defaults(func=cmd_download_indices)

    # download bonds
    p_bonds = dl_sub.add_parser("bonds",
                                 help="Download government bond prices (GBOND)")
    p_bonds.add_argument("--no-resume", action="store_true")
    p_bonds.set_defaults(func=cmd_download_bonds)

    # ── transform ──
    p_tr = subparsers.add_parser("transform", help="Transform data")
    tr_sub = p_tr.add_subparsers(dest="tr_command")

    p_clean = tr_sub.add_parser("clean", help="Clean prices (Raw→Cleaned)")
    p_clean.add_argument("--exchange", "-e", help="Exchange code")
    p_clean.set_defaults(func=cmd_transform_clean)

    p_panel = tr_sub.add_parser("panel", help="Build monthly panel")
    p_panel.add_argument("--exchange", "-e", help="Exchange code")
    p_panel.set_defaults(func=cmd_transform_panel)

    p_qual = tr_sub.add_parser("quality", help="Compute quality scores")
    p_qual.add_argument("--exchange", "-e", help="Exchange code")
    p_qual.set_defaults(func=cmd_transform_quality)

    # ── calendar ──
    p_cal = subparsers.add_parser("calendar", help="Build trading calendars")
    p_cal.add_argument("--exchange", "-e", help="Exchange code")
    p_cal.set_defaults(func=cmd_calendar)

    # ── audit ──
    p_audit = subparsers.add_parser("audit", help="Run quality checks")
    p_audit.add_argument("--exchange", "-e", help="Exchange code")
    p_audit.add_argument("--full", action="store_true",
                         help="Run expensive cross-market checks")
    p_audit.set_defaults(func=cmd_audit)

    # ── status ──
    p_status = subparsers.add_parser("status", help="Database status overview")
    p_status.set_defaults(func=cmd_status)

    # ── purge-ballast ──
    p_purge = subparsers.add_parser("purge-ballast",
                                     help="Delete price data for blacklisted exchanges")
    p_purge.add_argument("--exchange", "-e",
                         help="Specific exchange to purge (must be in blacklist)")
    p_purge.add_argument("--yes", "-y", action="store_true",
                         help="Skip confirmation prompt")
    p_purge.set_defaults(func=cmd_purge_ballast)

    # ── migrate-legacy ──
    p_migrate = subparsers.add_parser("migrate-legacy",
                                       help="Import legacy CSV data")
    p_migrate.set_defaults(func=cmd_migrate_legacy)

    # Parse and execute
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.parse_args([args.command, "--help"])


if __name__ == "__main__":
    main()
