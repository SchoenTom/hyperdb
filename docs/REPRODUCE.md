# Reproduce HyperDB — Open Pipeline, Bring Your Own API Key

HyperDB is shipped as a **pipeline, not a dataset**. Anyone can clone this repo, plug in their
own data-provider API key, run the build, and obtain a **byte-for-byte comparable**,
publication-grade equity database — clean, consecutively ordered, gap-honest, well-covered,
and academically defensible. Reproducibility *is* the quality proof (cf. Chen & Zimmermann,
Open Source Asset Pricing).

## What you need
- Python 3.11+, DuckDB 1.0+ (`pip install -r requirements.txt`)
- A data-provider subscription. Default backbone: **EODHD All-World** (≈100k calls/day).
  The provider is swappable behind `src/ingest/provider.py` (EODHD / Sharadar / …).
- A drive with ~150–300 GB free for the full global daily build (APFS/ext4/NTFS-journaled —
  **not** non-journaled exFAT).

## Quickstart
```bash
cp config/settings.example.yaml config/settings.yaml   # settings.yaml is gitignored
# edit settings.yaml: set api.token (YOUR key) and paths.data_dir / paths.db_file
python cli.py universe                 # build instrument universe (active + delisted)
python cli.py download smart           # ~5 days, API-rate-bound, resumable
python cli.py calendar                 # real exchange calendars
python cli.py transform screen         # Ince-Porter static/dynamic screens
python cli.py transform total-return   # point-in-time total returns
python cli.py transform clean          # Bronze -> Silver
python cli.py transform delisting      # Shumway delisting returns
python cli.py transform panel          # Silver -> Gold (returns, beta, mv[t-1])
python cli.py transform factors-align  # availability-lagged factor merge
python cli.py audit --full             # integrity + coverage
python cli.py audit --benchmarks       # publication-grade gate (see below)
```
Builds are **idempotent and resumable** (`meta_download_log`), and every API response is
recorded in `meta_manifest` under a `vintage_id`, so a run is pinned to a frozen snapshot.

## The "good database" — machine-checkable acceptance criteria
A build is **publication-grade** only when `audit --benchmarks` reports PASS on all of:

### A. Integrity & ordering ("consecutive, orderly")
- 0 duplicate primary keys (`(asset_id,date)`, `(asset_id,month)`, FX, splits).
- 0 orphan rows (every price/return references a `dim_asset`/`dim_exchange`).
- Each asset's daily series has **strictly increasing, unique dates**; monthly panel is exactly
  **one row per `(asset_id, month)`** across the asset's active life; globally sorted.
- Schema version matches `meta_schema_version`.

### B. Missing-data policy ("no NaNs" — the honest definition)
- The Gold **clean view** has **NO NaN in core fields** (`return_pit`, `mktcap_beg`, ids, dates).
- **Gaps are represented as absent rows, never fabricated or interpolated.** No forward-fill of
  prices into non-trading periods; no synthetic returns.
- Every removed/missing value traces to exactly one rule: *physically impossible* (removed) or
  *screen* (flagged) — with counts logged to `VALIDATION_REPORT.md`. Nothing is silently dropped.

### C. Coverage ("well-filled, legitimate")
- Per-asset trading-day completeness vs the real exchange calendar ≥ threshold (flag below).
- Cross-sectional breadth per month ≥ N names for each major market (no thin months passing
  silently).
- Date span and instrument counts within expected bands; sentinel/`gap` share reported per
  exchange (concentration surfaced, not hidden).

### D. Correctness vs external truth (the proof it is legitimate)
- **Anchor-event alignment**: COVID US Mkt-RF ≈ −13.35% sits on 2020-03; factor/return
  `corr ≥ 0.95 at lag 0` (misalignment fails the build).
- **Factor reconstruction**: own size/value/market factors correlate **≥ 0.95** with Ken French.
- **Corporate-action anchors**: AAPL 4:1 (2020-08) & 7:1 (2014-06) reflected; `return_pit ≈
  return_vendor`.
- **LSEG cross-check** (if available): overlapping S&P 500 returns/market-caps match within
  tolerance.
- **Delisting-bias demonstration**: small-cap returns shift as expected once Shumway delisting
  returns are applied.

### E. Reproducibility
- Re-running a sampled exchange from its `vintage_id` yields identical `response_sha256` and
  identical Silver hashes. Two people with the same provider/plan/vintage get the same DB.

## Verifying *your* build
`python cli.py audit --benchmarks` writes `docs/VALIDATION_REPORT.md`. Compare it to the
reference numbers the repo ships per vintage. All PASS ⇒ you hold the same publication-grade
database.

## Honesty clause
EODHD ≠ Bloomberg/CRSP. Known limitations (pre-2000 survivorship, FX gaps, ADR handling,
sentinel values) are enumerated in `LIMITATIONS.md`. The pipeline's value is that every
cleaning choice is explicit, referenced, and reproducible — the accepted standard for
Datastream-class data in published research.

## License & citation
See `LICENSE` (to be added) and `CITATION.cff`. Pipeline design follows Ince & Porter (2006),
Hanauer et al. (2021), Shumway (1997), Bali-Engle-Murray (2016), Chen & Zimmermann.
