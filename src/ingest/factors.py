"""
HyperDataBank — Factor Model Downloader
────────────────────────────────────────
Downloads risk factor returns from academic sources:

    1. Fama-French 3-Factor (daily & monthly) — US, Europe, Japan,
       Asia-Pacific, Global, Emerging
    2. Fama-French 5-Factor (monthly) — same regions
    3. Q-Factor model (monthly) — US
    4. TED Spread (monthly) — from FRED

All factor data is stored in factor_return with a uniform schema:
    (date, frequency, region, model, factor_name, value)

This allows queries like:
    SELECT * FROM factor_return
    WHERE region = 'Europe' AND model = 'FF5' AND frequency = 'monthly'
"""

import io
import zipfile
import requests
import numpy as np
import pandas as pd

from src.core.config import load_settings
from src.core.db import get_connection, init_schema
from src.core.log import get_logger

logger = get_logger("hyperdb.factors")

# Kenneth French Data Library — factor file mappings
# Each entry: (zip_filename, region, model, frequency, has_annual_section)
FF_FILES = [
    # US — 3-Factor
    ("F-F_Research_Data_Factors_daily_CSV.zip",
     "US", "FF3", "daily"),
    ("F-F_Research_Data_Factors_CSV.zip",
     "US", "FF3", "monthly"),
    # US — 5-Factor
    ("F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
     "US", "FF5", "daily"),
    ("F-F_Research_Data_5_Factors_2x3_CSV.zip",
     "US", "FF5", "monthly"),
    # US — Momentum
    ("F-F_Momentum_Factor_daily_CSV.zip",
     "US", "Carhart", "daily"),
    ("F-F_Momentum_Factor_CSV.zip",
     "US", "Carhart", "monthly"),
    # Europe — 3-Factor & 5-Factor
    ("Europe_3_Factors_Daily_CSV.zip",
     "Europe", "FF3", "daily"),
    ("Europe_3_Factors_CSV.zip",
     "Europe", "FF3", "monthly"),
    ("Europe_5_Factors_Daily_CSV.zip",
     "Europe", "FF5", "daily"),
    ("Europe_5_Factors_CSV.zip",
     "Europe", "FF5", "monthly"),
    # Japan
    ("Japan_3_Factors_Daily_CSV.zip",
     "Japan", "FF3", "daily"),
    ("Japan_3_Factors_CSV.zip",
     "Japan", "FF3", "monthly"),
    ("Japan_5_Factors_Daily_CSV.zip",
     "Japan", "FF5", "daily"),
    ("Japan_5_Factors_CSV.zip",
     "Japan", "FF5", "monthly"),
    # Asia-Pacific ex Japan
    ("Asia_Pacific_ex_Japan_3_Factors_Daily_CSV.zip",
     "Asia-Pacific", "FF3", "daily"),
    ("Asia_Pacific_ex_Japan_3_Factors_CSV.zip",
     "Asia-Pacific", "FF3", "monthly"),
    ("Asia_Pacific_ex_Japan_5_Factors_Daily_CSV.zip",
     "Asia-Pacific", "FF5", "daily"),
    ("Asia_Pacific_ex_Japan_5_Factors_CSV.zip",
     "Asia-Pacific", "FF5", "monthly"),
    # Global
    ("Global_3_Factors_Daily_CSV.zip",
     "Global", "FF3", "daily"),
    ("Global_3_Factors_CSV.zip",
     "Global", "FF3", "monthly"),
    ("Global_5_Factors_Daily_CSV.zip",
     "Global", "FF5", "daily"),
    ("Global_5_Factors_CSV.zip",
     "Global", "FF5", "monthly"),
    # Global ex US
    ("Global_ex_US_3_Factors_Daily_CSV.zip",
     "Global_ex_US", "FF3", "daily"),
    ("Global_ex_US_3_Factors_CSV.zip",
     "Global_ex_US", "FF3", "monthly"),
    ("Global_ex_US_5_Factors_Daily_CSV.zip",
     "Global_ex_US", "FF5", "daily"),
    ("Global_ex_US_5_Factors_CSV.zip",
     "Global_ex_US", "FF5", "monthly"),
    # Emerging
    ("Emerging_5_Factors_CSV.zip",
     "Emerging", "FF5", "monthly"),
    ("Emerging_5_Factors_Daily_CSV.zip",
     "Emerging", "FF5", "daily"),
]


def _download_zip_csv(url: str) -> str | None:
    """Download a ZIP file and extract the CSV content as string."""
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200:
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".CSV")
                         or n.endswith(".csv")]
            if not csv_names:
                logger.warning("No CSV found in %s", url)
                return None
            return zf.read(csv_names[0]).decode("utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to download %s: %s", url, e)
        return None


def _parse_ff_csv(csv_text: str, frequency: str) -> pd.DataFrame:
    """Parse a Fama-French CSV file into a clean DataFrame.

    The FF CSV format has a header section, then data rows, then sometimes
    an annual section. We parse only the main data section.
    """
    lines = csv_text.strip().split("\n")

    # Find the start of data (first line that starts with a digit)
    data_start = None
    header_line = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[0].isdigit():
            data_start = i
            # Header is the line before data starts
            header_line = i - 1
            break

    if data_start is None:
        return pd.DataFrame()

    # Parse header
    header = lines[header_line].strip().split(",")
    header = [h.strip() for h in header]

    # Parse data rows until we hit a non-data line
    data_rows = []
    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line or not line[0].isdigit():
            break
        parts = line.split(",")
        if len(parts) < 2:
            continue
        data_rows.append([p.strip() for p in parts])

    if not data_rows:
        return pd.DataFrame()

    df = pd.DataFrame(data_rows)

    # Name columns
    if frequency == "daily":
        col_names = ["date"] + [f"col_{i}" for i in range(1, df.shape[1])]
    else:
        col_names = ["month"] + [f"col_{i}" for i in range(1, df.shape[1])]
    df.columns = col_names[:df.shape[1]]

    # Standard FF factor names based on column count
    factor_names = {
        4: ["mkt_rf", "smb", "hml", "rf"],           # FF3
        6: ["mkt_rf", "smb", "hml", "rmw", "cma", "rf"],  # FF5
        1: ["umd"],                                    # Momentum
        2: ["umd", "rf"],                              # Momentum with RF
    }

    n_value_cols = df.shape[1] - 1
    if n_value_cols in factor_names:
        names = factor_names[n_value_cols]
        for i, name in enumerate(names):
            if i + 1 < df.shape[1]:
                df.rename(columns={f"col_{i+1}": name}, inplace=True)
    else:
        # Use header names if available
        for i in range(1, min(len(header), df.shape[1])):
            clean_name = header[i].strip().replace("-", "_").replace(" ", "_").lower()
            df.rename(columns={f"col_{i}": clean_name}, inplace=True)

    # Parse date/month
    if frequency == "daily":
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"])
    else:
        df["date"] = pd.to_datetime(df["month"], format="%Y%m", errors="coerce")
        df = df.dropna(subset=["date"])
        df.drop(columns=["month"], inplace=True, errors="ignore")

    # Convert value columns to float and divide by 100 (percentage → decimal)
    value_cols = [c for c in df.columns if c != "date"]
    for col in value_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

    return df


def download_ff_factors() -> None:
    """Download all Fama-French factor files and store in factor_return."""
    init_schema()
    conn = get_connection()
    settings = load_settings()
    base_url = settings["factors"]["ff_base_url"]

    logger.info("Downloading Fama-French factors (%d files)...", len(FF_FILES))

    for zip_name, region, model, frequency in FF_FILES:
        url = f"{base_url}/{zip_name}"
        logger.info("  %s (%s, %s, %s)", zip_name, region, model, frequency)

        csv_text = _download_zip_csv(url)
        if csv_text is None:
            logger.warning("  Skipping %s — download failed", zip_name)
            continue

        df = _parse_ff_csv(csv_text, frequency)
        if df.empty:
            logger.warning("  Skipping %s — no data parsed", zip_name)
            continue

        # Melt to long format and insert into factor_return
        value_cols = [c for c in df.columns if c != "date"]
        count = 0
        for _, row in df.iterrows():
            for factor_name in value_cols:
                val = row[factor_name]
                if pd.isna(val):
                    continue
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO factor_return
                            (date, frequency, region, model,
                             factor_name, value)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [
                        row["date"].strftime("%Y-%m-%d"),
                        frequency, region, model, factor_name, float(val),
                    ])
                    count += 1
                except Exception:
                    pass

        logger.info("  Stored %d factor-date observations", count)

    conn.close()
    logger.info("Fama-French download complete.")


def download_q_factors() -> None:
    """Download Q-factor model data from global-q.org."""
    init_schema()
    conn = get_connection()
    settings = load_settings()

    url = settings["factors"]["q_factor_url"]
    logger.info("Downloading Q-factors from %s", url)

    try:
        df = pd.read_csv(url)
    except Exception as e:
        logger.error("Failed to download Q-factors: %s", e)
        conn.close()
        return

    # Identify columns
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip()
        if "year" in cl:
            col_map["year"] = col
        elif cl in ("month",):
            col_map["month_num"] = col
        elif "mkt" in cl or "market" in cl:
            col_map["q_mkt"] = col
        elif cl in ("r_me", "me"):
            col_map["q_me"] = col
        elif cl in ("r_ia", "ia"):
            col_map["q_ia"] = col
        elif cl in ("r_roe", "roe"):
            col_map["q_roe"] = col
        elif cl in ("r_eg", "eg"):
            col_map["q_eg"] = col

    if "year" not in col_map or "month_num" not in col_map:
        logger.error("Cannot parse Q-factor CSV columns: %s", list(df.columns))
        conn.close()
        return

    # Build date column
    df["date"] = pd.to_datetime(
        df[col_map["year"]].astype(str) + "-" +
        df[col_map["month_num"]].astype(str).str.zfill(2) + "-01"
    )

    # Identify factor columns
    factor_cols = {v: k for k, v in col_map.items()
                   if k not in ("year", "month_num")}

    count = 0
    for _, row in df.iterrows():
        for orig_col, factor_name in factor_cols.items():
            val = row[orig_col]
            if pd.isna(val):
                continue
            # Convert from percentage if needed
            fval = float(val)
            if abs(fval) > 1 and factor_name != "q_eg":
                fval = fval / 100.0
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO factor_return
                        (date, frequency, region, model,
                         factor_name, value)
                    VALUES (?, 'monthly', 'US', 'Q', ?, ?)
                """, [row["date"].strftime("%Y-%m-%d"), factor_name, fval])
                count += 1
            except Exception:
                pass

    conn.close()
    logger.info("Q-factors: stored %d observations", count)


def download_ted_spread() -> None:
    """Download TED spread from FRED."""
    init_schema()
    conn = get_connection()
    settings = load_settings()

    base = settings["factors"]["fred_base_url"]
    url = (f"{base}?bg=2000&fg=000&fgsnd=2000&id=TEDRATE"
           f"&cosd=1986-01-02&coed=2025-12-31&vintage_date="
           f"&revision_date=&nd=1986-01-02&ost=-99999&oet=99999"
           f"&lsv=&lev=&mma=0&fml=a&fq=Monthly&fam=avg"
           f"&transformation=lin&line_color=%230073e6"
           f"&line_style=Solid&lw=2&mark_type=NONE&mw=2"
           f"&width=1168&height=450&stacking=&range=&mode=fred")

    logger.info("Downloading TED spread from FRED...")

    try:
        df = pd.read_csv(url)
    except Exception as e:
        logger.error("Failed to download TED spread: %s", e)
        conn.close()
        return

    if "DATE" in df.columns:
        df.rename(columns={"DATE": "date", "TEDRATE": "ted"}, inplace=True)
    else:
        logger.error("Unexpected columns in TED data: %s", list(df.columns))
        conn.close()
        return

    df["date"] = pd.to_datetime(df["date"])
    df["ted"] = pd.to_numeric(df["ted"], errors="coerce")
    df = df.dropna(subset=["ted"])

    # Store as factor
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute("""
                INSERT OR IGNORE INTO factor_return
                    (date, frequency, region, model,
                     factor_name, value)
                VALUES (?, 'monthly', 'US', 'Spread', 'ted', ?)
            """, [row["date"].strftime("%Y-%m-%d"), float(row["ted"])])
            count += 1
        except Exception:
            pass

    conn.close()
    logger.info("TED spread: stored %d monthly observations", count)


def download_all_factors() -> None:
    """Download all factor models (Fama-French, Q-factors, TED spread)."""
    download_ff_factors()
    download_q_factors()
    download_ted_spread()
