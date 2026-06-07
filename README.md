# HyperDB — A Global Financial Database for Quantitative Research

A comprehensive, multi-asset-class financial database covering 324,969 instruments
across 42 exchanges worldwide (1985--2025). Built on EODHD end-of-day data and stored
in DuckDB for fast analytical queries. Designed for reproducible academic research
on asset pricing, factor models, and quantitative trading strategies.

University of Konstanz, 2026.

## Research Context

Empirical finance research requires high-quality, survivorship-bias-free price data
with broad cross-sectional coverage. Commercial databases (CRSP, Compustat, Refinitiv)
are expensive and often limited to specific regions. HyperDB provides a transparent,
open-architecture alternative built from EODHD's global equity data, supplemented
with academic factor returns from Kenneth French, the q-factor model, and FRED
macroeconomic indicators.

The database follows a medallion architecture (Bronze / Silver / Gold) that separates
raw ingestion from cleaning and analysis-ready transformations. All fields from the
data provider are stored without modification in the Bronze layer. Cleaning rules
in the Silver layer are minimal and transparent --- only physically impossible values
are removed. No opinionated filters (penny stocks, volume floors, exchange exclusions)
are applied at the database level. Researchers apply their own filters downstream.

## Data Sources

| Source | Data | Coverage | Access |
|--------|------|----------|--------|
| EODHD API | End-of-day OHLCV prices | 42 exchanges, 1985--2025 | API key required |
| EODHD API | Stock splits, dividends | All equities with price data | API key required |
| EODHD API | FX daily rates | 51 currency pairs | API key required |
| Kenneth French Data Library | FF3, FF5, Carhart factors | US, Europe, Japan, Asia-Pac, Global, Emerging | Public |
| Global-Q | q-factor model | US | Public |
| FRED | TED spread | US | Public |

## Database Summary

| Metric | Value |
|--------|-------|
| Instruments (dim_asset) | 324,969 |
| Exchanges with price data | 42 (of 77 in registry, across 35+ countries) |
| Daily price observations (Bronze) | 414,628,206 |
| Daily price observations (Silver) | 413,838,945 |
| Monthly panel observations (Gold) | 21,559,321 |
| Stock splits | 108,741 |
| Dividend payments | 2,010,176 |
| FX daily rates | 359,289 (51 pairs) |
| Factor return observations | 688,842 |
| Data quality scores | 1,035,660 |
| Date range | 1985-01-01 to 2025-12-31 |
| Survivorship bias | Controlled (active + delisted instruments) |

## Requirements

- Python 3.11+
- DuckDB 1.0+

```bash
pip install -r requirements.txt
```

Required packages: `duckdb`, `pandas`, `numpy`, `pyyaml`, `tqdm`, `requests`,
`scipy`, `matplotlib`.

## Schema Architecture

HyperDB uses a medallion architecture with five table categories:

```
Bronze    Raw data from EODHD, stored without modification.
          Every field the API returns is preserved.

Silver    Cleaned and validated. Physically impossible values removed.
          Daily and log returns computed. Quality flags assigned.
          NO opinionated filtering.

Gold      Analysis-ready derived quantities. Monthly panel with
          returns in three currencies (local, USD, EUR), rolling
          beta estimates, liquidity measures, and quality flags.

Dim       Dimension tables. Instrument master (dim_asset), exchange
          registry (dim_exchange), trading calendar (dim_calendar).

Meta      Pipeline metadata. Download logs (meta_download_log),
          data quality scores (meta_data_quality).
```

### Table Reference

| Layer | Table | Rows | Primary Key | Description |
|-------|-------|------|-------------|-------------|
| Dim | dim_asset | 324,969 | asset_id | Instrument master (ticker, exchange, ISIN, class, active/delisted) |
| Dim | dim_exchange | 77 | exchange_code | Exchange metadata (country, region, currency, timezone, tier) |
| Dim | dim_calendar | 535,591 | (date, exchange_code) | Trading calendar inferred from price data |
| Bronze | bronze_price_daily | 414,628,206 | (asset_id, date) | Daily OHLCV prices |
| Bronze | bronze_split | 108,741 | (asset_id, date) | Stock split ratios |
| Bronze | bronze_dividend | 2,010,176 | (asset_id, date, value) | Dividend payments with metadata |
| Bronze | bronze_fx_daily | 359,289 | (date, base, quote) | Daily FX rates (51 pairs) |
| Silver | silver_price_daily | 413,838,945 | (asset_id, date) | Cleaned prices with returns and flags |
| Silver | silver_fx_daily | 354,551 | (date, base, quote) | Cleaned FX with log returns |
| Gold | gold_monthly_panel | 21,559,321 | (asset_id, month) | Monthly returns, betas, liquidity |
| Gold | gold_factor_return | 688,842 | (date, freq, region, model, factor) | FF3, FF5, Carhart, q-factor |
| Meta | meta_download_log | 472,188 | -- | Per-asset download tracking |
| Meta | meta_data_quality | 1,035,660 | (asset_id, dimension) | Quality scores (0--1) |

### Asset Identification

Each instrument is identified by a composite key:

```
asset_id = EXCHANGE:TICKER:CLASS
```

Examples: `US:AAPL:equity`, `XETRA:SAP:equity`, `HK:0005:equity`, `LSE:HSBA:equity`.

## Pipeline

### Quick Start (Read-Only)

To query the pre-built database, no pipeline execution is needed:

```python
import duckdb

con = duckdb.connect('hyperdb.duckdb', read_only=True)

# Monthly returns for US equities, 2020 onwards
df = con.execute("""
    SELECT asset_id, month, return_local, beta_local
    FROM gold_monthly_panel
    WHERE exchange_code = 'US' AND month >= '2020-01-01'
""").fetchdf()
```

### Full Rebuild (Requires EODHD API Key)

To rebuild the database from scratch:

```bash
# Step 0: Set API key in config/settings.yaml

# Step 1: Build instrument universe
python cli.py universe

# Step 2: Download all data (~3-5 days, 500K API calls)
python cli.py download smart

# Step 3: Build trading calendar
python cli.py calendar

# Step 4: Clean prices (Bronze -> Silver)
python cli.py transform clean

# Step 5: Build monthly panel (Silver -> Gold)
python cli.py transform panel

# Step 6: Compute quality scores
python cli.py transform quality

# Step 7: Validate
python cli.py audit --full
```

## Data Quality

### Cleaning Rules (Bronze to Silver)

| Rule | Action | Rows Affected |
|------|--------|---------------|
| C1 | Remove adjusted_close <= 0 | 673,525 |
| C2 | Remove close <= 0 (where adjusted_close > 0) | 115,736 |
| C3 | Remove NULL dates | 0 |
| C4 | Flag \|daily return\| > 200% as `extreme` | Flagged, not removed |
| C5 | Flag close > 99,000 as `sentinel` | 2,610,972 flagged |
| C6 | Compute daily and log returns | All rows |

Total rows removed: 789,261 (0.19% of Bronze = 673,525 + 115,736).
All removals are physically impossible values (zero or negative prices).
Sentinel values (EODHD's 999,999.99 placeholder) are flagged but retained
for transparency.

### Validation Results

| Check | Result |
|-------|--------|
| Duplicate price records | 0 |
| Duplicate split records | 0 |
| Duplicate FX records | 0 |
| Orphaned prices (no dim_asset entry) | 0 |
| Orphaned splits (no dim_asset entry) | 0 |
| Orphaned dividends (no dim_asset entry) | 0 |
| AAPL close 2024-12-31 | $250.42 (verified) |
| MSFT date range | 1986-03-13 to 2025-12-31 |
| EUR/USD rate 2024-12-31 | 1.0406 (verified) |

### Download Success Rates

| Data Type | OK | Failed | Success Rate |
|-----------|-----|--------|--------------|
| Prices | 172,664 | 12 | 99.99% |
| Splits | 150,045 | 9 | 99.99% |
| Dividends | 143,046 | 2,026 | 98.60% |

## Exchange Coverage

### Tier 1 --- Core Developed Markets

US (NYSE/NASDAQ/AMEX), LSE (London), XETRA (Deutsche Borse),
PA (Euronext Paris), AS (Euronext Amsterdam), SW (SIX Swiss).

### Tier 2 --- Important Developed Markets

TO (Toronto), AU (ASX), HK (Hong Kong), KO/KQ (Korea),
TW/TWO (Taiwan), ST (Stockholm), CO (Copenhagen), OL (Oslo).

### Tier 3 --- Emerging and Regional Markets

SHG/SHE (China), BK (Thailand), F (Frankfurt),
V (TSX Venture), WAR (Warsaw), MC (Madrid), and 20+ others.

## Factor Models

| Model | Factors | Regions | Frequency |
|-------|---------|---------|-----------|
| Fama-French 3-Factor | Mkt-RF, SMB, HML | US, Europe, Japan, Asia-Pac, Global, Emerging | Daily + Monthly |
| Fama-French 5-Factor | + RMW, CMA | US, Europe, Japan, Asia-Pac, Global, Emerging | Daily + Monthly |
| Carhart 4-Factor | + MOM | US | Daily + Monthly |

Source: Kenneth French Data Library, Global-Q.

## Project Structure

```
HyperDB/
    hyperdb.duckdb              Database file (34 GB)
    README.md                   This file
    VALIDATION_PROTOCOL.md      Quality validation procedures
    cli.py                      Command-line interface
    requirements.txt            Python dependencies
    config/
        settings.yaml           Configuration (API key removed)
        exchanges.yaml          Exchange registry (77 exchanges)
        asset_classes.yaml      Asset class taxonomy
    src/
        core/
            db.py               Schema definition, connection management
            config.py           Configuration loader
            log.py              Logging setup
        ingest/
            client.py           EODHD API wrapper (rate-limited, retries)
            universe.py         Instrument universe builder
            prices.py           Daily price downloader (backfill + bulk)
            corporate_actions.py Splits and dividends
            fx.py               FX rate downloader
            factors.py          Academic factor models (FF, q-factor)
            fundamentals.py     Company profiles and financial statements
            macro.py            Macroeconomic indicators
            calendar.py         Trading calendar builder
        transform/
            clean.py            Bronze -> Silver (returns, quality flags)
            returns.py          Monthly return computation (multi-currency)
            risk.py             Beta estimation (Frazzini & Pedersen 2014)
            panel.py            Gold monthly panel builder
            quality.py          Data quality scoring (5 dimensions)
        audit/
            checks.py           Automated quality checks
    generate_figures.py         Data visualization script (8 figures)
    reports/
        figures/                Publication-ready PDF figures
```

## Known Limitations

1. **Sentinel values and extreme returns.** EODHD returns 999,999.99 for some
   securities on certain dates. These are flagged as `sentinel` in
   silver_price_daily but not removed. The gold_monthly_panel includes returns
   derived from these values, which can be extremely large. **Researchers must
   filter returns for analysis**, for example:
   ```sql
   WHERE return_local BETWEEN -1.0 AND 2.0
   ```
   Alternatively, filter the Silver layer on `return_flag = 'clean'` before
   computing custom aggregates.

2. **Beta estimates for US and Frankfurt.** Due to memory constraints (8 GB RAM),
   rolling beta estimates for the US and Frankfurt exchanges are not computed in
   the Gold panel. Monthly returns are available; betas can be computed on a
   machine with 16+ GB RAM using `python cli.py transform panel --exchange US`.

3. **Exchange blacklist.** Twenty exchanges were excluded from download to
   conserve disk space and API calls (see `exchange_blacklist` in settings.yaml).
   These include frontier markets and redundant regional German exchanges.

4. **No intraday data.** Only daily OHLCV. No tick data or bid-ask spreads.

5. **Fundamentals not populated.** The schema supports financial statements,
   earnings, insider transactions, and analyst ratings, but these tables are
   currently empty. They can be populated with `python cli.py download fundamentals`.

6. **FX gaps.** Some emerging-market currencies have sparse FX data before 2000.
   USD/EUR returns for those assets may contain gaps.

## Reproducibility

The entire database can be rebuilt from scratch using the provided code and an
EODHD API key (All-World plan, 100K calls/day). Total rebuild time: approximately
5 days. All pipeline steps are idempotent and resumable.

Factor data from Kenneth French and Global-Q is downloaded automatically and
cached locally. No manual data acquisition is required beyond the EODHD API key.

## Note on AI Usage

Development of the data pipeline and quality assurance procedures was supported
by Claude (Anthropic). All code, queries, and validation logic were reviewed and
verified by the author. The database contents are sourced exclusively from EODHD,
Kenneth French Data Library, Global-Q, and FRED.

## References

- Fama, E. F. and French, K. R. (1993). Common risk factors in the returns on
  stocks and bonds. *Journal of Financial Economics*, 33(1):3--56.
- Fama, E. F. and French, K. R. (2015). A five-factor asset pricing model.
  *Journal of Financial Economics*, 116(1):1--22.
- Frazzini, A. and Pedersen, L. H. (2014). Betting against beta. *Journal of
  Financial Economics*, 111(1):1--25.
- Hou, K., Xue, C., and Zhang, L. (2015). Digesting anomalies: An investment
  approach. *Review of Financial Studies*, 28(3):650--705.
