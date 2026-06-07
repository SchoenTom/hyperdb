# HyperDB

```
        one API key
             │
   ┌─────────▼─────────┐   ┌───────────────────┐   ┌───────────────────┐
   │        raw        │ ─►│      cleaned      │ ─►│       panel       │ ─►  research
   └───────────────────┘   └───────────────────┘   └───────────────────┘
     immutable, vintaged     screened, point-in-     returns, betas,
     every response hashed    time total returns      delisting, identity
```

**A reproducible pipeline for a global, point-in-time equity database.**
The repository is the pipeline, not the data: you supply a data-provider API key and
rebuild the database locally. Same input, same panel — every time.

```
license  MIT (code only, no vendor data)   ·   python  3.11+   ·   storage  DuckDB
```

---

## What it is

Commercial research data (CRSP, Compustat, Bloomberg) is expensive and access-gated.
HyperDB builds a research panel from an affordable global provider and makes it
*trustworthy* — through documented screening, point-in-time discipline, delisting
adjustment, and explicit identity resolution. It does not pretend to be CRSP; it aims
to be defensible and transparent, with every choice written down and every result
reproducible from a frozen data snapshot. Design rationale: [docs/DESIGN.md](docs/DESIGN.md).

## The three stages

```
raw       vendor data, stored unchanged · immutable · vintaged (responses hashed)
cleaned   screened (Ince–Porter) · point-in-time total returns · quality flags
panel     analysis-ready monthly panel: returns, betas, delisting returns, factors
```

Standard reproducible-research layering (raw → interim → processed) — deliberately not a
"Bronze/Silver/Gold medallion", which is data-warehouse product terminology.

## What it gets right — the hard part

Equity data fails quietly. Each line is a way a real result turns into a false one, and
what the pipeline does about it. Full register: [docs/VALIDITY.md](docs/VALIDITY.md).

```
survivorship bias    →  delisted firms kept + delisting returns (Shumway 1997)
look-ahead           →  point-in-time returns · availability-lagged factors · mv[t-1]
ticker reuse/change  →  permanent identities — the PERMNO problem
data errors          →  documented static & dynamic screens (Ince & Porter 2006)
irreproducibility    →  immutable, vintaged raw + per-response manifests
```

Identity is the hardest of these; it has its own note: [docs/IDENTITY.md](docs/IDENTITY.md).

## Sources

| Source | Data | Access |
|---|---|---|
| EODHD (default) | prices, dividends, splits, FX, fundamentals | your API key |
| Kenneth French | FF3 / FF5 / momentum factors | public |
| Global-Q · FRED | q-factors · macro series | public |
| Sharadar (optional) | point-in-time US prices & fundamentals | your subscription |

No vendor data is redistributed here; you obtain data under your own licence.

## Rebuild it

```bash
pip install -r requirements.txt
cp config/settings.example.yaml config/settings.yaml   # set your api.token + paths
python cli.py universe
python cli.py download smart        # ~5 days, API-rate-bound, resumable
python cli.py calendar
python cli.py transform screen total-return clean delisting panel factors-align
python cli.py audit --full --benchmarks
```

Idempotent and resumable. The criteria a build must meet: [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Documentation

```
DESIGN.md      how the pipeline is built, stage by stage
VALIDITY.md    every threat to validity, and the countermeasure for each
IDENTITY.md    the PERMNO problem and how identity is resolved
REPRODUCE.md   rebuilding the database and its acceptance criteria
DISCLAIMER.md  terms of use
```

Empirical reports (cleaning impact, coverage, validation) are produced by the build —
they are absent here because they do not exist until you run it.

## Limitations · Disclaimer · AI use

EODHD is a budget provider; pre-2000 survivorship, emerging-market FX, and
corporate-action edge cases are weaker than commercial standards, and identity linkage
is heuristic where ISIN is missing — see [docs/VALIDITY.md](docs/VALIDITY.md).

For research use only; provided "as is", without warranty; not investment advice;
historical data, not for live trading — see [docs/DISCLAIMER.md](docs/DISCLAIMER.md). The
pipeline design, code, and documentation were developed with assistance from an AI coding
assistant (Anthropic's Claude); the author reviewed and validated all content and is
solely responsible for it.

## Citation · References

Cite via [CITATION.cff](CITATION.cff). Built on Ince & Porter (2006), Shumway (1997),
Frazzini & Pedersen (2014), Fama–French (1993, 2015), Hou–Xue–Zhang (2015),
Bali–Engle–Murray (2016), and Chen–Zimmermann (Open Source Asset Pricing).
