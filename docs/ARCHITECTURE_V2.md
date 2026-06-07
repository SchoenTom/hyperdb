# HyperDB v2 — Architecture & Build Specification (Publication-Grade)

> Status: design spec for the rebuild. Branch `v2-publication-grade`.
> Companion to the high-level plan in `~/.claude/plans/ich-habe-mir-vor-crystalline-manatee.md`.
> Goal: a global, daily, point-in-time-correct equity database that withstands referee
> scrutiny as a CRSP/Datastream substitute — *with documented limitations*.

---

## 0. Non-negotiables (the contract this design must satisfy)

1. **Point-in-time correctness.** No value enters a return/characteristic at date `t` that
   was not knowable at `t`. (Factors lagged to availability; fundamentals lagged to reporting;
   market cap weights use `t-1`; vendor "adjusted" prices never trusted blind.)
2. **Survivorship-bias-free.** Delisted/dead instruments included; delisting returns imputed
   (Shumway). Point-in-time index membership, never today's list backward.
3. **Documented, reproducible cleaning.** Every screen has a threshold, a reason, a literature
   reference, and a row-count impact logged. Bronze is immutable & vintaged so any result can
   be re-derived from a frozen snapshot.
4. **Proven by validation, not asserted.** A benchmark suite must pass before the DB is
   labelled publication-grade (anchor-event alignment, factor correlation ≥ 0.95 vs Ken French,
   LSEG cross-check, delisting-bias demonstration, reproducibility hash check).
5. **Provider-agnostic.** EODHD is today's backbone but swappable behind an interface.

References: Ince & Porter (2006); Hanauer et al. (2021, JBF guidelines); Shumway (1997);
Shumway & Warther (1999); Bali, Engle & Murray (2016); Chen & Zimmermann (Open Source AP).

---

## 1. Layered architecture & build DAG

```
                 ┌─────────────────────────────────────────────────────┐
   DataProvider  │  provider.py (ABC) ── eodhd.py | sharadar.py | …     │
   (interface)   └─────────────────────────────────────────────────────┘
                                    │  every call writes a manifest row
                                    ▼
   BRONZE   immutable, vintaged raw  (bronze_*  +  meta_manifest, meta_vintage)
                                    │  C-rules + Ince-Porter screens + PIT total return
                                    ▼
   SILVER   cleaned, screened, PIT returns  (silver_price_daily, silver_fx_daily)
                                    │  monthly aggregation + delisting + factors + beta
                                    ▼
   GOLD     analysis-ready monthly panel  (gold_monthly_panel, gold_factor_return)
                                    │
   DIM      dim_asset · dim_exchange · dim_calendar · dim_index_membership (PIT)
   META     meta_manifest · meta_vintage · meta_data_quality · meta_download_log
```

Build order (CLI, extends existing `cli.py`):
`universe → download (smart) → calendar → transform screen → transform total-return →
transform clean → transform delisting → transform panel → transform factors-align →
audit --full → audit --benchmarks`.

---

## 2. Ingestion: provider abstraction & vintaged Bronze

### 2.1 `src/ingest/provider.py` (NEW) — the `DataProvider` ABC
Pure interface; adapters return **normalized** records (provider quirks isolated). Methods:

| Method | Returns (normalized) |
|---|---|
| `list_exchanges()` | exchange codes + metadata |
| `list_symbols(exchange, include_delisted=True)` | ticker, name, isin, type, currency, is_active |
| `get_prices(symbol, start, end)` | date, open, high, low, close, **raw_close (unadjusted)**, adj_close, volume |
| `get_splits(symbol, start)` | date, ratio (parsed to float) |
| `get_dividends(symbol, start)` | ex_date, value, unadjusted_value, currency, pay/record/decl dates |
| `get_fx(base, quote, start, end)` | date, rate |
| `get_fundamentals(symbol)` | as-reported statements + **report/filing dates** (for PIT lag) |
| `get_delisting(symbol)` | delist_date, reason_code (if available) |

- `src/ingest/eodhd.py` (NEW): wraps the **existing** `client.py` (rate-limit/retry already
  there) and maps EODHD JSON → the normalized schema. Crucially also pulls **`close`
  (unadjusted)** alongside `adjusted_close` — v1 leaned on adjusted_close only.
- `src/ingest/sharadar.py` (NEW, optional): US point-in-time / SBF backbone (SEP+SF1).
- Existing `prices.py`/`corporate_actions.py`/`fx.py`/`universe.py` call the provider instead
  of `client.py` directly.

### 2.2 Immutable, vintaged Bronze (provenance)
- New tables:
  - `meta_manifest(run_id, snapshot_date, endpoint, params_json, response_sha256, n_rows,
    http_status, fetched_at)` — one row per API response.
  - `meta_vintage(vintage_id, snapshot_date, provider, plan, git_commit, notes)` — a download
    campaign is a *vintage*; results are always traceable to one.
- Bronze rows carry `vintage_id`. Bronze is **append-only**; corrections create a new vintage,
  never overwrite. This is what makes "point-in-time vendor data" honest (EODHD revises).

---

## 3. Universe & identifier integrity (`src/ingest/universe.py` + `config/security_screens.yaml` NEW)

### 3.1 Static security screens (Ince-Porter §3, common-equity isolation)
Keep all instruments in `dim_asset` but **classify** rigorously; analysis defaults to common
equity. Drop/flag non-common securities by (a) provider type and (b) **name screens** — if the
security name contains any token, set `security_type` accordingly and exclude from the
common-equity view:

```
PREF, 'PF', PREFERRED         → preferred
WARRANT, WT, WARRANTS          → warrant
RIGHT, RT, RIGHTS              → right
UNIT, UNITS                    → unit
ETF, FUND, INDEX, TRUST(REIT?) → fund/etf/index   (REIT handled explicitly, not auto-dropped)
BOND, NOTE, DEBENTURE, '%'     → debt
DUPLICATE, DUP, XXX, TEST, '1000' placeholders → junk/duplicate
ADR, ADS, GDR                  → depositary_receipt (flag, don't silently drop)
EXPIRED, DELIST, 'WHEN ISSUED' → defunct/when-issued
```
Country-specific additions per Hanauer-et-al. appendix (e.g., investment trusts in UK).

### 3.2 Identifier hardening
- `dim_asset` gains: `isin`, `figi?`, `security_type`, `primary_listing` (bool),
  `first_seen`, `last_seen`, `delist_date`, `delist_reason`.
- **Ticker reuse**: a `(exchange,ticker)` whose `is_active` flips off then a *new* ISIN
  appears later → split into two `asset_id`s keyed by `isin`+`first_seen`. Never let one
  `asset_id` span two real entities.
- **ADR/dual-listing**: mark `primary_listing` (home exchange) to avoid double-counting in
  cross-sectional sorts.

### 3.3 Point-in-time index membership — `dim_index_membership` (NEW)
`(index, asset_id, start_date, end_date)`. Seed S&P 500 from the climate project's monthly
constituent files (`~/Desktop/GPA - CF/walter_R/Climate_Finance_LSEG_Data/SP_500_Cons_*.xlsx`).
Membership queries must be as-of-date, never "current members backward."

---

## 4. Bronze→Silver: total return, cleaning, screens

### 4.1 `src/transform/total_return.py` (NEW) — PIT total return (replaces blind adjusted_close)
v1 computes returns from EODHD `adjusted_close` (`clean.py:96-101`, `LAG(adjusted_close)`),
which bakes in the vendor's *retroactive* split/div adjustment. v2 reconstructs the
total-return index from **unadjusted close + cash dividends + split factors as known on each
date**:

```
split_factor_t  = ∏ splits with ex_date ≤ t            (cumulative, from raw events)
TRI_t           = (raw_close_t * split_factor_t + Σ div reinvested) chained from t-1
return_pit_t    = TRI_t / TRI_{t-1} - 1
```
The vendor `adjusted_close` is retained only as a **cross-check column** (`return_vendor`);
a validation test asserts `corr(return_pit, return_vendor) > 0.999` on clean names and
flags divergences (catches vendor adjustment errors — e.g., missed/mis-dated splits).

### 4.2 `src/transform/screens.py` (NEW) — Ince-Porter dynamic screens
Pure functions over the daily panel; each writes a bit into a `screen_flags` bitmask and never
silently deletes (analysis layer chooses what to drop). Exact definitions:

| Screen | Rule | Action |
|---|---|---|
| **P1 price floor** | `raw_close_{t-1}` below country threshold (e.g. local-currency penny) | flag `low_price`; return set missing in strict view |
| **R1 return reversal** (Ince-Porter) | `max(R_t, R_{t-1}) ≥ 300%` **and** `(1+R_t)(1+R_{t-1})−1 < 50%` | set **both** `R_t, R_{t-1}` missing (`reversal` flag) |
| **R2 extreme** | `|R_t| > 100%` daily / `>200%` retained-but-flagged | flag `extreme` |
| **S1 stale/padded** | ≥ `k` consecutive identical `raw_close` (k per liquidity) | flag `stale` |
| **C-rules (keep v1)** | `adj_close≤0`, `close≤0`, null date removed; sentinel `≥99,000` | remove impossible; **remove** sentinel in analysis view (v1 only flagged) |

Each screen logs rows affected → `docs/VALIDATION_REPORT.md` and `DECISIONS.md` (the
"X rows, Y%" transparency from the climate project).

### 4.3 Domain-aware NaN (climate pattern)
Physically impossible → NaN; economically valid negatives kept (e.g., negative book equity,
gross profit). Applied in `clean.py` for any fundamentals.

---

## 5. Delisting returns — `src/transform/delisting.py` (NEW, Shumway)

1. Classify `delist_reason` → {merger/acquisition, exchange-move, **performance/bankruptcy**,
   unknown} from provider status fields + name screens.
2. Last partial month: compute the within-month return through the final trade.
3. **Missing performance delistings** get a convention return (config-driven, documented):
   default **−30% (NYSE/AMEX)** / **−55% (Nasdaq/OTC)** per Shumway & Warther; neutral
   delistings get the realized/clean return, no penalty. Unknown→conservative flag, sensitivity
   in the audit.
4. Output: `gold_monthly_panel.delisting_return` + `delisting_flag`; a benchmark test shows the
   small-cap return gap **with vs without** the adjustment (the Shumway effect, made visible).

---

## 6. Silver→Gold: returns, FX, factors, beta, fundamentals

### 6.1 Monthly returns & FX (`returns.py`, extend)
- Keep correct monthly compounding (`last/first − 1`, `returns.py:58-108`) but feed it
  `return_pit`.
- **FX alignment**: snap FX to the **same month-end trading date** as the equity close;
  verify USD↔EUR triangulation residual ≈ 0. (v1 used `LAST_VALUE` of FX month — verify the
  stamp matches the return's month-end.)

### 6.2 Factor alignment — *the* look-ahead fix (`returns.py`/`factors.py`)
v1 merges factors by `DATE_TRUNC('month', date)` with **no availability lag** — the exact bug
caught in the climate project. v2:
- Align Ken French / q-factors to **information-availability dates** (month-end label, released
  next business day → matched to the return month they describe, *not* shifted into the future).
- Bake the **anchor-event test** into `audit/benchmarks.py`: the COVID crash (US Mkt-RF
  ≈ −13.35%, 2020-03) must sit on `2020-03`; and `corr(panel_mkt_return[t], MktRF[t])` must be
  **≥ 0.95 at lag 0** (a high correlation only at lag ±1 ⇒ misalignment ⇒ test fails the build).

### 6.3 Market-cap timing (`mv[t-1]`)
All value-weighted constructions use **beginning-of-month** market cap. Port the climate
helpers verbatim as the reference implementation:
`construct_factor_portfolios`, `hac_mean`, `ff5_regression`
(`~/Desktop/GPA - CF/notebooks/02_task_4.ipynb`). Audit asserts `corr(mv[t], ret[t])` is *not*
silently used as a weight.

### 6.4 Beta (`risk.py`, keep F&P 2014; remove the RAM cap)
Methodology unchanged (`beta = w·ρ·σ_i/σ_m + (1−w)·1`, `risk.py:212-213`, w=0.6, 252/1260
windows). v2 **computes US & Frankfurt** too (v1 skipped them on 8 GB RAM) by chunking per
exchange/year and spilling to the external drive; document the (slower) HDD path.

### 6.5 Point-in-time fundamentals (for Climate/ESG)
Lag by **reporting availability**: quarterly **+3 months**, annual **+6 months**; upgrade to
**fiscal-year-end-aware** lag where FY end is known (the climate "Felix-Fix"). Never use a
statement before its filing date.

---

## 7. Trading calendar (`src/ingest/calendar.py`, fix naive inference)

v1 infers trading days from "any instrument traded" → a market-wide holiday with zero rows is
mis-marked as non-trading. v2: use real exchange calendars (`pandas-market-calendars` /
EODHD `/exchange-details`) as ground truth, **cross-check** against inferred days, and log
divergences. Calendar feeds the stale-price screen and monthly-completeness counts.

---

## 8. Validation & benchmark suite (`src/audit/benchmarks.py` NEW; extends `checks.py`)

The build is "publication-grade" only when ALL pass. Each is a function returning
PASS/FAIL + evidence, written to `docs/VALIDATION_REPORT.md`:

1. **Structural/referential** (keep v1): no dup PKs, no orphans, schema version.
2. **Anchor-event alignment**: COVID −13.35% on 2020-03; factor `corr ≥ 0.95 @ lag 0`.
3. **Factor reconstruction**: own size/value/market factors correlate **≥ 0.95** with Ken
   French same-region; sign & magnitude of premia plausible.
4. **OSAP replication**: replicate a handful of Chen-Zimmermann signals; t-stats in range.
5. **LSEG cross-check**: for overlapping S&P 500 names/months, `return` and `mv` match the
   climate LSEG panel within tolerance (independent Refinitiv-grade benchmark you already own).
6. **Corporate-action anchors**: AAPL 4:1 (2020-08), 7:1 (2014-06) reflected; `return_pit` ≈
   `return_vendor`.
7. **Delisting-bias demonstration**: small-cap decile return with vs without delisting returns.
8. **Coverage/sentinel distribution**: where/when sentinels & gaps concentrate (per exchange).
9. **Reproducibility**: rebuild a sampled exchange from its vintage → identical `response_sha256`
   and identical Silver hashes.

---

## 9. Documentation deliverables (`docs/`)

- `ARCHITECTURE_V2.md` (this file) — the design.
- `METHODOLOGY.md` — every rule + threshold + reference + row-impact.
- `DATA_DICTIONARY.md` — table/column/units/source/constraints.
- `LIMITATIONS.md` — honest register (EODHD vs CRSP, pre-2000 survivorship, FX gaps, sentinel
  share, calendar caveats, ADR handling).
- `DECISIONS.md` — decision log à la climate project (choice + rationale + before/after).
- `VALIDATION_REPORT.md` — auto-generated suite results per vintage.

---

## 10. Schema deltas vs v1 (in `src/core/db.py`)

- `dim_asset`: + `isin, security_type, primary_listing, first_seen, last_seen, delist_date,
  delist_reason`.
- `dim_index_membership` (NEW): `(index, asset_id, start_date, end_date)`.
- `bronze_price_daily`: + `raw_close`, `vintage_id`.
- `silver_price_daily`: + `return_pit`, `return_vendor`, `screen_flags` (bitmask).
- `gold_monthly_panel`: + `delisting_return`, `delisting_flag`, `mktcap_beg` (t-1 weight).
- `meta_manifest`, `meta_vintage` (NEW).

---

## 11. Config knobs (`config/settings.yaml`; example tracked)

`screens.price_floor_by_country`, `screens.reversal_threshold (300%/50%)`,
`screens.stale_k`, `delisting.perf_return_nyse (−0.30)`, `delisting.perf_return_nasdaq (−0.55)`,
`fundamentals.lag_quarterly (3)`, `fundamentals.lag_annual (6)`,
`factors.availability_lag_days`, `universe.security_screen_file`. All defaults from the
literature, set **ex ante** (no in-sample tuning — avoids data-snooping).

---

## 12. Execution order (full rigorous build)

0. New drive APFS + git (done) → settings.yaml path to new drive · 1. Reactivate EODHD · 2.
provider.py + eodhd.py + manifest/vintage · 3. universe + security screens + index membership ·
4. download Bronze (~5 d, API-bound) · 5. calendar (real) · 6. total_return + screens + clean →
Silver · 7. delisting · 8. returns + factor-alignment + mv[t-1] + beta(US/FRA) → Gold ·
9. fundamentals PIT (climate) · 10. audit + benchmarks green · 11. docs · 12. backup-by-repro
(git push) + optional Gold snapshot.
