# Disclaimer and Terms of Use

**Academic research use.** This repository provides a data-construction *pipeline* for empirical
finance research. It is intended for academic and educational use.

**No data redistribution.** No third-party vendor data is distributed with this repository. The
pipeline orchestrates downloads and transformations of data that the user obtains under their
own licence (e.g., EODHD, and public sources such as the Kenneth French Data Library, Global-Q,
and FRED). Users are responsible for complying with the terms of their data providers.

**No warranty.** The pipeline and any database produced by it are provided "as is", without
warranty of any kind, express or implied, including but not limited to warranties of accuracy,
completeness, merchantability, or fitness for a particular purpose.

**No investment advice.** Neither the pipeline nor any data or results derived from it constitute
financial or investment advice or a recommendation to buy, sell, or hold any security. Any
outputs are for research purposes only.

**Limitation of liability.** In no event shall the author or contributors be liable for any
damages arising from the use of this pipeline or any database produced by it.

**Historical data; not for live trading.** A database built with this pipeline reflects
historical data as of the build date and is not updated in real time. It must not be used for
live trading or real-time decision-making.

**Known limitations.** The data provider used by default (EODHD) is a budget global source whose
coverage and corporate-action handling are weaker than commercial gold standards (CRSP,
Compustat, Bloomberg). Documented limitations are listed in [VALIDITY.md](VALIDITY.md) and
quantified by the build's coverage report.

**Use of AI tools.** The pipeline design, code, and documentation were developed with assistance
from an AI coding assistant (Anthropic's Claude).

**Citation.** If you use this pipeline in academic work, please cite it (see `CITATION.cff`).
