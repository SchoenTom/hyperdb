# HyperDB — Quality Validation Protocol
### Universität Konstanz, 2026
### Version 1.0

---

## 1. Purpose

This document defines a systematic, reproducible protocol for validating the integrity, completeness, and correctness of the HyperDB financial database. It serves as:
- **Internal QA**: Ensuring the database meets academic research standards before use
- **External Assurance**: Providing fellow researchers with verifiable proof of data quality
- **Audit Trail**: Documenting what was checked, when, and with what result

---

## 2. Validation Dimensions

### 2.1 Structural Integrity
Ensures the database schema is correct and all constraints are satisfied.

| Check | SQL Query | Expected |
|-------|-----------|----------|
| Schema version | `SELECT * FROM meta_schema_version` | Version 1 |
| All 21 tables exist | `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main'` | 21 |
| No duplicate prices | `SELECT COUNT(*) FROM (SELECT asset_id, date, COUNT(*) n FROM bronze_price_daily GROUP BY 1,2 HAVING n>1)` | 0 |
| No duplicate splits | `SELECT COUNT(*) FROM (SELECT asset_id, date, COUNT(*) n FROM bronze_split GROUP BY 1,2 HAVING n>1)` | 0 |
| No duplicate FX | `SELECT COUNT(*) FROM (SELECT date, base_currency, quote_currency, COUNT(*) n FROM bronze_fx_daily GROUP BY 1,2,3 HAVING n>1)` | 0 |

### 2.2 Referential Integrity
Ensures all fact tables reference valid dimension entries.

| Check | SQL Query | Expected |
|-------|-----------|----------|
| Prices -> dim_asset | `SELECT COUNT(DISTINCT asset_id) FROM bronze_price_daily WHERE asset_id NOT IN (SELECT asset_id FROM dim_asset)` | 0 |
| Splits -> dim_asset | `SELECT COUNT(DISTINCT asset_id) FROM bronze_split WHERE asset_id NOT IN (SELECT asset_id FROM dim_asset)` | 0 |
| Dividends -> dim_asset | `SELECT COUNT(DISTINCT asset_id) FROM bronze_dividend WHERE asset_id NOT IN (SELECT asset_id FROM dim_asset)` | 0 |
| Assets -> dim_exchange | `SELECT COUNT(*) FROM dim_asset WHERE exchange_code NOT IN (SELECT exchange_code FROM dim_exchange)` | 0 |

### 2.3 Completeness
Ensures all expected data is present.

```sql
-- Coverage matrix: assets with prices vs splits vs dividends
SELECT 
    'has_prices' as check_type,
    COUNT(DISTINCT asset_id) as count
FROM meta_download_log WHERE data_type='prices' AND status='ok'
UNION ALL
SELECT 'has_splits', COUNT(DISTINCT asset_id)
FROM meta_download_log WHERE data_type='splits' AND status='ok'
UNION ALL
SELECT 'has_dividends', COUNT(DISTINCT asset_id)
FROM meta_download_log WHERE data_type='dividends' AND status='ok';

-- Exchange coverage: prices per exchange
SELECT a.exchange_code, 
       COUNT(DISTINCT p.asset_id) as assets_with_prices,
       COUNT(DISTINCT a2.asset_id) as total_assets,
       ROUND(COUNT(DISTINCT p.asset_id) * 100.0 / COUNT(DISTINCT a2.asset_id), 1) as pct
FROM dim_asset a2
LEFT JOIN bronze_price_daily p ON a2.asset_id = p.asset_id
LEFT JOIN dim_asset a ON p.asset_id = a.asset_id
GROUP BY a.exchange_code
ORDER BY total_assets DESC;

-- FX coverage: all currencies in dim_asset should have FX rates
SELECT DISTINCT a.currency
FROM dim_asset a
WHERE a.currency NOT IN (
    SELECT base_currency FROM bronze_fx_daily
    UNION SELECT quote_currency FROM bronze_fx_daily
)
AND a.currency IS NOT NULL
AND a.currency != 'USD';
```

### 2.4 Temporal Consistency
Ensures time series are continuous and dates are valid.

```sql
-- Date range per exchange (should align with market history)
SELECT a.exchange_code,
       MIN(p.date) as first_date, MAX(p.date) as last_date,
       COUNT(DISTINCT p.date) as trading_days,
       DATEDIFF('day', MIN(p.date), MAX(p.date)) as calendar_days
FROM bronze_price_daily p
JOIN dim_asset a ON p.asset_id = a.asset_id
GROUP BY 1
ORDER BY first_date;

-- Check for future dates (should be 0)
SELECT COUNT(*) FROM bronze_price_daily WHERE date > '2025-12-31';

-- Check for dates before 1985 (should be 0 given config)
SELECT COUNT(*) FROM bronze_price_daily WHERE date < '1985-01-01';
```

### 2.5 Value Plausibility
Ensures financial values are within expected ranges.

```sql
-- Price sanity checks
SELECT 
    'negative_adj_close' as check_type,
    COUNT(*) as count
FROM bronze_price_daily WHERE adjusted_close < 0
UNION ALL
SELECT 'zero_adj_close', COUNT(*)
FROM bronze_price_daily WHERE adjusted_close = 0
UNION ALL
SELECT 'sentinel_values', COUNT(*)
FROM bronze_price_daily WHERE adjusted_close > 99000
UNION ALL
SELECT 'null_volume', COUNT(*)
FROM bronze_price_daily WHERE volume IS NULL
UNION ALL
SELECT 'negative_volume', COUNT(*)
FROM bronze_price_daily WHERE volume < 0;

-- FX rate sanity
SELECT base_currency, quote_currency,
       MIN(close) as min_rate, MAX(close) as max_rate,
       AVG(close) as avg_rate
FROM bronze_fx_daily
GROUP BY 1, 2
HAVING MIN(close) <= 0 OR MAX(close) > 100000;

-- Split ratio format check
SELECT split_ratio, COUNT(*) 
FROM bronze_split 
WHERE split_ratio NOT LIKE '%:%' 
  AND split_ratio NOT LIKE '%/%'
  AND split_ratio IS NOT NULL
GROUP BY 1 
LIMIT 20;
```

---

## 3. External Validation (Cross-Reference)

### 3.1 Known Reference Values
Compare database values against publicly verifiable sources.

| Asset | Date | Field | Expected Value | Source |
|-------|------|-------|----------------|--------|
| US:AAPL:equity | 2024-12-31 | close | ~250.42 | Yahoo Finance |
| US:MSFT:equity | 2024-12-31 | close | ~421.00 | Yahoo Finance |
| US:AAPL:equity | 2020-08-31 | split_ratio | 4:1 | Apple IR |
| US:TSLA:equity | 2022-08-25 | split_ratio | 3:1 | Tesla IR |
| EUR/USD FX | 2024-12-31 | close | ~1.035 | ECB |

```sql
-- Verify reference values
SELECT asset_id, date, close, adjusted_close 
FROM bronze_price_daily 
WHERE asset_id = 'US:AAPL:equity' AND date = '2024-12-31';

SELECT asset_id, date, split_ratio 
FROM bronze_split 
WHERE asset_id = 'US:AAPL:equity' AND date >= '2020-01-01';

SELECT date, close 
FROM bronze_fx_daily 
WHERE base_currency = 'EUR' AND quote_currency = 'USD' 
AND date = '2024-12-31';
```

### 3.2 Factor Model Cross-Check
Compare stored factor returns against Kenneth French Data Library.

```sql
-- FF3 US monthly: Mkt-RF for January 2024
SELECT * FROM gold_factor_return 
WHERE model = 'FF3' AND region = 'US' AND frequency = 'monthly'
AND factor_name = 'Mkt-RF' AND date >= '2024-01-01' AND date < '2024-02-01';
-- Cross-check: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
```

### 3.3 Survivorship Bias Check
Confirm that delisted securities are included.

```sql
-- Count active vs inactive assets
SELECT is_active, COUNT(*) FROM dim_asset GROUP BY 1;

-- Verify known delistings exist (e.g., Lehman Brothers delisted 2008)
SELECT * FROM dim_asset WHERE name LIKE '%Lehman%';

-- Check that delisted assets have price history ending before today
SELECT a.asset_id, a.name, a.is_active, MAX(p.date) as last_price
FROM dim_asset a
JOIN bronze_price_daily p ON a.asset_id = p.asset_id
WHERE a.is_active = false
GROUP BY 1, 2, 3
ORDER BY last_price DESC
LIMIT 10;
```

---

## 4. Statistical Validation

### 4.1 Return Distribution
Monthly returns should be approximately normal with known characteristics.

```sql
-- If gold_monthly_panel is populated:
SELECT 
    exchange_code,
    COUNT(*) as n,
    AVG(return_local) as mean_return,
    STDDEV(return_local) as std_return,
    PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY return_local) as p1,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY return_local) as median,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY return_local) as p99
FROM gold_monthly_panel
WHERE return_local IS NOT NULL
GROUP BY exchange_code
ORDER BY n DESC
LIMIT 10;
-- Expected: mean ~0.5-1.5% monthly, std ~5-10%, median close to mean
```

### 4.2 Beta Distribution
Betas should center around 1.0 with reasonable dispersion.

```sql
SELECT 
    exchange_code,
    COUNT(*) as n,
    AVG(beta_local) as mean_beta,
    STDDEV(beta_local) as std_beta,
    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY beta_local) as p10,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY beta_local) as median,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY beta_local) as p90
FROM gold_monthly_panel
WHERE beta_local IS NOT NULL
GROUP BY exchange_code
ORDER BY n DESC
LIMIT 10;
-- Expected: mean ~1.0, std ~0.3-0.6, median ~0.9-1.1
```

### 4.3 Corporate Action Consistency
Verify that split-adjusted prices are continuous.

```sql
-- For assets with known splits: check that adjusted_close is smooth
-- around the split date (no jumps proportional to split ratio)
SELECT p.date, p.close, p.adjusted_close, s.split_ratio
FROM bronze_price_daily p
JOIN bronze_split s ON p.asset_id = s.asset_id AND p.date = s.date
WHERE p.asset_id = 'US:AAPL:equity'
ORDER BY p.date;
```

---

## 5. Automated Audit

Run the built-in audit suite:
```bash
cd /Volumes/HyperDB
python cli.py audit --full > reports/audit_report.txt 2>&1
```

This checks:
- Database overview (row counts per table)
- Universe statistics (active/delisted, by class, by exchange)
- Price data quality (null/zero/negative counts, date ranges)
- Corporate actions (split/dividend counts, history length)
- FX coverage (available pairs, missing currencies)
- Macro data (indicator coverage by country)
- Fundamentals availability
- Monthly panel statistics (return/beta distributions)
- Spot checks (known reference values)
- Ingest metadata (success rate, failed assets)

---

## 6. Validation Checklist

### Pre-Release Checklist
- [ ] All 21 tables exist with correct schema
- [ ] bronze_price_daily: >400M rows, 0 duplicates
- [ ] bronze_split: >100K rows, all asset_ids valid
- [ ] bronze_dividend: >2M rows, all asset_ids valid
- [ ] bronze_fx_daily: >350K rows, 50+ currency pairs
- [ ] gold_factor_return: >680K rows, FF3+FF5+Carhart models
- [ ] dim_asset: >320K instruments, active+delisted
- [ ] Referential integrity: 0 orphaned records in all fact tables
- [ ] Date range: 1985-01-01 to 2025-12-31
- [ ] No future dates, no dates before 1985
- [ ] AAPL spot check: close ~$250 on 2024-12-31
- [ ] EUR/USD spot check: ~1.035 on 2024-12-31
- [ ] API key NOT present in settings.yaml
- [ ] WAL file absent (clean checkpoint)
- [ ] No __pycache__, .DS_Store, or temp files
- [ ] silver_price_daily populated (if transforms ran)
- [ ] Audit report generated and saved
- [ ] README.md present with usage instructions

### For External Distribution
- [ ] Database opens successfully on fresh Python + DuckDB install
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `python cli.py status` runs without error
- [ ] `python cli.py audit` runs without error
- [ ] Sample query returns expected results:
  ```python
  import duckdb
  con = duckdb.connect('hyperdb.duckdb', read_only=True)
  df = con.execute("SELECT * FROM bronze_price_daily WHERE asset_id='US:AAPL:equity' AND date='2024-12-31'").fetchdf()
  assert len(df) == 1
  assert abs(df['close'].iloc[0] - 250.42) < 1.0
  ```

---

## 7. Known Limitations

Document these for transparency with fellow researchers:

1. **Sentinel values**: EODHD returns 999999.9999 for some securities on certain dates. These are flagged as 'sentinel' in silver_price_daily but NOT removed — researchers should filter them.

2. **Negative adjusted_close**: 54,764 rows have negative adjusted_close. These are removed during Bronze->Silver cleaning but remain in bronze for traceability.

3. **Exchange blacklist**: 20 exchanges were excluded from download to save disk space (see settings.yaml). These include emerging/frontier markets.

4. **Failed downloads**: 2,026 dividend downloads and 9 split downloads failed (HTTP errors). These represent <1.5% of instruments.

5. **FX gaps**: Some emerging market currencies may have sparse FX data pre-2000. Returns in USD/EUR for those assets may have gaps.

6. **Beta estimation**: Rolling betas require 5 years of data. First 5 years of any asset's history will have unreliable or missing beta estimates.

7. **No intraday data**: Only daily OHLCV. No tick data, no bid-ask spreads.

8. **Fundamentals not downloaded**: Financial statements, earnings, insider transactions are in the schema but not yet populated. Can be added later with `python cli.py download fundamentals`.

---

## 8. Reproducibility

To rebuild this database from scratch:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set API key in config/settings.yaml
# api.token: "YOUR_EODHD_API_KEY"

# 3. Build universe
python cli.py universe

# 4. Download all data (takes ~3-5 days depending on API plan)
python cli.py download smart

# 5. Transform
python cli.py calendar
python cli.py transform clean
python cli.py transform panel
python cli.py transform quality

# 6. Audit
python cli.py audit --full > reports/audit_report.txt
```

Total API calls required: ~500,000 (fits within EODHD All-World plan's 100K/day over 5 days)

---

*Protocol created: April 6, 2026*
*Database version: HyperDB v1.0*
*Author: Tom Schoen, Universitat Konstanz*
