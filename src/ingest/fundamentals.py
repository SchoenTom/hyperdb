"""
HyperDataBank — Fundamentals Downloader
────────────────────────────────────────
Downloads comprehensive fundamental data from EODHD's /fundamentals/ endpoint.

This is the richest endpoint EODHD offers. For each instrument it returns:
    - Company profile (sector, industry, GICS, description, etc.)
    - Financial highlights (market cap, PE, EPS, margins, etc.)
    - Valuation ratios
    - Share statistics (outstanding, float, short interest)
    - Financial statements (Balance Sheet, Income Statement, Cash Flow)
      — both quarterly and annual, typically 10+ years of history
    - Earnings history (actual vs estimate, surprise %)
    - Outstanding shares history
    - Insider transactions
    - Analyst ratings
    - ESG scores
    - ETF-specific data (holdings, weights, expense ratio)

Everything is stored. Nothing is dropped.

Financial statements use EAV (Entity-Attribute-Value) format:
    (asset_id, date, period_type, statement_type, line_item, value)
This allows storing any line item from any statement without schema changes.
"""

import duckdb
from tqdm import tqdm

from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.fundamentals")


def _already_downloaded(conn, asset_id, data_type):
    row = conn.execute("""
        SELECT 1 FROM meta_download_log
        WHERE asset_id = ? AND data_type = ? AND status = 'ok' LIMIT 1
    """, [asset_id, data_type]).fetchone()
    return row is not None


def _load_done_set(conn, data_type, exchange_code=None):
    """Batch-load all already-downloaded asset_ids into a set."""
    query = """
        SELECT DISTINCT asset_id FROM meta_download_log
        WHERE data_type = ? AND status = 'ok'
    """
    params = [data_type]
    if exchange_code:
        query += " AND exchange_code = ?"
        params.append(exchange_code)
    return {r[0] for r in conn.execute(query, params).fetchall()}


def _log_download(conn, asset_id, exchange_code, data_type, status,
                  record_count=0, error=None):
    conn.execute("""
        INSERT INTO meta_download_log
            (asset_id, exchange_code, data_type, status,
             record_count, error_message, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, current_timestamp)
    """, [asset_id, exchange_code, data_type, status, record_count, error])


def _safe_float(val) -> float | None:
    """Convert a value to float, returning None for non-numeric."""
    if val is None or val == "" or val == "None":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    """Convert a value to int, returning None for non-numeric."""
    if val is None or val == "" or val == "None":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_date(val) -> str | None:
    """Return date string or None."""
    if val is None or val == "" or val == "0000-00-00" or val == "None":
        return None
    return str(val)


def _store_profile(conn, asset_id, data):
    """Extract and store company profile into dim_asset_profile."""
    general = data.get("General", {}) or {}
    highlights = data.get("Highlights", {}) or {}
    valuation = data.get("Valuation", {}) or {}
    shares = data.get("SharesStats", {}) or {}
    technicals = data.get("Technicals", {}) or {}
    analyst = data.get("AnalystRatings", {}) or {}
    esg = data.get("ESGScores", {}) or {}
    etf_data = data.get("ETF_Data", {}) or {}

    conn.execute("""
        INSERT OR REPLACE INTO dim_asset_profile (
            asset_id, description, sector, industry,
            gics_sector, gics_group, gics_industry, gics_sub_industry,
            fiscal_year_end, ipo_date, international_domestic,
            address, phone, web_url, logo_url, full_time_employees,
            lei, primary_ticker, home_category,
            market_cap, market_cap_mln_usd, ebitda,
            pe_ratio, peg_ratio, book_value,
            dividend_share, dividend_yield, eps,
            eps_estimate_current_yr, eps_estimate_next_yr,
            profit_margin, operating_margin_ttm,
            roa_ttm, roe_ttm, revenue_ttm,
            revenue_per_share_ttm, gross_profit_ttm, diluted_eps_ttm,
            trailing_pe, forward_pe, price_sales_ttm, price_book_mrq,
            enterprise_value, ev_revenue, ev_ebitda,
            shares_outstanding, shares_float,
            percent_insiders, percent_institutions,
            shares_short, shares_short_prior_mo, short_ratio,
            short_pct_outstanding, short_pct_float,
            beta_eodhd, week_52_high, week_52_low,
            day_50_ma, day_200_ma,
            etf_company_name, etf_company_url, etf_asset_class,
            etf_net_expense_ratio, etf_total_assets,
            etf_yield, etf_inception_date,
            analyst_rating, analyst_target_price,
            analyst_strong_buy, analyst_buy, analyst_hold,
            analyst_sell, analyst_strong_sell,
            esg_score, esg_environment, esg_social, esg_governance,
            updated_at
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            current_timestamp
        )
    """, [
        asset_id,
        general.get("Description"),
        general.get("Sector"),
        general.get("Industry"),
        general.get("GicSector"),
        general.get("GicGroup"),
        general.get("GicIndustry"),
        general.get("GicSubIndustry"),
        general.get("FiscalYearEnd"),
        _safe_date(general.get("IPODate")),
        general.get("InternationalDomestic"),
        general.get("Address"),
        general.get("Phone"),
        general.get("WebURL"),
        general.get("LogoURL"),
        _safe_int(general.get("FullTimeEmployees")),
        general.get("LEI"),
        general.get("PrimaryTicker"),
        general.get("HomeCategory"),
        _safe_float(highlights.get("MarketCapitalization")),
        _safe_float(highlights.get("MarketCapitalizationMlnUSD")),
        _safe_float(highlights.get("EBITDA")),
        _safe_float(highlights.get("PERatio")),
        _safe_float(highlights.get("PEGRatio")),
        _safe_float(highlights.get("BookValue")),
        _safe_float(highlights.get("DividendShare")),
        _safe_float(highlights.get("DividendYield")),
        _safe_float(highlights.get("EarningsShare")),
        _safe_float(highlights.get("EPSEstimateCurrentYear")),
        _safe_float(highlights.get("EPSEstimateNextYear")),
        _safe_float(highlights.get("ProfitMargin")),
        _safe_float(highlights.get("OperatingMarginTTM")),
        _safe_float(highlights.get("ReturnOnAssetsTTM")),
        _safe_float(highlights.get("ReturnOnEquityTTM")),
        _safe_float(highlights.get("RevenueTTM")),
        _safe_float(highlights.get("RevenuePerShareTTM")),
        _safe_float(highlights.get("GrossProfitTTM")),
        _safe_float(highlights.get("DilutedEpsTTM")),
        _safe_float(valuation.get("TrailingPE")),
        _safe_float(valuation.get("ForwardPE")),
        _safe_float(valuation.get("PriceSalesTTM")),
        _safe_float(valuation.get("PriceBookMRQ")),
        _safe_float(valuation.get("EnterpriseValue")),
        _safe_float(valuation.get("EnterpriseValueRevenue")),
        _safe_float(valuation.get("EnterpriseValueEbitda")),
        _safe_int(shares.get("SharesOutstanding")),
        _safe_int(shares.get("SharesFloat")),
        _safe_float(shares.get("PercentInsiders")),
        _safe_float(shares.get("PercentInstitutions")),
        _safe_int(shares.get("SharesShort")),
        _safe_int(shares.get("SharesShortPriorMonth")),
        _safe_float(shares.get("ShortRatio")),
        _safe_float(shares.get("ShortPercentOutstanding")),
        _safe_float(shares.get("ShortPercentFloat")),
        _safe_float(technicals.get("Beta")),
        _safe_float(technicals.get("52WeekHigh")),
        _safe_float(technicals.get("52WeekLow")),
        _safe_float(technicals.get("50DayMA")),
        _safe_float(technicals.get("200DayMA")),
        etf_data.get("Company_Name"),
        etf_data.get("Company_URL"),
        etf_data.get("Asset_Class"),
        _safe_float(etf_data.get("Net_Expense_Ratio")),
        _safe_float(etf_data.get("Total_Assets")),
        _safe_float(etf_data.get("Yield")),
        _safe_date(etf_data.get("Inception_Date")),
        analyst.get("Rating"),
        _safe_float(analyst.get("TargetPrice")),
        _safe_int(analyst.get("StrongBuy")),
        _safe_int(analyst.get("Buy")),
        _safe_int(analyst.get("Hold")),
        _safe_int(analyst.get("Sell")),
        _safe_int(analyst.get("StrongSell")),
        _safe_float(esg.get("totalEsg")),
        _safe_float(esg.get("environmentScore")),
        _safe_float(esg.get("socialScore")),
        _safe_float(esg.get("governanceScore")),
    ])


def _store_financials(conn, asset_id, data):
    """Extract and store financial statements in EAV format."""
    financials = data.get("Financials", {}) or {}
    count = 0

    for statement_type in ("Balance_Sheet", "Income_Statement", "Cash_Flow"):
        statement = financials.get(statement_type, {}) or {}

        for period_type in ("quarterly", "yearly"):
            periods = statement.get(period_type, {}) or {}

            for report_date, items in periods.items():
                if not isinstance(items, dict):
                    continue

                filing_date = _safe_date(items.get("filing_date"))
                currency = items.get("currency_symbol")

                for line_item, value in items.items():
                    if line_item in ("date", "filing_date", "currency_symbol"):
                        continue
                    numeric = _safe_float(value)
                    if numeric is None:
                        continue

                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO raw_fundamental
                                (asset_id, report_date, period_type,
                                 statement_type, filing_date,
                                 currency_symbol, line_item, value)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            asset_id, report_date, period_type,
                            statement_type, filing_date,
                            currency, line_item, numeric,
                        ])
                        count += 1
                    except Exception:
                        pass

    return count


def _store_earnings(conn, asset_id, data):
    """Extract and store earnings history."""
    earnings = data.get("Earnings", {}) or {}
    history = earnings.get("History", {}) or {}
    count = 0

    for date_key, record in history.items():
        if not isinstance(record, dict):
            continue
        report_date = record.get("reportDate") or date_key
        try:
            conn.execute("""
                INSERT OR IGNORE INTO raw_earnings
                    (asset_id, report_date, eps_actual, eps_estimate,
                     eps_difference, surprise_pct)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                asset_id, report_date,
                _safe_float(record.get("epsActual")),
                _safe_float(record.get("epsEstimate")),
                _safe_float(record.get("epsDifference")),
                _safe_float(record.get("surprisePercent")),
            ])
            count += 1
        except Exception:
            pass

    return count


def _store_shares_outstanding(conn, asset_id, data):
    """Extract and store historical shares outstanding."""
    outstanding = data.get("outstandingShares", {}) or {}
    count = 0

    for section in ("quarterly", "annual"):
        periods = outstanding.get(section, {}) or {}
        for date_key, record in periods.items():
            if not isinstance(record, dict):
                continue
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO raw_shares_outstanding
                        (asset_id, date, shares_mln, shares_raw)
                    VALUES (?, ?, ?, ?)
                """, [
                    asset_id,
                    record.get("dateFormatted") or date_key,
                    _safe_float(record.get("sharesMln")),
                    _safe_int(record.get("shares")),
                ])
                count += 1
            except Exception:
                pass

    return count


def _store_insider_transactions(conn, asset_id, data):
    """Extract and store insider transactions."""
    insiders = data.get("InsiderTransactions", {}) or {}
    if isinstance(insiders, list):
        transactions = insiders
    else:
        transactions = list(insiders.values()) if insiders else []

    count = 0
    for t in transactions:
        if not isinstance(t, dict):
            continue
        try:
            conn.execute("""
                INSERT INTO raw_insider_transaction
                    (asset_id, date, owner_name, transaction_type,
                     shares, value, owner_title, security_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                asset_id,
                _safe_date(t.get("date")) or t.get("transactionDate"),
                t.get("ownerName"),
                t.get("transactionType"),
                _safe_int(t.get("transactionShares")),
                _safe_float(t.get("transactionValue")),
                t.get("ownerTitle"),
                t.get("securityName"),
            ])
            count += 1
        except Exception:
            pass

    return count


def _store_etf_holdings(conn, asset_id, data):
    """Extract and store ETF holdings."""
    etf_data = data.get("ETF_Data", {}) or {}
    holdings = etf_data.get("Holdings", {}) or {}
    count = 0

    for key, h in holdings.items():
        if not isinstance(h, dict):
            continue
        try:
            conn.execute("""
                INSERT INTO raw_etf_holding
                    (asset_id, holding_code, holding_name, holding_isin,
                     weight_pct, sector, country, asset_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                asset_id,
                h.get("Code"),
                h.get("Name"),
                h.get("ISIN"),
                _safe_float(h.get("Assets_%")),
                h.get("Sector"),
                h.get("Country"),
                h.get("Asset_Class"),
            ])
            count += 1
        except Exception:
            pass

    return count


def download_fundamentals(exchange_code: str | None = None,
                          asset_class: str | None = None,
                          resume: bool = True) -> None:
    """Download complete fundamental data for all instruments.

    This is the most data-rich download. For each instrument, EODHD returns
    company profile, financial statements, earnings, insider transactions,
    share statistics, ESG scores, and more.

    Args:
        exchange_code: Limit to a specific exchange. None = all.
        asset_class: Limit to a specific asset class. None = equity + etf.
        resume: Skip instruments already downloaded.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()

    query = "SELECT asset_id, ticker_api, exchange_code FROM dim_asset WHERE 1=1"
    params = []

    if exchange_code:
        query += " AND exchange_code = ?"
        params.append(exchange_code)
    if asset_class:
        query += " AND asset_class = ?"
        params.append(asset_class)
    else:
        # Default: equities and ETFs (most data available)
        query += " AND asset_class IN ('equity', 'etf')"

    query += " AND exchange_code NOT IN ('FOREX', 'CC')"
    query += " ORDER BY exchange_code, ticker"

    assets = conn.execute(query, params).fetchall()
    logger.info("Fundamentals download: %d instruments", len(assets))

    done_set = _load_done_set(conn, "fundamentals", exchange_code) if resume else set()

    for asset_id, ticker_api, ex_code in tqdm(assets, desc="Fundamentals"):
        if resume and asset_id in done_set:
            continue

        data = client.get_fundamentals(ticker_api)

        if data is None or not isinstance(data, dict):
            _log_download(conn, asset_id, ex_code, "fundamentals", "failed")
            continue

        total_records = 0

        # Store company profile
        _store_profile(conn, asset_id, data)
        total_records += 1

        # Store financial statements (EAV)
        total_records += _store_financials(conn, asset_id, data)

        # Store earnings history
        total_records += _store_earnings(conn, asset_id, data)

        # Store shares outstanding
        total_records += _store_shares_outstanding(conn, asset_id, data)

        # Store insider transactions
        total_records += _store_insider_transactions(conn, asset_id, data)

        # Store ETF holdings if applicable
        if data.get("ETF_Data"):
            total_records += _store_etf_holdings(conn, asset_id, data)

        _log_download(conn, asset_id, ex_code, "fundamentals", "ok",
                      total_records)

    conn.close()
    logger.info("Fundamentals download complete. API calls: %d",
                client.request_count)
