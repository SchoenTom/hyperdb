# Design & Build Specification

> How HyperDB turns raw end-of-day vendor data into a global, daily, point-in-time-correct
> equity database that withstands referee scrutiny as a CRSP/Datastream substitute — *with
> documented limitations*. Read alongside [VALIDITY](VALIDITY.md) (why each choice exists) and
> [IDENTITY](IDENTITY.md) (the hardest part).

## 0. Non-negotiables (the contract this design satisfies)

1. **Point-in-time correctness.** Nothing enters a return/characteristic at date `t` that was
   not knowable at `t`: factors lagged to availability, fundamentals lagged to reporting, market
   cap weighted at `t-1`, vendor "adjusted" prices never trusted blind.
2. **Survivorship-bias-free.** Delisted instruments included; delisting returns imputed
   (Shumway). Index membership is point-in-time, never today's list backward.
3. **Documented, reproducible cleaning.** Every screen has a threshold, a reason, a reference,
   and a logged row-impact. Bronze is immutable & vintaged, so any result re-derives from a
   frozen snapshot.
4. **Proven, not asserted.** A benchmark suite must pass before the database is called
   publication-grade.
5. **Provider-agnostic.** EODHD is the default backbone but swappable behind an interface.

References: Ince & Porter (2006); Hanauer et al. (2021); Shumway (1997); Shumway & Warther
(1999); Bali, Engle & Murray (2016); Chen & Zimmermann (Open Source Asset Pricing).

## 1. Layered architecture & build order

```
   DataProvider   provider.py (ABC) ── eodhd · sharadar · …
   (interface)         │  every response hashed → meta_manifest
                       ▼
   BRONZE   immutable, vintaged raw            bronze_* + meta_manifest, meta_vintage
                       │  screens · point-in-time total return
                       ▼
   SILVER   cleaned, screened, PIT returns      silver_price_daily, silver_fx_daily
                       │  monthly aggregation · delisting · factors · beta
                       ▼
   GOLD     analysis-ready monthly panel        gold_monthly_panel, gold_factor_return
   DIM      company · entity · listing · exchange · calendar · index_membership (PIT)
   META     meta_manifest · meta_vintage · meta_download_log
```

Build (CLI): `universe → download → calendar → transform screen → transform total-return →
transform clean → transform delisting → transform panel → transform factors-align →
audit --full → audit --benchmarks`.

## 2. Ingestion — provider abstraction & vintaged Bronze

**`DataProvider` interface** (`src/ingest/provider.py`): adapters return *normalized* records so
provider quirks stay isolated. Methods: `list_exchanges`, `list_symbols(include_delisted=True)`,
`get_prices` (incl. **raw unadjusted close**), `get_splits`, `get_dividends`, `get_fx`,
`get_fundamentals` (with report/filing dates), `get_delisting`. The default `eodhd` adapter
wraps the rate-limited API client; a `sharadar` adapter can back the US sub-universe.

**Vintaged Bronze (provenance).** Every API response is recorded in `meta_manifest`
(`endpoint, params, response_sha256, n_rows, fetched_at, vintage_id`). A download campaign is a
*vintage*; Bronze is append-only and carries `vintage_id`, so results trace to a frozen snapshot
even though vendor data is revised over time.

## 3. Universe & identifier integrity

**Static security screens** (common-equity isolation, Ince & Porter): classify every instrument
by provider type **and** name screens (`PREF/WARRANT/RIGHT/UNIT/ETF/FUND/BOND/DUPLICATE/ADR/…`);
the common-equity view excludes non-common types (REITs handled explicitly, not auto-dropped).
Country-specific additions per the international-data guidelines.

**Identity** is the hardest correctness problem and has its own document:
[IDENTITY.md](IDENTITY.md) (the PERMNO problem → a permanent `company → entity → listing`
model resolving ticker reuse, ticker changes, cross-listings, and share classes).

**Point-in-time index membership** (`dim_index_membership`, `(index, member, start, end)`):
membership is always queried as-of-date, never "current constituents backward."

## 4. Bronze → Silver — total return, screens, cleaning

**Point-in-time total return** (`src/transform/total_return.py`). Returns are reconstructed from
**unadjusted close + cash dividends + split factors known as of each date**, not from a vendor
`adjusted_close` (which is recomputed retroactively whenever a new split occurs → look-ahead):

```
split_factor_t = ∏ splits with ex_date ≤ t
TRI_t          = (raw_close_t · split_factor_t + Σ reinvested dividends) chained from t-1
return_pit_t   = TRI_t / TRI_{t-1} − 1
```
Vendor `adjusted_close` is kept only as a cross-check (`return_vendor`); a test asserts
`corr(return_pit, return_vendor) > 0.999` on clean names and flags divergences (catches
missed/mis-dated vendor splits).

**Dynamic screens** (`src/transform/screens.py`) — each writes a bit into `screen_flags`, never
silently deletes:

| Screen | Rule | Action |
|---|---|---|
| P1 price floor | prior price below a country threshold | flag `low_price` |
| R1 reversal (Ince-Porter) | `max(R_t,R_{t-1}) ≥ 300%` **and** `(1+R_t)(1+R_{t-1})−1 < 50%` | both returns → missing |
| R2 extreme | `\|R_t\|` above threshold | flag `extreme` |
| S1 stale/padded | ≥ k identical consecutive prices | flag `stale` |
| C-rules | `close ≤ 0`, null date removed; sentinel `≥ 99,000` removed in analysis view | clean |

Domain-aware missing values: physically impossible → removed; economically valid negatives
(e.g., negative book equity) kept. Every screen's row-impact is logged to the build's
validation report.

## 5. Delisting returns (Shumway)

Classify the delisting reason (merger / exchange-move / **performance-bankruptcy** / unknown);
impute missing performance-delisting returns with documented conventions (default **−30%**
NYSE/AMEX, **−55%** Nasdaq/OTC); neutral delistings keep their realized return. Output
`delisting_return` + `delisting_flag`; a benchmark shows the small-cap return gap **with vs
without** the adjustment.

## 6. Silver → Gold — returns, FX, factors, beta, fundamentals

- **Monthly returns** compound `return_pit`; **FX** is snapped to the same month-end stamp as
  the equity close, with a USD↔EUR triangulation check.
- **Factor alignment** (the classic look-ahead trap): factors are aligned to their
  *information-availability* dates, never shifted into the future. A hard **anchor-event test**
  guards it — the COVID crash (US Mkt-RF ≈ −13.35%) must land on 2020-03 and
  `corr(market_return, MktRF) ≥ 0.95 at lag 0`, or the build fails.
- **Market-cap weighting** uses beginning-of-month `mv[t-1]` (contemporaneous `mv[t]`
  correlates ≈ 0.85 with the month's return → look-ahead).
- **Beta** follows Frazzini & Pedersen (2014) (`β = w·ρ·σ_i/σ_m + (1−w)`, 252/1260-day windows,
  Vasicek shrinkage), computed for all exchanges.
- **Fundamentals** are lagged to reporting availability (quarterly +3m, annual +6m;
  fiscal-year-end-aware where known), stored as-reported and vintaged.

## 7. Trading calendar

Real exchange calendars (`pandas-market-calendars` / provider exchange details) are ground
truth, cross-checked against days inferred from data; divergences logged. This prevents a
market-wide holiday with zero rows from being mis-marked as a non-trading day.

## 8. Validation & benchmark suite (`src/audit/benchmarks.py`)

Publication-grade only when **all** pass (each returns PASS/FAIL + evidence to the build's
validation report): structural/referential integrity · anchor-event alignment · own factors
correlate ≥ 0.95 with Ken French · replication of a few Open-Source-Asset-Pricing signals ·
cross-check vs an independent benchmark extract where available · corporate-action anchors
(AAPL 4:1 2020-08, 7:1 2014-06) · delisting-bias demonstration · coverage/sentinel distribution
· reproducibility hashes. Full criteria in [REPRODUCE.md](REPRODUCE.md).

## 9. Schema (key tables, `src/core/db.py`)

- Identity: `dim_company`, `dim_entity`, `dim_listing` (+ `isin, security_type,
  primary_listing, first_seen, last_seen, delist_date, delist_reason`); `dim_index_membership`.
- `bronze_price_daily`: + `raw_close`, `vintage_id`.
- `silver_price_daily`: + `return_pit`, `return_vendor`, `screen_flags` (bitmask).
- `gold_monthly_panel`: + `delisting_return`, `delisting_flag`, `mktcap_beg` (t-1 weight).
- `meta_manifest`, `meta_vintage`.

## 10. Config (`config/settings.yaml`; example tracked)

Screen thresholds, delisting conventions, fundamental lags, and factor-availability lag are all
config knobs with defaults **fixed ex ante from the literature** — no in-sample tuning
(avoids data-snooping).
