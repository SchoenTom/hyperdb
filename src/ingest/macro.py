"""
HyperDataBank — Macro Indicator Downloader
───────────────────────────────────────────
Downloads macroeconomic indicators from EODHD's macro API.

Available indicators include:
    gdp_current_usd, gdp_per_capita_usd, real_gdp_growth,
    inflation_consumer_prices_annual, unemployment_total,
    population_total, real_interest_rate, current_account_balance,
    government_debt_to_gdp, trade_balance, and more.

Data is stored per country (ISO 3166-1 alpha-3) in bronze_macro_indicator.
"""

from tqdm import tqdm

from src.core.config import load_exchanges
from src.core.db import get_connection, init_schema
from src.core.log import get_logger
from src.ingest.client import EODHDClient

logger = get_logger("hyperdb.macro")

# ISO 3166-1 alpha-2 → alpha-3 mapping for countries in our exchange registry
COUNTRY_MAP = {
    "US": "USA", "GB": "GBR", "DE": "DEU", "FR": "FRA", "NL": "NLD",
    "CH": "CHE", "IT": "ITA", "ES": "ESP", "BE": "BEL", "PT": "PRT",
    "IE": "IRL", "AT": "AUT", "FI": "FIN", "DK": "DNK", "SE": "SWE",
    "NO": "NOR", "PL": "POL", "CZ": "CZE", "HU": "HUN", "GR": "GRC",
    "TR": "TUR", "RU": "RUS", "JP": "JPN", "HK": "HKG", "CN": "CHN",
    "KR": "KOR", "TW": "TWN", "IN": "IND", "SG": "SGP", "AU": "AUS",
    "NZ": "NZL", "CA": "CAN", "BR": "BRA", "MX": "MEX", "AR": "ARG",
    "CL": "CHL", "CO": "COL", "PE": "PER", "ZA": "ZAF", "IL": "ISR",
    "SA": "SAU", "AE": "ARE", "QA": "QAT", "KW": "KWT", "TH": "THA",
    "MY": "MYS", "ID": "IDN", "PH": "PHL", "VN": "VNM", "PK": "PAK",
    "BD": "BGD", "LK": "LKA", "EG": "EGY", "NG": "NGA", "KE": "KEN",
}

# Key macro indicators to download for each country
INDICATORS = [
    "gdp_current_usd",
    "gdp_per_capita_usd",
    "real_gdp_growth",
    "inflation_consumer_prices_annual",
    "unemployment_total",
    "population_total",
    "real_interest_rate",
    "current_account_balance",
    "government_debt_to_gdp",
    "trade_balance_pct_of_gdp",
    "broad_money_to_gdp",
    "tax_revenue_to_gdp",
    "life_expectancy",
    "central_government_debt",
    "foreign_direct_investment",
]


def download_macro(countries: list[str] | None = None) -> None:
    """Download macroeconomic indicators for specified countries.

    Args:
        countries: List of ISO alpha-2 country codes. None = all countries
                   from the exchange registry.
    """
    init_schema()
    conn = get_connection()
    client = EODHDClient()

    if countries is None:
        # Get all unique countries from exchange registry
        exchanges = load_exchanges()
        country_codes = set()
        for meta in exchanges.values():
            cc = meta.get("country")
            if cc and cc != "XX":
                country_codes.add(cc)
        countries = sorted(country_codes)

    logger.info("Downloading macro indicators for %d countries...",
                len(countries))

    total_records = 0

    for cc2 in tqdm(countries, desc="Macro data"):
        cc3 = COUNTRY_MAP.get(cc2, cc2)  # Try alpha-3, fall back to alpha-2

        for indicator in INDICATORS:
            data = client.get_macro_indicators(cc3, indicator=indicator)

            if data is None or len(data) == 0:
                continue

            for record in data:
                if not isinstance(record, dict):
                    continue
                date_val = record.get("Date") or record.get("date")
                value = record.get("Value") or record.get("value")
                period = record.get("Period") or record.get("period")

                if date_val is None or value is None:
                    continue

                try:
                    float_val = float(value)
                except (ValueError, TypeError):
                    continue

                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO bronze_macro_indicator
                            (country_iso2, indicator, date, period, value)
                        VALUES (?, ?, ?, ?, ?)
                    """, [cc2, indicator, date_val, period, float_val])
                    total_records += 1
                except Exception:
                    pass

    conn.close()
    logger.info("Macro download complete: %d records, %d API calls",
                total_records, client.request_count)
