# HyperDB

An open, reproducible pipeline for constructing a global, daily, point-in-time equity database
for empirical asset-pricing research. The repository contains the **pipeline only**; it
distributes no vendor data. Researchers supply their own data-provider API key and rebuild the
database locally, so that results are independently reproducible rather than taken on trust.

University of Konstanz.

## Scope and intent

Commercial research databases (CRSP, Compustat, Refinitiv, Bloomberg) are expensive and
access-restricted. HyperDB instead builds a research panel from an affordable global provider
(EODHD by default) and makes that data trustworthy through documented screening, point-in-time
discipline, delisting adjustment, and explicit identity resolution. It is **not** a replacement
for CRSP or Bloomberg; the aim is a transparent, defensible alternative with stated limitations
— the standard accepted in published work that relies on Datastream-class data. The central
quality argument is reproducibility: anyone running the pipeline obtains the same panel.

## Data sources

| Source | Data | Access |
|---|---|---|
| EODHD (default) | End-of-day prices, dividends, splits, FX, fundamentals | user API key |
| Kenneth French Data Library | FF3 / FF5 / momentum factors | public |
| Global-Q | q-factor model | public |
| FRED | macroeconomic series | public |
| Sharadar (optional) | point-in-time US prices/fundamentals | user subscription |

No vendor data is redistributed in this repository; users obtain data under their own licences.

## Pipeline

The pipeline separates immutable raw data from cleaned and analysis-ready outputs — the standard
reproducible-research convention (cf. Cookiecutter Data Science `raw / interim / processed`;
the TIER protocol; Wilson et al., *Good Enough Practices in Scientific Computing*). It is
deliberately **not** framed as a "Bronze/Silver/Gold medallion" architecture, which is
data-warehouse product terminology rather than research methodology.

| Stage | Contents |
|---|---|
| **Raw** | Vendor data stored unchanged; immutable and vintaged (every API response hashed for provenance). |
| **Cleaned** | Screened and validated; point-in-time total returns; quality flags. |
| **Panel** | Analysis-ready monthly panel (returns, betas, delisting returns) and factor returns. |

Build order and commands are documented in [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Methodological choices

Each choice below addresses a specific way equity data can mislead. The full register, with
countermeasures and verification, is in [docs/VALIDITY.md](docs/VALIDITY.md).

- **Survivorship and delisting.** Delisted instruments are included; missing performance-related
  delisting returns are imputed following Shumway (1997).
- **Point-in-time discipline.** Total returns are reconstructed from unadjusted prices, dividends,
  and splits (not retroactively adjusted vendor series); factors are aligned to their
  availability dates; market-cap weights use the prior month; fundamentals are lagged to
  reporting.
- **Data screens.** Static and dynamic screens following Ince & Porter (2006) isolate common
  equity and remove data-entry errors; nothing is deleted silently.
- **Identity resolution.** Ticker reuse, ticker changes, cross-listings, and share classes are
  resolved into permanent identifiers — the problem CRSP solves with PERMNO. See
  [docs/IDENTITY.md](docs/IDENTITY.md).
- **Reproducibility.** Raw data are immutable and vintaged with per-response manifests, so any
  result re-derives from a frozen snapshot.

## Reproducing the database

```bash
pip install -r requirements.txt
cp config/settings.example.yaml config/settings.yaml   # gitignored; set your api.token and paths
python cli.py universe
python cli.py download smart        # ~5 days, API-rate-bound, resumable
python cli.py calendar
python cli.py transform screen total-return clean delisting panel factors-align
python cli.py audit --full --benchmarks
```

The build is idempotent and resumable. Acceptance criteria a build must meet are specified in
[docs/REPRODUCE.md](docs/REPRODUCE.md).

## Documentation

| Doc | Purpose |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | How the pipeline is built, stage by stage |
| [docs/VALIDITY.md](docs/VALIDITY.md) | Threats to validity and the countermeasure for each |
| [docs/IDENTITY.md](docs/IDENTITY.md) | The PERMNO problem and how identity is resolved |
| [docs/REPRODUCE.md](docs/REPRODUCE.md) | Rebuilding the database and its acceptance criteria |

Empirical reports (cleaning impact, coverage, validation results) are produced by the build.
They are not committed here because they do not exist until the pipeline is run.

## Limitations

EODHD is a budget global provider; corporate-action edge cases, pre-2000 survivorship
completeness, and emerging-market FX coverage are weaker than commercial gold standards.
Identity linkage is heuristic where ISIN is missing. These and other limitations are enumerated
in [docs/VALIDITY.md](docs/VALIDITY.md), and quantified by the build's coverage report.

## Citation

If you use this pipeline, please cite it; see [CITATION.cff](CITATION.cff).

## Disclaimer

For academic research use only. The pipeline is provided "as is", without warranty of any kind,
and is not investment advice. It distributes no vendor data; users must comply with their data
providers' licence terms. The resulting database reflects historical data and is not intended
for live trading. Full text: [docs/DISCLAIMER.md](docs/DISCLAIMER.md).

## Use of AI tools

The pipeline design, code, and documentation were developed with assistance from an AI coding
assistant (Anthropic's Claude). The author reviewed, revised, and validated all content and is
solely responsible for its correctness.

## References

- Ince, O. & Porter, R. B. (2006). Individual Equity Return Data from Thomson Datastream: Handle
  with Care! *Journal of Financial Research*, 29(4).
- Shumway, T. (1997). The Delisting Bias in CRSP Data. *Journal of Finance*, 52(1).
- Frazzini, A. & Pedersen, L. H. (2014). Betting Against Beta. *Journal of Financial Economics*,
  111(1).
- Fama, E. F. & French, K. R. (1993, 2015). *Journal of Financial Economics*.
- Hou, K., Xue, C., & Zhang, L. (2015). Digesting Anomalies. *Review of Financial Studies*, 28(3).
- Bali, T., Engle, R., & Murray, S. (2016). *Empirical Asset Pricing*. Wiley.
- Chen, A. & Zimmermann, T. Open Source Cross-Sectional Asset Pricing.
