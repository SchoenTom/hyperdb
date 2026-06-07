# Methodology

> Every cleaning rule, threshold, and transformation, with its literature reference and its
> measured row-level impact. Thresholds are fixed **ex ante** (no in-sample tuning — see T21).
> Impact columns marked `‹build›` are populated automatically by `cli.py audit --full` after a
> database is built; they are **not** asserted here beforehand.

## 1. Universe & security typing
- Static security screens (non-common-equity isolation): see `config/security_screens.yaml`.
- Entity resolution (HyperID): see `ENTITY_RESOLUTION.md`.
- Rows by `security_type`: `‹build›`

## 2. Bronze → Silver cleaning rules
| Rule | Definition | Threshold | Action | Rows affected |
|---|---|---|---|---|
| C1 | `adjusted_close ≤ 0` | — | remove (impossible) | `‹build›` |
| C2 | `close ≤ 0` | — | remove (impossible) | `‹build›` |
| C3 | null date | — | remove | `‹build›` |
| C5 | sentinel `≥ 99,000` (EODHD 999,999.99) | 99,000 | remove in analysis view | `‹build›` |
| P1 | price floor | per-country | flag `low_price` | `‹build›` |
| R1 | Ince-Porter reversal | 300% / 50% | set both returns missing | `‹build›` |
| R2 | extreme daily return | 100% / 200% | flag | `‹build›` |
| S1 | stale/padded run | k consecutive | flag `stale` | `‹build›` |

## 3. Point-in-time total return
Reconstruction from raw close + dividends + split factors known as of each date; vendor
`adjusted_close` retained only as cross-check (`return_vendor`). Definition in
`ARCHITECTURE_V2.md §4.1`. Divergence stats: `‹build›`

## 4. Delisting returns (Shumway)
Reason classification; missing performance-delist convention (−30% NYSE/AMEX, −55% Nasdaq).
Counts by reason: `‹build›`

## 5. Returns, FX, factor alignment, beta
Monthly compounding; FX month-end alignment; availability-lagged factors (+ COVID anchor test);
`mv[t-1]` weights; F&P-2014 beta (252/1260 windows, Vasicek w=0.6). Parameters in
`config/settings.yaml`.

## 6. Point-in-time fundamentals
Reporting lag: quarterly +3m, annual +6m (FY-end-aware where known). As-reported, vintaged.
