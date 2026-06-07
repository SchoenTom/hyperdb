# Entity Resolution — Solving the PERMNO Problem without CRSP

> CRSP's single most valuable feature is not its prices — it is **PERMNO** (a permanent
> security identifier) and **PERMCO** (a permanent company identifier). They guarantee that a
> time series follows *one* real security through ticker changes, and never silently merges two
> different companies that happened to share a ticker. EODHD provides **no permanent
> identifier**. Reconstructing one is the single most important — and hardest — correctness task
> in this database. This document specifies how.

## 1. Why `(exchange, ticker)` is not an identity

| Failure mode | Example | Naive result |
|---|---|---|
| **Ticker reuse** | `GM`: old General Motors (delist 2009, bankruptcy) → new GM (IPO 2010) | one fake 35-yr series spanning two firms |
| **Ticker change** | `FB` → `META` (2022); `GOOG` → adds `GOOGL` (2014) | one firm split into two truncated series |
| **Cross-listing / ADR** | Shell home line (AS/LSE) + NYSE ADR | same firm counted 2–3× |
| **Share classes** | `BRK.A` / `BRK.B`; `GOOGL` / `GOOG` | distinct securities, one company |
| **M&A / reincorporation** | CUSIP/ISIN changes on merger | continuity broken or wrongly merged |

Any of these silently corrupts returns, weights, survivorship, and every downstream factor.

## 2. The HyperID model (three permanent layers)

```
company_id   (PERMCO-analogue)  one real company / issuer
   └── entity_id  (PERMNO-analogue)  one security (share class) over its whole life
          └── listing_id   one (exchange, ticker, currency) interval
                 └── asset_id   the daily-data key (back-compatible: EXCHANGE:TICKER:CLASS)
```

- **`listing_id`** — a contiguous interval of a `(exchange, ticker, currency)` with a start/end.
  Ticker changes and cross-listings create *new listings under the same entity*.
- **`entity_id`** — the permanent security. Survives ticker changes and venue moves. This is the
  unit returns are computed on.
- **`company_id`** — groups share classes / dual-listed lines of one issuer for company-level
  work (size, fundamentals).

New tables (`src/core/db.py`): `dim_company`, `dim_entity`, `dim_listing`; `dim_asset` rows
map to a `listing_id` → `entity_id` → `company_id`.

## 3. Resolution algorithm (anchored on ISIN + listing intervals)

**Primary anchor: ISIN.** Reasonably stable per security; changes on major events (so an ISIN
change is itself a signal). Steps:

1. **Listing intervals.** From per-symbol price history, derive each `(exchange,ticker)`'s
   `[first_seen, last_seen]` and detect internal trading gaps > G days.
2. **Entity linking (same security).**
   - Same ISIN across different `(exchange,ticker)` with overlapping/adjacent intervals → same
     `entity_id` (ticker change or cross-listing).
   - No ISIN: fall back to (normalized name + domicile + currency + adjacent interval) match,
     with a **confidence score**.
3. **Reuse splitting (different securities).**
   - Same `(exchange,ticker)` with a trading gap **and** a different ISIN after the gap → two
     `entity_id`s. Never bridge a delist→relist gap that changes ISIN.
4. **Cross-listing & primary.** Multiple concurrent listings under one entity → mark
   `primary_listing` by home domicile, then liquidity (median dollar volume). Cross-sectional
   sorts use the primary line only.
5. **Company grouping.** Link share classes / multiple entities of one issuer into `company_id`
   via issuer name + domicile + (where available) corporate structure / shared ISIN prefix.
6. **Confidence & provenance.** Every link stores `match_method` (`isin` | `name_interval` |
   `manual`) and a confidence in `[0,1]`. Low-confidence links are reported, never silently
   trusted.

## 4. Edge cases explicitly handled

- **Delist → bankruptcy → ticker reused years later** (T1): gap + ISIN change ⇒ split. Old
  entity gets a Shumway delisting return; new entity starts fresh.
- **Reverse merger / shell reuse:** ISIN change ⇒ new entity even if ticker persists.
- **Redomiciliation (e.g., ticker stays, ISIN country prefix changes):** same `company_id`,
  potentially new `entity_id`; documented.
- **Pre-2000 / EM without ISIN:** name+interval heuristics, flagged low-confidence, excluded
  from strict views unless validated.

## 5. Validation (in `audit/benchmarks.py`)

- **Anchor cases resolve correctly:** GM reuse → ≥2 entities; FB↔META → 1 entity; GOOGL/GOOG →
  2 entities / 1 company; a known cross-listing → 1 entity / N listings.
- **No entity spans an ISIN change** without an explicit corporate-action link.
- **No `(exchange,ticker)` maps to >1 entity at the same date.**
- **Report:** counts of entities, multi-listing entities, reuse-splits, and low-confidence
  links (transparency, not perfection).

## 6. Honest limitations

This is the **best achievable PERMNO-analogue from EODHD**, not CRSP. We lack CRSP's curated,
point-in-time CUSIP history. Where ISIN is missing or corporate actions are undocumented,
linkage is heuristic and flagged. `LIMITATIONS.md` will quantify the unresolved share after the
build. The value is that identity is *explicitly modeled, confidence-scored, and verifiable* —
not silently assumed by a ticker string.
