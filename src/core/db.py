"""
HyperDataBank — Database Layer (DuckDB)
────────────────────────────────────────
Central schema definition and connection management.

Architecture:
    raw_*   Raw data from EODHD, stored as-is.  Full reproducibility.
    clean_*   Cleaned, validated, cross-referenced.  Minimal opinionated transforms.
    panel_*     Derived quantities (returns, betas, panels).  Analysis-ready.
    dim_*      Dimension / lookup tables.
    meta_*     Pipeline metadata (download logs, quality scores).

Design principles:
    1. Store EVERY field EODHD returns — no field is dropped.
    2. No opinionated filtering at the database level.
    3. Every row is traceable to its source and download timestamp.
    4. Schema changes are versioned via meta_schema_version.
"""

import duckdb
from pathlib import Path

from src.core.config import get_db_path
from src.core.log import get_logger

logger = get_logger("hyperdb.db")

SCHEMA_VERSION = 1


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a connection to the HyperDataBank DuckDB file."""
    db_path = get_db_path()
    conn = duckdb.connect(str(db_path), read_only=read_only,
                          config={'threads': '1', 'memory_limit': '6GB'})
    if not read_only:
        conn.execute("SET preserve_insertion_order = false")
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection | None = None) -> None:
    """Create all tables if they do not exist.

    Safe to call repeatedly — uses CREATE TABLE IF NOT EXISTS.
    """
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    logger.info("Initializing database schema (version %d)...", SCHEMA_VERSION)

    # ══════════════════════════════════════════════════════════════════════════
    # SCHEMA VERSION TRACKING
    # ══════════════════════════════════════════════════════════════════════════
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_schema_version (
            version         INTEGER PRIMARY KEY,
            applied_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)
    # Insert version if not present
    existing = conn.execute(
        "SELECT version FROM meta_schema_version WHERE version = ?",
        [SCHEMA_VERSION],
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO meta_schema_version (version) VALUES (?)",
            [SCHEMA_VERSION],
        )

    # ══════════════════════════════════════════════════════════════════════════
    # DIMENSION TABLES
    # ══════════════════════════════════════════════════════════════════════════

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_exchange (
            exchange_code       VARCHAR PRIMARY KEY,
            exchange_name       VARCHAR,
            country_iso2        VARCHAR,
            country_name        VARCHAR,
            region              VARCHAR,
            default_currency    VARCHAR,
            timezone            VARCHAR,
            mic_code            VARCHAR,
            eodhd_code          VARCHAR,
            tier                INTEGER,
            operating_hours     VARCHAR,
            notes               VARCHAR,
            updated_at          TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # dim_asset: Master table for EVERY instrument across ALL exchanges.
    # This is the central reference. Every fact table joins to asset_id.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_asset (
            asset_id            VARCHAR PRIMARY KEY,
            ticker              VARCHAR NOT NULL,
            exchange_code       VARCHAR NOT NULL,
            isin                VARCHAR,
            name                VARCHAR,
            asset_class         VARCHAR,
            asset_subclass      VARCHAR,
            eodhd_type          VARCHAR,
            currency            VARCHAR,
            country_domicile    VARCHAR,
            is_active           BOOLEAN,
            ticker_api          VARCHAR,
            first_seen          DATE,
            last_seen           DATE,
            updated_at          TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # dim_asset_profile: Extended company/instrument profile from Fundamentals API.
    # Separated from dim_asset because it is only available for a subset
    # of instruments and changes infrequently.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_asset_profile (
            asset_id                VARCHAR PRIMARY KEY,
            -- Company basics
            description             VARCHAR,
            sector                  VARCHAR,
            industry                VARCHAR,
            gics_sector             VARCHAR,
            gics_group              VARCHAR,
            gics_industry           VARCHAR,
            gics_sub_industry       VARCHAR,
            fiscal_year_end         VARCHAR,
            ipo_date                DATE,
            international_domestic  VARCHAR,
            -- Contact / address
            address                 VARCHAR,
            phone                   VARCHAR,
            web_url                 VARCHAR,
            logo_url                VARCHAR,
            full_time_employees     INTEGER,
            -- Identifiers
            lei                     VARCHAR,
            cusip                   VARCHAR,
            primary_ticker          VARCHAR,
            home_category           VARCHAR,
            -- Latest snapshot metrics (updated periodically)
            market_cap              DOUBLE,
            market_cap_mln_usd      DOUBLE,
            ebitda                  DOUBLE,
            pe_ratio                DOUBLE,
            peg_ratio               DOUBLE,
            book_value              DOUBLE,
            dividend_share          DOUBLE,
            dividend_yield          DOUBLE,
            eps                     DOUBLE,
            eps_estimate_current_yr DOUBLE,
            eps_estimate_next_yr    DOUBLE,
            profit_margin           DOUBLE,
            operating_margin_ttm    DOUBLE,
            roa_ttm                 DOUBLE,
            roe_ttm                 DOUBLE,
            revenue_ttm             DOUBLE,
            revenue_per_share_ttm   DOUBLE,
            gross_profit_ttm        DOUBLE,
            diluted_eps_ttm         DOUBLE,
            -- Valuation
            trailing_pe             DOUBLE,
            forward_pe              DOUBLE,
            price_sales_ttm         DOUBLE,
            price_book_mrq          DOUBLE,
            enterprise_value        DOUBLE,
            ev_revenue              DOUBLE,
            ev_ebitda               DOUBLE,
            -- Shares statistics
            shares_outstanding      BIGINT,
            shares_float            BIGINT,
            percent_insiders        DOUBLE,
            percent_institutions    DOUBLE,
            shares_short            BIGINT,
            shares_short_prior_mo   BIGINT,
            short_ratio             DOUBLE,
            short_pct_outstanding   DOUBLE,
            short_pct_float         DOUBLE,
            -- Technicals snapshot
            beta_eodhd              DOUBLE,
            week_52_high            DOUBLE,
            week_52_low             DOUBLE,
            day_50_ma               DOUBLE,
            day_200_ma              DOUBLE,
            -- ETF specific
            etf_company_name        VARCHAR,
            etf_company_url         VARCHAR,
            etf_asset_class         VARCHAR,
            etf_net_expense_ratio   DOUBLE,
            etf_total_assets        DOUBLE,
            etf_yield               DOUBLE,
            etf_inception_date      DATE,
            -- Analyst ratings snapshot
            analyst_rating          VARCHAR,
            analyst_target_price    DOUBLE,
            analyst_strong_buy      INTEGER,
            analyst_buy             INTEGER,
            analyst_hold            INTEGER,
            analyst_sell            INTEGER,
            analyst_strong_sell     INTEGER,
            -- ESG
            esg_score               DOUBLE,
            esg_environment         DOUBLE,
            esg_social              DOUBLE,
            esg_governance          DOUBLE,
            --
            updated_at              TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_calendar (
            date                DATE,
            exchange_code       VARCHAR,
            is_trading_day      BOOLEAN,
            PRIMARY KEY (date, exchange_code)
        )
    """)

    # ══════════════════════════════════════════════════════════════════════════
    # RAW TABLES — Raw data from EODHD, stored as-is
    # ══════════════════════════════════════════════════════════════════════════

    # Daily OHLCV prices — ALL fields from EODHD /eod/ endpoint.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_price_daily (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            open                DOUBLE,
            high                DOUBLE,
            low                 DOUBLE,
            close               DOUBLE,
            adjusted_close      DOUBLE,
            volume              BIGINT,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_split (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            split_ratio         VARCHAR,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_dividend (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            value               DOUBLE,
            unadjusted_value    DOUBLE,
            currency            VARCHAR,
            declaration_date    DATE,
            record_date         DATE,
            payment_date        DATE,
            period              VARCHAR,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, date, value)
        )
    """)

    # Financial statements in EAV (Entity-Attribute-Value) format.
    # This stores EVERY line item from Balance Sheet, Income Statement,
    # and Cash Flow — quarterly and annual — in a single table.
    # Economists can pivot/filter as needed for their research.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_fundamental (
            asset_id            VARCHAR NOT NULL,
            report_date         DATE NOT NULL,
            period_type         VARCHAR NOT NULL,
            statement_type      VARCHAR NOT NULL,
            filing_date         DATE,
            currency_symbol     VARCHAR,
            line_item           VARCHAR NOT NULL,
            value               DOUBLE,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, report_date, period_type,
                         statement_type, line_item)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_earnings (
            asset_id            VARCHAR NOT NULL,
            report_date         DATE NOT NULL,
            eps_actual          DOUBLE,
            eps_estimate        DOUBLE,
            eps_difference      DOUBLE,
            surprise_pct        DOUBLE,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, report_date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_shares_outstanding (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            shares_mln          DOUBLE,
            shares_raw          BIGINT,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_insider_transaction (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            owner_name          VARCHAR,
            transaction_type    VARCHAR,
            shares              BIGINT,
            value               DOUBLE,
            owner_title         VARCHAR,
            security_name       VARCHAR,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_etf_holding (
            asset_id            VARCHAR NOT NULL,
            holding_code        VARCHAR,
            holding_name        VARCHAR,
            holding_isin        VARCHAR,
            weight_pct          DOUBLE,
            sector              VARCHAR,
            country             VARCHAR,
            asset_class         VARCHAR,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_fx_daily (
            date                DATE NOT NULL,
            base_currency       VARCHAR NOT NULL,
            quote_currency      VARCHAR NOT NULL,
            open                DOUBLE,
            high                DOUBLE,
            low                 DOUBLE,
            close               DOUBLE,
            adjusted_close      DOUBLE,
            volume              BIGINT,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (date, base_currency, quote_currency)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_macro_indicator (
            country_iso2        VARCHAR NOT NULL,
            indicator           VARCHAR NOT NULL,
            date                DATE NOT NULL,
            period              VARCHAR,
            value               DOUBLE,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (country_iso2, indicator, date)
        )
    """)

    # Bond-specific fields from EODHD fundamentals endpoint.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_bond_detail (
            asset_id            VARCHAR PRIMARY KEY,
            issuer_name         VARCHAR,
            issuer_country      VARCHAR,
            coupon_rate         DOUBLE,
            coupon_frequency    VARCHAR,
            coupon_type         VARCHAR,
            maturity_date       DATE,
            issue_date          DATE,
            face_value          DOUBLE,
            currency            VARCHAR,
            bond_type           VARCHAR,
            credit_rating       VARCHAR,
            rating_agency       VARCHAR,
            is_callable         BOOLEAN,
            is_convertible      BOOLEAN,
            yield_to_maturity   DOUBLE,
            duration_modified   DOUBLE,
            duration_macaulay   DOUBLE,
            convexity           DOUBLE,
            downloaded_at       TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # ══════════════════════════════════════════════════════════════════════════
    # CLEANED TABLES — Cleaned, validated data
    # ══════════════════════════════════════════════════════════════════════════
    # Cleaning rules (Raw → Cleaned):
    #   1. Remove rows with null/negative adjusted_close
    #   2. Remove rows with clearly corrupt data (sentinel values)
    #   3. Forward-fill minor gaps (≤3 trading days) in prices
    #   4. Flag but DO NOT remove extreme returns — they are informational
    #   5. Cross-reference with corporate actions for consistency
    #
    # What we do NOT do in Cleaned:
    #   - No penny stock filtering
    #   - No volume filtering
    #   - No exchange filtering
    #   - No seasoning requirements
    #   These belong DOWNSTREAM in research scripts.

    conn.execute("""
        CREATE TABLE IF NOT EXISTS clean_price_daily (
            asset_id            VARCHAR NOT NULL,
            date                DATE NOT NULL,
            open                DOUBLE,
            high                DOUBLE,
            low                 DOUBLE,
            close               DOUBLE,
            adjusted_close      DOUBLE,
            volume              BIGINT,
            daily_return        DOUBLE,
            log_return          DOUBLE,
            return_flag         VARCHAR,
            PRIMARY KEY (asset_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS clean_fx_daily (
            date                DATE NOT NULL,
            base_currency       VARCHAR NOT NULL,
            quote_currency      VARCHAR NOT NULL,
            rate                DOUBLE NOT NULL,
            log_return          DOUBLE,
            PRIMARY KEY (date, base_currency, quote_currency)
        )
    """)

    # ══════════════════════════════════════════════════════════════════════════
    # PANEL TABLES — Analysis-ready derived quantities
    # ══════════════════════════════════════════════════════════════════════════

    conn.execute("""
        CREATE TABLE IF NOT EXISTS panel_monthly (
            asset_id                VARCHAR NOT NULL,
            month                   DATE NOT NULL,
            exchange_code           VARCHAR,
            asset_class             VARCHAR,
            currency                VARCHAR,
            -- Returns in local currency
            return_local            DOUBLE,
            excess_return_local     DOUBLE,
            -- Returns in USD
            return_usd              DOUBLE,
            excess_return_usd       DOUBLE,
            -- Returns in EUR
            return_eur              DOUBLE,
            excess_return_eur       DOUBLE,
            -- Risk metrics (vs local market index)
            beta_local              DOUBLE,
            beta_local_ts           DOUBLE,
            sigma_i                 DOUBLE,
            sigma_m                 DOUBLE,
            rho_im                  DOUBLE,
            -- Risk metrics (vs global market)
            beta_global             DOUBLE,
            -- Liquidity
            median_price_local      DOUBLE,
            mean_volume             DOUBLE,
            trading_days            INTEGER,
            turnover_ratio          DOUBLE,
            -- Sample size
            n_daily                 INTEGER,
            n_3day                  INTEGER,
            -- Quality flags (informational, not filters)
            data_quality_flag       VARCHAR,
            PRIMARY KEY (asset_id, month)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_return (
            date                DATE NOT NULL,
            frequency           VARCHAR NOT NULL,
            region              VARCHAR NOT NULL,
            model               VARCHAR NOT NULL,
            factor_name         VARCHAR NOT NULL,
            value               DOUBLE,
            PRIMARY KEY (date, frequency, region, model, factor_name)
        )
    """)

    # ══════════════════════════════════════════════════════════════════════════
    # META TABLES — Pipeline tracking and quality metadata
    # ══════════════════════════════════════════════════════════════════════════

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_download_log (
            asset_id            VARCHAR,
            exchange_code       VARCHAR,
            data_type           VARCHAR,
            status              VARCHAR,
            record_count        INTEGER,
            error_message       VARCHAR,
            started_at          TIMESTAMP,
            completed_at        TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta_data_quality (
            asset_id            VARCHAR NOT NULL,
            dimension           VARCHAR NOT NULL,
            score               DOUBLE,
            detail              VARCHAR,
            computed_at         TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, dimension)
        )
    """)

    # Index creation skipped — 414M rows exceed 8GB RAM for index builds.
    # DuckDB columnar storage handles analytical queries efficiently without indexes.
    # Indexes can be added later on a machine with more RAM if needed.

    logger.info("Schema initialized successfully (%d tables).", 21)

    if close_after:
        conn.close()


def get_table_stats(conn: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Return row counts for all tables in the database."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    tables = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """).fetchall()

    stats = {}
    for (table_name,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        stats[table_name] = count

    if close_after:
        conn.close()

    return stats
