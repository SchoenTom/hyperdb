# Limitations (Honest Register)

> Referees trust a dataset more when its authors state its limits plainly. This register is
> deliberately candid. Quantities marked `‹build›` are filled from the actual build — not
> guessed.

1. **Provider ≠ CRSP/Bloomberg.** EODHD is a budget global provider. Corporate-action edge
   cases (spinoffs, rights), pre-2000 survivorship completeness, and point-in-time fundamentals
   are weaker than commercial gold standards. Mitigated by screening, validation, and this
   register — not eliminated.
2. **Entity resolution is heuristic where ISIN is missing.** Unresolved / low-confidence share:
   `‹build›`. See `ENTITY_RESOLUTION.md`.
3. **Pre-2000 / emerging-market coverage** is thinner; FX for some EM currencies sparse before
   2000. Affected currencies/periods: `‹build›`.
4. **Sentinel values** (EODHD 999,999.99) removed in the analysis view; distribution by
   exchange/era: `‹build›`.
5. **No intraday data.** Daily OHLCV only; no bid-ask spreads / tick data.
6. **Time-zone non-synchronicity** across global markets affects same-date cross-region
   statistics; local-date convention documented (T19).
7. **Spinoffs / complex corporate actions** flagged as lower-confidence rather than fully
   modeled.
8. **Delisting-return conventions** (Shumway −30%/−55%) are standard approximations, not
   security-specific realized returns; sensitivity reported in the audit.
9. **Calendar** built from real exchange calendars where available; residual inference gaps
   logged: `‹build›`.
