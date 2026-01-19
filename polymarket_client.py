"""Polymarket API client for fetching market data."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import config

logger = logging.getLogger(__name__)


@dataclass
class Market:
    """Represents a Polymarket market."""

    id: str
    question: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[float]
    volume: float
    volume_24h: float
    liquidity: float
    end_date: Optional[datetime]
    active: bool
    closed: bool
    tags: list[str]
    image: Optional[str]

    @property
    def url(self) -> str:
        """Get the Polymarket URL for this market."""
        return f"https://polymarket.com/event/{self.slug}"

    @property
    def formatted_prices(self) -> str:
        """Format outcome prices as percentages."""
        if not self.outcomes or not self.outcome_prices:
            return "N/A"
        return " | ".join(
            f"{outcome}: {price*100:.1f}%"
            for outcome, price in zip(self.outcomes, self.outcome_prices)
        )

    def price_for_outcome(self, outcome: str) -> Optional[float]:
        """Get the price for a specific outcome."""
        try:
            idx = self.outcomes.index(outcome)
            return self.outcome_prices[idx]
        except (ValueError, IndexError):
            return None


@dataclass
class Event:
    """Represents a Polymarket event (can contain multiple markets)."""

    id: str
    title: str
    slug: str
    description: str
    markets: list[Market]
    volume: float
    liquidity: float
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    active: bool
    closed: bool
    tags: list[str]
    image: Optional[str]

    @property
    def url(self) -> str:
        """Get the Polymarket URL for this event."""
        return f"https://polymarket.com/event/{self.slug}"


class PolymarketClient:
    """Async client for the Polymarket Gamma API."""

    def __init__(self):
        self.base_url = config.gamma_api_base_url
        self.clob_url = config.clob_api_base_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError)),
        reraise=True,
    )
    async def _request(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """Make a request to the Gamma API with retry logic."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        try:
            async with session.get(url, params=params, timeout=30) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            logger.error(f"API error for {url}: {e.status} - {e.message}")
            raise
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            raise

    def _parse_market(self, data: dict) -> Market:
        """Parse market data from API response."""
        outcomes_raw = data.get("outcomes", [])
        outcomes = []
        try:
            if isinstance(outcomes_raw, str):
                # Handle JSON string format like '["Yes", "No"]'
                import json
                try:
                    parsed = json.loads(outcomes_raw)
                    if isinstance(parsed, list):
                        outcomes = [str(o) for o in parsed]
                    else:
                        outcomes = outcomes_raw.split(",") if outcomes_raw else []
                except json.JSONDecodeError:
                    outcomes = outcomes_raw.split(",") if outcomes_raw else []
            elif isinstance(outcomes_raw, list):
                outcomes = [str(o) for o in outcomes_raw]
        except (ValueError, TypeError):
            outcomes = []

        outcome_prices_raw = data.get("outcomePrices", [])
        outcome_prices = []
        try:
            if isinstance(outcome_prices_raw, str):
                # Handle JSON string format like '["0.5", "0.5"]'
                import json
                try:
                    parsed = json.loads(outcome_prices_raw)
                    if isinstance(parsed, list):
                        outcome_prices = [float(p) for p in parsed]
                    else:
                        outcome_prices = [float(p) for p in outcome_prices_raw.split(",") if p]
                except json.JSONDecodeError:
                    outcome_prices = [float(p) for p in outcome_prices_raw.split(",") if p]
            elif isinstance(outcome_prices_raw, list):
                outcome_prices = [float(p) for p in outcome_prices_raw]
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse outcome prices: {outcome_prices_raw} - {e}")
            outcome_prices = []

        end_date = None
        if data.get("endDate"):
            try:
                end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            volume=float(data.get("volume", 0) or 0),
            volume_24h=float(data.get("volume24hr", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            end_date=end_date,
            active=data.get("active", False),
            closed=data.get("closed", False),
            tags=data.get("tags", []) or [],
            image=data.get("image"),
        )

    def _parse_event(self, data: dict) -> Event:
        """Parse event data from API response."""
        markets = [self._parse_market(m) for m in data.get("markets", [])]

        start_date = None
        if data.get("startDate"):
            try:
                start_date = datetime.fromisoformat(data["startDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        end_date = None
        if data.get("endDate"):
            try:
                end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Event(
            id=data.get("id", ""),
            title=data.get("title", ""),
            slug=data.get("slug", ""),
            description=data.get("description", ""),
            markets=markets,
            volume=float(data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            start_date=start_date,
            end_date=end_date,
            active=data.get("active", False),
            closed=data.get("closed", False),
            tags=data.get("tags", []) or [],
            image=data.get("image"),
        )

    async def get_active_events(
        self,
        limit: int = 50,
        offset: int = 0,
        tags: Optional[list[str]] = None,
    ) -> list[Event]:
        """Fetch active events from the Gamma API."""
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }

        if tags:
            params["tag"] = ",".join(tags)

        try:
            data = await self._request("/events", params)
            if isinstance(data, list):
                return [self._parse_event(e) for e in data]
            return []
        except Exception as e:
            logger.error(f"Failed to fetch active events: {e}")
            return []

    async def get_active_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        tags: Optional[list[str]] = None,
    ) -> list[Market]:
        """Fetch active markets from the Gamma API."""
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }

        if tags:
            params["tag"] = ",".join(tags)

        try:
            data = await self._request("/markets", params)
            if isinstance(data, list):
                return [self._parse_market(m) for m in data]
            return []
        except Exception as e:
            logger.error(f"Failed to fetch active markets: {e}")
            return []

    async def get_all_active_markets(self, batch_size: int = 500) -> list[Market]:
        """Fetch ALL active markets from the Gamma API (paginated).

        Warning: This can return 20k+ markets. Use with caution.
        """
        all_markets = []
        offset = 0

        logger.info("Starting full market scan...")

        while True:
            params = {
                "active": "true",
                "closed": "false",
                "limit": batch_size,
                "offset": offset,
            }

            try:
                data = await self._request("/markets", params)
                if not data or not isinstance(data, list):
                    break

                markets = [self._parse_market(m) for m in data]
                all_markets.extend(markets)

                logger.info(f"Fetched {len(data)} markets (total: {len(all_markets)})")

                if len(data) < batch_size:
                    break

                offset += batch_size

            except Exception as e:
                logger.error(f"Error fetching markets at offset {offset}: {e}")
                break

        logger.info(f"Full scan complete: {len(all_markets)} total markets")
        return all_markets

    async def get_market_by_slug(self, slug: str) -> Optional[Market]:
        """Fetch a specific market by its slug."""
        params = {"slug": slug}

        try:
            data = await self._request("/markets", params)
            if isinstance(data, list) and data:
                return self._parse_market(data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to fetch market {slug}: {e}")
            return None

    async def get_event_by_slug(self, slug: str) -> Optional[Event]:
        """Fetch a specific event by its slug."""
        params = {"slug": slug}

        try:
            data = await self._request("/events", params)
            if isinstance(data, list) and data:
                return self._parse_event(data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to fetch event {slug}: {e}")
            return None

    async def search_markets(self, query: str, limit: int = 20) -> list[Market]:
        """Search for markets by keyword."""
        params = {
            "q": query,
            "limit": limit,
            "active": "true",
            "closed": "false",
        }

        try:
            data = await self._request("/markets", params)
            if isinstance(data, list):
                return [self._parse_market(m) for m in data]
            return []
        except Exception as e:
            logger.error(f"Failed to search markets for '{query}': {e}")
            return []

    async def get_top_markets_by_volume(self, limit: int = 10) -> list[Market]:
        """Get top markets by 24h volume."""
        return await self.get_active_markets(limit=limit)

    async def get_trending_events(self, limit: int = 10) -> list[Event]:
        """Get trending events by volume."""
        return await self.get_active_events(limit=limit)
