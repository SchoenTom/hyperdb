# Decision Log

> Every non-obvious methodological choice, its rationale, its reference, and (where applicable)
> before/after evidence. Modelled on the GPA-CF project's `Decisions.md`. New entries are
> appended; nothing is silently changed.

| # | Decision | Rationale | Reference | Evidence |
|---|---|---|---|---|
| D1 | Reconstruct **point-in-time total returns**, do not trust vendor `adjusted_close` | retroactive adjustment embeds future splits/divs | — | `corr(pit,vendor)` `‹build›` |
| D2 | **Availability-lag factors**; enforce COVID anchor test | the one-month misalignment bug (GPA-CF) | — | lag-0 corr `‹build›` |
| D3 | Weight by **`mv[t-1]`** | contemporaneous mv look-ahead (`corr≈0.85`) | — | GMB Δ `‹build›` |
| D4 | Impute missing **performance-delisting returns** (−30%/−55%) | Shumway omission bias | Shumway & Warther (1999) | small-cap Δ `‹build›` |
| D5 | **ISIN-anchored entity resolution** (HyperID), confidence-scored | ticker reuse/change/cross-listing | CRSP PERMNO | unresolved share `‹build›` |
| D6 | **Remove** sentinels in analysis view (v1 only flagged) | placeholder contamination | GPA-CF zero-contamination | sentinel share `‹build›` |
| D7 | All screen thresholds fixed **ex ante** from literature | avoid data-snooping (T21) | Ince & Porter (2006) | — |
| D8 | Gaps as **absent rows**, never filled/interpolated | fabrication = academic fraud | — | — |

*(Quantitative evidence columns are filled by the build; not asserted beforehand.)*
