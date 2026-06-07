# Threats to Academic Validity — and How HyperDB Counters Each

> The hardest part of empirical asset pricing is not the factor model — it is the data.
> A brilliant strategy on flawed data produces confident nonsense. This register enumerates
> every known way a homemade equity database can be academically devalued, and the concrete
> countermeasure HyperDB applies. It is the project's central quality argument.
>
> **Status legend:** `Designed` = specified in the pipeline architecture; `Verified` = checked
> by the benchmark suite on a built database (post-build, no claims until then).

---

## A. Identity & entity resolution (the PERMNO problem)

**T1 — Ticker reuse over time.** A delisted ticker is later reassigned to a *different*
company (e.g., `GM`: old General Motors → bankruptcy 2009; new GM → IPO 2010). Naively keyed
by `(exchange,ticker)`, two distinct firms collapse into one fictitious 35-year series.
*Devalues:* fabricated continuity, contaminated long-run returns, broken survivorship logic.
*Countermeasure:* permanent surrogate identity (`entity_id`) anchored on ISIN + listing
intervals + corporate-action linkage; a trading gap followed by a new ISIN ⇒ new entity. See
`ENTITY_RESOLUTION.md`. *Verify:* GM/MCI/`anchor` reuse cases resolve to ≥2 entities. `Designed`

**T2 — Ticker change for the same firm.** Same company, new ticker (FB→META 2022; GOOG→
GOOGL). Naive keying splits one firm into two truncated series.
*Countermeasure:* ISIN-continuity links listings across ticker changes into one `entity_id`.
*Verify:* FB/META and Google class anchors map to single entities. `Designed`

**T3 — Cross-listings / ADRs double-count.** The same economic firm trades on several venues
(home line + ADR). Pooling them inflates the cross-section and double-weights the name.
*Countermeasure:* one `entity_id`, many `listing`s; a `primary_listing` flag (home/most-liquid)
used for cross-sectional sorts. *Verify:* multi-listing entities flagged; sorts use primary only.
`Designed`

**T4 — Share-class duplication.** `BRK.A`/`BRK.B`, `GOOGL`/`GOOG` are distinct securities of
one company. Treating them as unrelated breaks company-level aggregation; merging them breaks
security-level returns. *Countermeasure:* separate securities, grouped by a `company_id`
(PERMCO-analogue). `Designed`

**T5 — Missing/!unstable ISIN (EM, pre-2000).** When the anchor identifier is absent, entity
resolution degrades. *Countermeasure:* fallback heuristics (name + domicile + listing interval)
with an explicit **confidence flag**; low-confidence links surfaced, never hidden. `Designed`

## B. Survivorship & delisting

**T6 — Survivorship bias.** Excluding dead firms upward-biases returns (failed firms vanish).
*Countermeasure:* universe ingests **active + delisted** instruments (already in
`universe.py`); coverage report shows the delisted share. *Verify:* delisted count > 0 per
era/exchange. `Designed`

**T7 — Missing delisting returns (Shumway 1997).** Performance-related delistings (bankruptcy)
have their final, large negative return omitted far more often than neutral ones ⇒ small-cap
returns overstated. *Countermeasure:* classify delisting reason; impute missing
performance-delist returns (−30% NYSE/AMEX, −55% Nasdaq) per Shumway & Warther; neutral
delists unpenalized. *Verify:* small-cap decile return shifts with/without adjustment.
`Designed`

## C. Look-ahead / point-in-time integrity

**T8 — Retroactive split/dividend adjustment.** Vendor `adjusted_close` is recomputed over the
*whole* history when a new split occurs ⇒ using it embeds future information.
*Countermeasure:* reconstruct a point-in-time total-return index from **raw close + dividends +
splits known as of each date**; keep vendor adjusted only as a cross-check. *Verify:*
`corr(return_pit, return_vendor) > 0.999` on clean names; divergences flagged. `Designed`

**T9 — Factor release lag (the misalignment bug).** Ken French / q-factors are published after
month-end; merging by calendar month without an availability rule mis-dates them by one month —
the exact bug found in the GPA-CF project (long-only β flipped from ≈ −0.2 to ≈ +1.0 once
corrected). *Countermeasure:* availability-aware factor alignment + a hard **anchor-event test**
(COVID US Mkt-RF ≈ −13.35% must land on 2020-03; `corr ≥ 0.95 @ lag 0` or the build fails).
*Verify:* anchor test in `benchmarks.py`. `Designed`

**T10 — Market-cap weighting look-ahead.** Value-weighting by *contemporaneous* `mv[t]`
over-weights within-month winners (`corr(mv[t],ret[t]) ≈ 0.85`). *Countermeasure:* all weights
use beginning-of-month `mv[t-1]`. `Designed`

**T11 — Fundamentals reporting lag & restatements.** Using a financial statement before its
filing date, or using restated (not as-reported) figures, is look-ahead.
*Countermeasure:* lag quarterly +3m / annual +6m (fiscal-year-end-aware where known); store
as-reported with report/filing dates; vintaged so restatements don't leak backward. `Designed`

**T12 — Point-in-time index membership.** Using today's S&P 500 list historically is
survivorship + look-ahead. *Countermeasure:* `dim_index_membership` with start/end intervals
(seeded from the GPA-CF monthly constituent files); membership is always as-of-date. `Designed`

## D. Data errors & corporate actions

**T13 — Bad ticks, reversals, stale & sentinel prices.** Data-entry errors (a price and its
reversal), padded/stale prices, and EODHD's `999,999.99` placeholder create spurious extreme
returns. *Countermeasure:* Ince-Porter dynamic screens (reversal filter, stale-run flag, price
floor) + removal of sentinels in the analysis view, all logged with counts. *Verify:* screen
impact table. `Designed`

**T14 — Corporate-action errors (splits/spinoffs/rights).** Missed or mis-dated splits create
fake ±50%+ jumps; spinoffs and rights issues are notoriously mishandled.
*Countermeasure:* PIT reconstruction catches split mismatches vs vendor; anchor splits
validated (AAPL 4:1 2020-08, 7:1 2014-06); spinoffs flagged as lower-confidence. `Designed`

## E. Coverage, gaps & completeness

**T15 — Brutal data gaps / thin cross-sections.** Sparse history or thin months silently weaken
inference. *Countermeasure:* coverage metrics (per-asset trading-day completeness vs real
calendar; cross-sectional breadth per month) with thresholds and a published coverage report;
gaps represented as **absent rows**, never filled. *Verify:* coverage gates. `Designed`

**T16 — Backfill bias in vendor data.** Vendors backfill history when adding a name; placeholder
zeros masquerade as data (the GPA-CF E-score lesson: 38–53% zeros pre-2010).
*Countermeasure:* detect placeholder/backfill runs; start-date / zero-contamination analysis
before trusting early history. `Designed`

## F. FX, calendar, microstructure, time zones

**T17 — FX timing & redenomination.** Mismatched FX stamps or unhandled currency
redenominations (legacy→EUR 1999; many EM redenominations) corrupt USD/EUR returns.
*Countermeasure:* FX snapped to the same month-end stamp as returns; triangulation residual ≈ 0;
explicit redenomination map. `Designed`

**T18 — Trading-calendar inference error.** Inferring "non-trading" from absent data mis-marks
market-wide holidays. *Countermeasure:* real exchange calendars cross-checked against inferred
days. `Designed`

**T19 — Non-synchronous / time-zone effects.** Global markets close at different times; "same
date" returns are not contemporaneous across regions (biases global betas/correlations).
*Countermeasure:* document the local-date convention; apply appropriate lead/lag for
cross-region statistics. `Designed`

**T20 — Microstructure / illiquidity.** Zero-volume days, bid-ask bounce, non-trading bias
estimates. *Countermeasure:* liquidity flags (volume, Amihud), non-trading excluded from return
computation. `Designed`

## G. Methodology & reproducibility

**T21 — Data-snooping in the pipeline itself.** Tuning screen thresholds to get nice results.
*Countermeasure:* every threshold fixed **ex ante** from the literature, documented in
`config` + `METHODOLOGY.md`; no in-sample tuning. `Designed`

**T22 — Non-reproducibility / vendor revision.** Vendor data changes; results can't be
re-derived. *Countermeasure:* immutable, vintaged Bronze + per-response manifests + hash-based
reproducibility check; results pinned to a `vintage_id`. *Verify:* re-run yields identical
hashes. `Designed`

**T23 — Winsorization / outlier choices.** Hidden trimming changes conclusions.
*Countermeasure:* provide flags, not forced winsorization; document any trimming and offer a
sensitivity in the audit. `Designed`

---

## Summary

| # | Threat | Status |
|---|--------|--------|
| T1–T5 | Identity / entity resolution (PERMNO problem) | Designed |
| T6–T7 | Survivorship & delisting returns | Designed |
| T8–T12 | Look-ahead / point-in-time | Designed |
| T13–T14 | Data errors & corporate actions | Designed |
| T15–T16 | Coverage, gaps, backfill | Designed |
| T17–T20 | FX, calendar, time-zone, microstructure | Designed |
| T21–T23 | Snooping, reproducibility, winsorization | Designed |

No threat is marked `Verified` until the database is built and `cli.py audit --benchmarks`
confirms it on real data. Until then these are designed countermeasures, not claimed results.
