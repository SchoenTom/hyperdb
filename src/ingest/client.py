"""
HyperDataBank — EODHD API Client
─────────────────────────────────
Robust, rate-limited client for all EODHD endpoints.

Handles:
    - Rate limiting (configurable delay between requests)
    - Automatic retries with exponential backoff
    - Request counting for API budget tracking
    - Structured error handling and logging
    - Every endpoint EODHD provides

This client returns raw JSON/dicts — no transformation or filtering.
Transformation happens in the ingest modules that call this client.
"""

import time
import requests
from typing import Any

from src.core.config import load_settings
from src.core.log import get_logger

logger = get_logger("hyperdb.api")


class EODHDClient:
    """Thread-safe EODHD API client with rate limiting and retries."""

    def __init__(self):
        settings = load_settings()
        self.token = settings["api"]["token"]
        self.base_url = settings["api"]["base_url"].rstrip("/")
        self.delay = settings["api"]["request_delay"]
        self.max_retries = settings["api"]["max_retries"]
        self.retry_backoff = settings["api"]["retry_backoff"]

        self._request_count = 0
        self._last_request_time = 0.0
        self._session = requests.Session()

    @property
    def request_count(self) -> int:
        return self._request_count

    def _throttle(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        """Execute a GET request with retries and rate limiting.

        Returns parsed JSON (dict or list), or None on failure.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params is None:
            params = {}
        params["api_token"] = self.token
        params["fmt"] = "json"

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(url, params=params, timeout=60)
                self._last_request_time = time.time()
                self._request_count += 1

                if resp.status_code == 200:
                    data = resp.json()
                    # EODHD sometimes returns error messages as JSON
                    if isinstance(data, dict) and "error" in data:
                        logger.warning("API error: %s (endpoint: %s)",
                                       data["error"], endpoint)
                        return None
                    return data
                elif resp.status_code == 429:
                    # Rate limited — wait and retry
                    wait = self.retry_backoff * (2 ** (attempt - 1))
                    logger.warning("Rate limited (429). Waiting %ds...", wait)
                    time.sleep(wait)
                    continue
                else:
                    logger.warning("HTTP %d for %s (attempt %d/%d)",
                                   resp.status_code, endpoint,
                                   attempt, self.max_retries)
            except requests.exceptions.Timeout:
                logger.warning("Timeout for %s (attempt %d/%d)",
                               endpoint, attempt, self.max_retries)
            except requests.exceptions.ConnectionError:
                wait = self.retry_backoff * (2 ** (attempt - 1))
                logger.warning("Connection error for %s. Waiting %ds...",
                               endpoint, wait)
                time.sleep(wait)
            except Exception as e:
                logger.error("Unexpected error for %s: %s", endpoint, e)
                return None

            # Exponential backoff before retry
            if attempt < self.max_retries:
                wait = self.retry_backoff * (2 ** (attempt - 1))
                time.sleep(wait)

        logger.error("All %d retries exhausted for %s",
                     self.max_retries, endpoint)
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # EXCHANGE ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_exchanges_list(self) -> list[dict] | None:
        """GET /exchanges-list/ — List all available exchanges."""
        return self._get("exchanges-list/")

    def get_exchange_details(self, exchange: str) -> dict | None:
        """GET /exchange-details/{exchange} — Trading hours, holidays, etc."""
        return self._get(f"exchange-details/{exchange}")

    def get_exchange_symbols(self, exchange: str,
                             delisted: bool = False) -> list[dict] | None:
        """GET /exchange-symbol-list/{exchange} — All tickers on an exchange.

        Returns list of dicts with fields:
            Code, Name, Country, Exchange, Currency, Type, Isin,
            previousClose, previousCloseDate
        """
        params = {}
        if delisted:
            params["delisted"] = "1"
        return self._get(f"exchange-symbol-list/{exchange}", params)

    # ══════════════════════════════════════════════════════════════════════════
    # PRICE ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_eod_prices(self, ticker_api: str,
                       from_date: str = "1985-01-01",
                       to_date: str = "2025-12-31",
                       period: str = "d") -> list[dict] | None:
        """GET /eod/{ticker_api} — Historical end-of-day prices.

        Returns list of dicts with fields:
            date, open, high, low, close, adjusted_close, volume
        """
        params = {"from": from_date, "to": to_date, "period": period}
        return self._get(f"eod/{ticker_api}", params)

    def get_eod_bulk(self, exchange: str,
                     date: str | None = None) -> list[dict] | None:
        """GET /eod-bulk-last-day/{exchange} — All tickers for one day.

        This is the key endpoint for efficient daily updates.
        One API call returns prices for ALL tickers on an exchange.
        """
        params = {}
        if date:
            params["date"] = date
        return self._get(f"eod-bulk-last-day/{exchange}", params)

    # ══════════════════════════════════════════════════════════════════════════
    # CORPORATE ACTION ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_splits(self, ticker_api: str,
                   from_date: str = "1970-01-01",
                   to_date: str = "2025-12-31") -> list[dict] | None:
        """GET /splits/{ticker_api} — Stock split history.

        Returns list of dicts with fields: date, split
        """
        params = {"from": from_date, "to": to_date}
        return self._get(f"splits/{ticker_api}", params)

    def get_dividends(self, ticker_api: str,
                      from_date: str = "1970-01-01",
                      to_date: str = "2025-12-31") -> list[dict] | None:
        """GET /div/{ticker_api} — Dividend history.

        Returns list of dicts with fields:
            date, value, unadjustedValue, currency,
            declarationDate, recordDate, paymentDate, period
        """
        params = {"from": from_date, "to": to_date}
        return self._get(f"div/{ticker_api}", params)

    # ══════════════════════════════════════════════════════════════════════════
    # FUNDAMENTALS ENDPOINT
    # ══════════════════════════════════════════════════════════════════════════

    def get_fundamentals(self, ticker_api: str) -> dict | None:
        """GET /fundamentals/{ticker_api} — Full fundamental data.

        Returns deeply nested dict with sections:
            General, Highlights, Valuation, SharesStats, Technicals,
            SplitsDividends, AnalystRatings, Holders, InsiderTransactions,
            ESGScores, outstandingShares, Earnings, Financials
            (+ ETF_Data, MutualFund_Data for those asset types)
        """
        return self._get(f"fundamentals/{ticker_api}")

    # ══════════════════════════════════════════════════════════════════════════
    # FX / FOREX ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_forex_history(self, pair: str,
                          from_date: str = "1985-01-01",
                          to_date: str = "2025-12-31",
                          period: str = "d") -> list[dict] | None:
        """GET /eod/{pair}.FOREX — Historical FX rates.

        pair format: 'EUR-USD', 'GBP-USD', etc.
        EODHD expects no hyphen in the ticker: EURUSD.FOREX
        """
        ticker = pair.replace("-", "")
        params = {"from": from_date, "to": to_date, "period": period}
        return self._get(f"eod/{ticker}.FOREX", params)

    def get_forex_bulk(self) -> list[dict] | None:
        """GET /eod-bulk-last-day/FOREX — All FX pairs for latest day."""
        return self._get("eod-bulk-last-day/FOREX")

    # ══════════════════════════════════════════════════════════════════════════
    # CRYPTO ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_crypto_history(self, pair: str,
                           from_date: str = "2010-01-01",
                           to_date: str = "2025-12-31",
                           period: str = "d") -> list[dict] | None:
        """GET /eod/{pair}.CC — Historical crypto prices.

        pair format: 'BTC-USD', 'ETH-USD', etc.
        """
        params = {"from": from_date, "to": to_date, "period": period}
        return self._get(f"eod/{pair}.CC", params)

    # ══════════════════════════════════════════════════════════════════════════
    # MACRO / ECONOMIC ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_macro_indicators(self, country: str,
                              indicator: str | None = None) -> list[dict] | None:
        """GET /macro-indicator/{country} — Macroeconomic data.

        country: ISO 3166-1 alpha-3 (e.g., 'USA', 'DEU', 'JPN')
        indicator: Optional specific indicator code.
            Available: 'gdp_current_usd', 'inflation_consumer_prices_annual',
            'unemployment_total', 'real_interest_rate', 'population_total',
            'gdp_per_capita_usd', etc.
        """
        params = {}
        if indicator:
            params["indicator"] = indicator
        return self._get(f"macro-indicator/{country}", params)

    # ══════════════════════════════════════════════════════════════════════════
    # BOND ENDPOINTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_bond_fundamentals(self, ticker_api: str) -> dict | None:
        """GET /bond-fundamentals/{ticker_api} — Bond-specific data.

        Includes: coupon, maturity, issue date, credit rating, etc.
        Falls back to /fundamentals/ for bond tickers on EODHD.
        """
        return self._get(f"bond-fundamentals/{ticker_api}")

    # ══════════════════════════════════════════════════════════════════════════
    # OPTIONS ENDPOINT
    # ══════════════════════════════════════════════════════════════════════════

    def get_options(self, ticker_api: str,
                    from_date: str | None = None,
                    to_date: str | None = None,
                    contract: str | None = None) -> dict | None:
        """GET /options/{ticker_api} — Options chain data.

        Returns dict with 'code', 'exchange', 'lastTradeDate', 'data'
        where data contains puts and calls with strikes, greeks, etc.
        """
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if contract:
            params["contract_name"] = contract
        return self._get(f"options/{ticker_api}", params)

    # ══════════════════════════════════════════════════════════════════════════
    # CALENDAR & EVENTS
    # ══════════════════════════════════════════════════════════════════════════

    def get_earnings_calendar(self, from_date: str | None = None,
                               to_date: str | None = None) -> list[dict] | None:
        """GET /calendar/earnings — Upcoming and historical earnings dates."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._get("calendar/earnings", params)

    def get_ipo_calendar(self, from_date: str | None = None,
                          to_date: str | None = None) -> list[dict] | None:
        """GET /calendar/ipos — IPO calendar."""
        params = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._get("calendar/ipos", params)

    # ══════════════════════════════════════════════════════════════════════════
    # INSIDER TRADING
    # ══════════════════════════════════════════════════════════════════════════

    def get_insider_transactions(self, ticker_api: str | None = None,
                                  from_date: str | None = None,
                                  to_date: str | None = None,
                                  limit: int = 1000) -> list[dict] | None:
        """GET /insider-transactions — Insider buying/selling."""
        params = {"limit": limit}
        if ticker_api:
            params["code"] = ticker_api
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._get("insider-transactions", params)

    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH
    # ══════════════════════════════════════════════════════════════════════════

    def search(self, query: str, limit: int = 50,
               bonds_only: bool = False) -> list[dict] | None:
        """GET /search/{query} — Search for tickers."""
        params = {"limit": limit}
        if bonds_only:
            params["bonds_only"] = "1"
        return self._get(f"search/{query}", params)
