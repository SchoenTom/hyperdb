# generate_figures.py – HyperDB data quality and coverage visualizations
#
# Generates publication-ready PDF figures for the HyperDB documentation.
# Style follows Frazzini & Pedersen (2014) replication standards.
#
# Usage: python generate_figures.py
# Output: reports/figures/*.pdf

import sys
from pathlib import Path
from datetime import datetime

_missing = []
for _pkg in ["duckdb", "pandas", "numpy", "matplotlib"]:
    try:
        __import__(_pkg)
    except ImportError:
        _missing.append(_pkg)
if _missing:
    print(f"Missing packages: {', '.join(_missing)}")
    sys.exit(1)

import duckdb
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec

# ── Paths ────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "hyperdb.duckdb"
FIG_DIR = Path(__file__).parent / "reports" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {
    "main":      "#1a3a4a",
    "accent":    "#4a8db7",
    "negative":  "#c0392b",
    "positive":  "#2e8b57",
    "muted":     "#8b9daa",
    "highlight": "#d4793a",
    "secondary": "#6b5b8a",
    "teal":      "#2a9d8f",
    "warm":      "#c9963b",
}

REGION_COLORS = {
    "North America": "#1a3a4a",
    "Europe":        "#4a8db7",
    "Asia-Pacific":  "#c0392b",
    "Other":         "#8b9daa",
}

plt.rcParams["font.family"] = "serif"
plt.rcParams["figure.dpi"] = 300
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False
plt.rcParams["savefig.bbox"] = "tight"


def _save(fig, name):
    path = FIG_DIR / f"{name}.pdf"
    fig.savefig(path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {path}")


def get_conn():
    return duckdb.connect(str(DB_PATH), read_only=True)


# ── Figure 1: Universe Growth ────────────────────────────────────────────────

def fig1_coverage_over_time():
    """How the investable universe grew over 40 years, by region."""
    con = get_conn()
    df = con.execute("""
        SELECT EXTRACT(YEAR FROM p.date) AS year,
               e.region,
               COUNT(DISTINCT p.asset_id) AS assets
        FROM raw_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        JOIN dim_exchange e ON a.exchange_code = e.exchange_code
        WHERE e.region IS NOT NULL
        GROUP BY 1, 2
    """).fetchdf()
    con.close()

    regions = ["North America", "Europe", "Asia-Pacific"]
    df["region_group"] = df["region"].apply(lambda r: r if r in regions else "Other")
    pivot = df.groupby(["year", "region_group"])["assets"].sum().unstack(fill_value=0)
    cols = [c for c in regions + ["Other"] if c in pivot.columns]
    pivot = pivot[cols]

    fig, ax = plt.subplots(figsize=(11, 6))
    pivot.plot.area(ax=ax, stacked=True,
                    color=[REGION_COLORS.get(c, "#ccc") for c in cols],
                    alpha=0.85, linewidth=0.5)
    ax.set_xlabel("Year")
    ax.set_ylabel("Instruments with price data")
    ax.set_title("Global Universe Growth (1985--2025)")
    ax.legend(loc="upper left", framealpha=0.9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))

    total_now = pivot.iloc[-1].sum()
    ax.annotate(f"{total_now/1000:.0f}K instruments",
                xy=(pivot.index[-1], total_now), xytext=(-60, 10),
                textcoords="offset points", fontsize=9, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=COLORS["main"]))
    _save(fig, "figure1_universe_growth")


# ── Figure 2: Top Exchanges ──────────────────────────────────────────────────

def fig2_exchange_ranking():
    """Top 20 exchanges ranked by total price observations."""
    con = get_conn()
    df = con.execute("""
        SELECT a.exchange_code, e.region,
               COUNT(*) AS observations,
               COUNT(DISTINCT p.asset_id) AS assets,
               MIN(p.date) AS first_date
        FROM raw_price_daily p
        JOIN dim_asset a ON p.asset_id = a.asset_id
        JOIN dim_exchange e ON a.exchange_code = e.exchange_code
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20
    """).fetchdf()
    con.close()

    regions = ["North America", "Europe", "Asia-Pacific"]
    colors = [REGION_COLORS.get(r if r in regions else "Other", "#ccc")
              for r in df["region"]]

    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(df["exchange_code"][::-1], df["observations"][::-1],
                   color=colors[::-1], edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Daily price observations")
    ax.set_title("Top 20 Exchanges by Data Volume")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e6:.0f}M"))

    for bar, (_, row) in zip(bars, df[::-1].iterrows()):
        ax.text(bar.get_width() + 1e6, bar.get_y() + bar.get_height()/2,
                f"{row['assets']:,} assets", va="center", fontsize=7,
                color=COLORS["muted"])

    for r in regions + ["Other"]:
        ax.barh(0, 0, color=REGION_COLORS.get(r, "#ccc"), label=r)
    ax.legend(loc="lower right", framealpha=0.9)
    _save(fig, "figure2_exchange_ranking")


# ── Figure 3: Survivorship Bias Control ───────────────────────────────────────

def fig3_survivorship():
    """Active vs delisted instruments — proving survivorship bias is controlled."""
    con = get_conn()
    df = con.execute("""
        SELECT
            CASE WHEN is_active THEN 'Active' ELSE 'Delisted' END AS status,
            asset_class,
            COUNT(*) AS n
        FROM dim_asset
        WHERE asset_class IN ('equity', 'etf', 'fund')
        GROUP BY 1, 2
        ORDER BY 2, 1
    """).fetchdf()

    timeline = con.execute("""
        SELECT EXTRACT(YEAR FROM MAX(p.date)) AS last_year,
               COUNT(DISTINCT p.asset_id) AS assets
        FROM raw_price_daily p
        GROUP BY p.asset_id
    """).fetchdf()
    con.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: active vs delisted by class
    pivot = df.pivot(index="asset_class", columns="status", values="n").fillna(0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    pivot.plot.bar(ax=ax1, color=[COLORS["positive"], COLORS["muted"]],
                   edgecolor="white", width=0.7)
    ax1.set_ylabel("Instruments")
    ax1.set_title("(a) Active vs Delisted by Asset Class")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
    ax1.legend(framealpha=0.9)
    plt.setp(ax1.get_xticklabels(), rotation=0)

    total_active = df[df["status"]=="Active"]["n"].sum()
    total_delisted = df[df["status"]=="Delisted"]["n"].sum()
    pct_delisted = total_delisted / (total_active + total_delisted) * 100
    ax1.text(0.97, 0.95, f"Delisted: {pct_delisted:.0f}%\nof universe",
             transform=ax1.transAxes, fontsize=9, ha="right", va="top",
             fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9))

    # Right: when did instruments drop out?
    bins = range(1985, 2027)
    ax2.hist(timeline["last_year"], bins=bins, color=COLORS["accent"],
             edgecolor="white", linewidth=0.3, alpha=0.85)
    ax2.set_xlabel("Last year with price data")
    ax2.set_ylabel("Number of instruments")
    ax2.set_title("(b) When Instruments Exit the Sample")
    ax2.axvline(2025, color=COLORS["positive"], linestyle="--", linewidth=1,
                label="Still active (2025)")
    ax2.legend(framealpha=0.9)

    fig.suptitle("Survivorship Bias Control", y=1.02, fontsize=13)
    _save(fig, "figure3_survivorship")


# ── Figure 4: Data Depth — History Length Distribution ────────────────────────

def fig4_data_depth():
    """How deep is the history? Distribution of years of data per instrument."""
    con = get_conn()
    df = con.execute("""
        SELECT p.asset_id,
               DATEDIFF('year', MIN(p.date), MAX(p.date)) AS years_of_data,
               COUNT(*) AS trading_days
        FROM raw_price_daily p
        GROUP BY 1
    """).fetchdf()
    con.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: years of history distribution
    ax1.hist(df["years_of_data"], bins=40, color=COLORS["main"],
             edgecolor="white", linewidth=0.3, alpha=0.85)
    ax1.set_xlabel("Years of price history")
    ax1.set_ylabel("Number of instruments")
    ax1.set_title("(a) History Depth per Instrument")
    ax1.axvline(df["years_of_data"].median(), color=COLORS["highlight"],
                linestyle="--", linewidth=1.5,
                label=f"Median: {df['years_of_data'].median():.0f} years")
    ax1.legend(framealpha=0.9)

    # Right: trading days distribution
    ax2.hist(df["trading_days"], bins=50, color=COLORS["teal"],
             edgecolor="white", linewidth=0.3, alpha=0.85)
    ax2.set_xlabel("Total trading days")
    ax2.set_ylabel("Number of instruments")
    ax2.set_title("(b) Observations per Instrument")
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
    ax2.axvline(df["trading_days"].median(), color=COLORS["highlight"],
                linestyle="--", linewidth=1.5,
                label=f"Median: {df['trading_days'].median():,.0f} days")
    ax2.legend(framealpha=0.9)

    fig.suptitle("Data Depth Analysis", y=1.02, fontsize=13)
    _save(fig, "figure4_data_depth")


# ── Figure 5: Cross-Sectional Coverage Per Month ──────────────────────────────

def fig5_cross_section():
    """How many instruments are available in each month for cross-sectional studies?"""
    con = get_conn()
    df = con.execute("""
        SELECT month, exchange_code,
               COUNT(DISTINCT asset_id) AS assets
        FROM panel_monthly
        GROUP BY 1, 2
    """).fetchdf()
    con.close()

    df["month"] = pd.to_datetime(df["month"])

    # Aggregate by month across all exchanges
    monthly = df.groupby("month")["assets"].sum().reset_index()

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.fill_between(monthly["month"], monthly["assets"],
                    color=COLORS["accent"], alpha=0.4)
    ax.plot(monthly["month"], monthly["assets"],
            color=COLORS["main"], linewidth=1)
    ax.set_xlabel("Month")
    ax.set_ylabel("Instruments in monthly panel")
    ax.set_title("Cross-Sectional Coverage Over Time")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))

    peak = monthly["assets"].max()
    peak_date = monthly.loc[monthly["assets"].idxmax(), "month"]
    ax.annotate(f"Peak: {peak/1000:.0f}K ({peak_date.year})",
                xy=(peak_date, peak), xytext=(-80, -30),
                textcoords="offset points", fontsize=9,
                arrowprops=dict(arrowstyle="->", color=COLORS["main"]))
    _save(fig, "figure5_cross_section")


# ── Figure 6: Return Distribution ─────────────────────────────────────────────

def fig6_return_distribution():
    """Monthly return distribution with normal overlay and fat-tail analysis."""
    con = get_conn()
    df = con.execute("""
        SELECT return_local FROM panel_monthly
        WHERE return_local IS NOT NULL
          AND return_local BETWEEN -1.0 AND 2.0
    """).fetchdf()
    con.close()

    returns = df["return_local"].values
    mu, sigma = np.mean(returns), np.std(returns)
    skew, kurt = pd.Series(returns).skew(), pd.Series(returns).kurtosis()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: histogram with normal
    ax1.hist(returns, bins=200, density=True, alpha=0.7,
             color=COLORS["accent"], edgecolor="white", linewidth=0.2)
    x = np.linspace(-0.6, 0.6, 500)
    normal = (1 / (sigma * np.sqrt(2*np.pi))) * np.exp(-0.5 * ((x - mu)/sigma)**2)
    ax1.plot(x, normal, color=COLORS["negative"], linewidth=1.5,
             label="Normal distribution")
    ax1.set_xlabel("Monthly return")
    ax1.set_ylabel("Density")
    ax1.set_title("(a) Return Distribution")
    ax1.set_xlim(-0.5, 0.5)
    ax1.legend(loc="upper right", framealpha=0.9)

    stats_text = (f"N = {len(returns):,}\n"
                  f"Mean = {mu*100:.2f}%\n"
                  f"Std  = {sigma*100:.2f}%\n"
                  f"Skew = {skew:.2f}\n"
                  f"Kurt = {kurt:.2f}")
    ax1.text(0.03, 0.95, stats_text, transform=ax1.transAxes,
             fontsize=8, va="top", fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9))

    # Right: QQ plot against normal
    sorted_r = np.sort(returns)
    n = len(sorted_r)
    theoretical = np.sort(np.random.normal(mu, sigma, n))
    # Subsample for plotting speed
    idx = np.linspace(0, n-1, 2000).astype(int)
    ax2.scatter(theoretical[idx], sorted_r[idx], s=1, alpha=0.4,
                color=COLORS["main"])
    lims = [-0.4, 0.4]
    ax2.plot(lims, lims, color=COLORS["negative"], linewidth=1, linestyle="--",
             label="45-degree line")
    ax2.set_xlabel("Theoretical quantiles (Normal)")
    ax2.set_ylabel("Sample quantiles")
    ax2.set_title("(b) Q-Q Plot vs Normal")
    ax2.set_xlim(lims)
    ax2.set_ylim(lims)
    ax2.legend(loc="upper left", framealpha=0.9)

    fig.suptitle("Monthly Return Analysis (21.6M observations)", y=1.02, fontsize=13)
    _save(fig, "figure6_return_distribution")


# ── Figure 7: Multi-Currency Coverage ─────────────────────────────────────────

def fig7_currency_coverage():
    """How many currencies are covered and FX data completeness."""
    con = get_conn()
    fx = con.execute("""
        SELECT base_currency, COUNT(*) AS days,
               MIN(date) AS first_date, MAX(date) AS last_date
        FROM raw_fx_daily
        WHERE quote_currency = 'USD'
        GROUP BY 1
        ORDER BY 2 DESC
    """).fetchdf()

    ccy_dist = con.execute("""
        SELECT a.currency, COUNT(DISTINCT a.asset_id) AS assets
        FROM dim_asset a
        WHERE a.currency IS NOT NULL
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 15
    """).fetchdf()
    con.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: assets per currency
    ax1.barh(ccy_dist["currency"][::-1], ccy_dist["assets"][::-1],
             color=COLORS["accent"], edgecolor="white", linewidth=0.5)
    ax1.set_xlabel("Instruments")
    ax1.set_title("(a) Top 15 Currencies by Instrument Count")
    ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))

    # Right: FX data completeness (days of FX data per currency)
    top_fx = fx.head(20)
    ax2.barh(top_fx["base_currency"][::-1], top_fx["days"][::-1],
             color=COLORS["teal"], edgecolor="white", linewidth=0.5)
    ax2.set_xlabel("Trading days of FX data")
    ax2.set_title("(b) FX Rate Coverage (vs USD)")

    fig.suptitle("Multi-Currency Infrastructure", y=1.02, fontsize=13)
    _save(fig, "figure7_currency_coverage")


# ── Figure 8: Download Pipeline Integrity ─────────────────────────────────────

def fig8_pipeline_integrity():
    """Comprehensive pipeline health: success rates and data flow."""
    con = get_conn()
    dl = con.execute("""
        SELECT data_type,
               SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN status='no_data' THEN 1 ELSE 0 END) AS no_data
        FROM meta_download_log
        WHERE data_type IN ('prices','splits','dividends')
        GROUP BY 1
    """).fetchdf()

    tables = con.execute("""
        SELECT 'Raw Prices' as layer, COUNT(*) as n FROM raw_price_daily
        UNION ALL SELECT 'Cleaned Prices', COUNT(*) FROM clean_price_daily
        UNION ALL SELECT 'Panel Panel', COUNT(*) FROM panel_monthly
        UNION ALL SELECT 'Splits', COUNT(*) FROM raw_split
        UNION ALL SELECT 'Dividends', COUNT(*) FROM raw_dividend
        UNION ALL SELECT 'FX Rates', COUNT(*) FROM raw_fx_daily
        UNION ALL SELECT 'Factor Returns', COUNT(*) FROM factor_return
        UNION ALL SELECT 'Quality Scores', COUNT(*) FROM meta_data_quality
    """).fetchdf()
    con.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: success rates as stacked horizontal bars
    dl["success_rate"] = dl["ok"] / (dl["ok"] + dl["failed"]) * 100
    x = range(len(dl))
    ax1.barh(dl["data_type"], dl["ok"], color=COLORS["positive"],
             label="OK", edgecolor="white")
    ax1.barh(dl["data_type"], dl["failed"], left=dl["ok"],
             color=COLORS["negative"], label="Failed", edgecolor="white")
    ax1.set_xlabel("Instruments")
    ax1.set_title("(a) Download Success Rates")
    ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
    ax1.legend(loc="lower right", framealpha=0.9)

    for i, row in dl.iterrows():
        ax1.text(row["ok"] + row["failed"] + 500, i,
                 f"{row['success_rate']:.1f}%", va="center",
                 fontsize=9, fontweight="bold", color=COLORS["positive"])

    # Right: data volume per table (log scale)
    tables = tables.sort_values("n")
    colors_list = [COLORS["main"] if "Raw" in l or "Cleaned" in l or "Panel" in l
                   else COLORS["accent"] for l in tables["layer"]]
    ax2.barh(tables["layer"], tables["n"], color=colors_list,
             edgecolor="white", linewidth=0.5)
    ax2.set_xscale("log")
    ax2.set_xlabel("Row count (log scale)")
    ax2.set_title("(b) Data Volume by Table")

    for i, (_, row) in enumerate(tables.iterrows()):
        label = f"{row['n']:,.0f}" if row["n"] < 1e6 else f"{row['n']/1e6:.1f}M"
        ax2.text(row["n"] * 1.3, i, label, va="center", fontsize=7)

    fig.suptitle("Pipeline Health and Data Volume", y=1.02, fontsize=13)
    _save(fig, "figure8_pipeline_integrity")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = datetime.now()
    print(f"Generating HyperDB figures...")
    print(f"  Database: {DB_PATH}")
    print(f"  Output:   {FIG_DIR}/")
    print()

    fig1_coverage_over_time()
    fig2_exchange_ranking()
    fig3_survivorship()
    fig4_data_depth()
    fig5_cross_section()
    fig6_return_distribution()
    fig7_currency_coverage()
    fig8_pipeline_integrity()

    elapsed = (datetime.now() - t0).total_seconds()
    n_figs = len(list(FIG_DIR.glob("*.pdf")))
    print(f"\nDone. {n_figs} figures generated in {elapsed:.0f}s.")


if __name__ == "__main__":
    main()
