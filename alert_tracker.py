"""Alert tracking and detection for Polymarket markets."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from polymarket_client import Market, Event

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alerts that can be triggered."""

    NEW_MARKET = "new_market"
    PRICE_CHANGE = "price_change"
    HIGH_VOLUME = "high_volume"
    MARKET_CLOSING_SOON = "closing_soon"
    TRENDING = "trending"


@dataclass
class Alert:
    """Represents an alert to be sent."""

    alert_type: AlertType
    market: Market
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    def format_telegram_message(self) -> str:
        """Format the alert as a Telegram message."""
        emoji_map = {
            AlertType.NEW_MARKET: "🆕",
            AlertType.PRICE_CHANGE: "📊",
            AlertType.HIGH_VOLUME: "🔥",
            AlertType.MARKET_CLOSING_SOON: "⏰",
            AlertType.TRENDING: "📈",
        }

        emoji = emoji_map.get(self.alert_type, "ℹ️")

        lines = [
            f"{emoji} <b>{self.alert_type.value.replace('_', ' ').title()}</b>",
            "",
            f"<b>{self.market.question}</b>",
            "",
            f"💹 {self.market.formatted_prices}",
            f"💰 Volume 24h: ${self.market.volume_24h:,.0f}",
            f"💧 Liquidity: ${self.market.liquidity:,.0f}",
        ]

        if self.metadata.get("price_change"):
            change = self.metadata["price_change"]
            direction = "📈" if change > 0 else "📉"
            lines.append(f"{direction} Change: {change:+.1%}")

        if self.metadata.get("previous_price") is not None:
            lines.append(f"Previous: {self.metadata['previous_price']*100:.1f}%")

        lines.extend([
            "",
            f"🔗 <a href=\"{self.market.url}\">View on Polymarket</a>",
        ])

        return "\n".join(lines)


class AlertTracker:
    """Tracks market state and detects alertable changes."""

    def __init__(
        self,
        volume_threshold: float = 10000,
        price_change_threshold: float = 0.10,
    ):
        self.volume_threshold = volume_threshold
        self.price_change_threshold = price_change_threshold

        # Track known markets and their last known state
        self._known_markets: dict[str, dict] = {}
        self._alerted_markets: set[str] = set()  # Markets we've already alerted for
        self._initialized: bool = False  # First run flag - don't alert on initial load

    def _get_market_state(self, market: Market) -> dict:
        """Get the current state of a market for comparison."""
        return {
            "prices": dict(zip(market.outcomes, market.outcome_prices)),
            "volume_24h": market.volume_24h,
            "liquidity": market.liquidity,
            "last_seen": datetime.utcnow(),
        }

    def check_market(self, market: Market) -> list[Alert]:
        """Check a market for alertable conditions."""
        alerts = []
        market_id = market.id

        # Get previous state if any
        previous_state = self._known_markets.get(market_id)

        # Check for new market
        if previous_state is None:
            # On first run, just learn markets without alerting
            if not self._initialized:
                pass  # Just learn, don't alert
            # Only alert for new markets with significant volume AFTER initial load
            elif market.volume_24h >= self.volume_threshold:
                alert_key = f"new_{market_id}"
                if alert_key not in self._alerted_markets:
                    alerts.append(Alert(
                        alert_type=AlertType.NEW_MARKET,
                        market=market,
                        message=f"New market detected with high volume",
                    ))
                    self._alerted_markets.add(alert_key)
        else:
            # Check for significant price changes
            for outcome, current_price in zip(market.outcomes, market.outcome_prices):
                previous_price = previous_state["prices"].get(outcome)
                if previous_price is not None and previous_price > 0:
                    price_change = current_price - previous_price

                    if abs(price_change) >= self.price_change_threshold:
                        alert_key = f"price_{market_id}_{outcome}_{datetime.utcnow().strftime('%Y%m%d%H')}"
                        if alert_key not in self._alerted_markets:
                            alerts.append(Alert(
                                alert_type=AlertType.PRICE_CHANGE,
                                market=market,
                                message=f"Significant price movement for {outcome}",
                                metadata={
                                    "outcome": outcome,
                                    "price_change": price_change,
                                    "previous_price": previous_price,
                                    "current_price": current_price,
                                },
                            ))
                            self._alerted_markets.add(alert_key)
                            break  # One alert per market per check

            # Check for volume spike
            prev_volume = previous_state["volume_24h"]
            if prev_volume > 0:
                volume_increase = (market.volume_24h - prev_volume) / prev_volume
                if volume_increase > 0.5:  # 50% volume increase
                    alert_key = f"volume_{market_id}_{datetime.utcnow().strftime('%Y%m%d%H')}"
                    if alert_key not in self._alerted_markets:
                        alerts.append(Alert(
                            alert_type=AlertType.HIGH_VOLUME,
                            market=market,
                            message=f"Volume spike detected: +{volume_increase:.0%}",
                            metadata={"volume_increase": volume_increase},
                        ))
                        self._alerted_markets.add(alert_key)

        # Update known state
        self._known_markets[market_id] = self._get_market_state(market)

        return alerts

    def check_markets(self, markets: list[Market]) -> list[Alert]:
        """Check multiple markets for alerts."""
        all_alerts = []
        for market in markets:
            try:
                alerts = self.check_market(market)
                all_alerts.extend(alerts)
            except Exception as e:
                logger.error(f"Error checking market {market.id}: {e}")

        # After first run, mark as initialized so future new markets trigger alerts
        if not self._initialized and markets:
            self._initialized = True
            logger.info(f"Initial market load complete. Tracking {len(self._known_markets)} markets. Future changes will trigger alerts.")

        return all_alerts

    def get_trending_markets(self, markets: list[Market], top_n: int = 5) -> list[Market]:
        """Get the top trending markets by volume."""
        sorted_markets = sorted(markets, key=lambda m: m.volume_24h, reverse=True)
        return sorted_markets[:top_n]

    def cleanup_old_alerts(self, hours: int = 24):
        """Remove old alert keys to allow re-alerting."""
        # Simple cleanup - remove alerts older than X hours based on timestamp in key
        current_hour = datetime.utcnow().strftime('%Y%m%d%H')
        self._alerted_markets = {
            key for key in self._alerted_markets
            if current_hour in key or "_" not in key
        }

    @property
    def tracked_market_count(self) -> int:
        """Get the number of markets being tracked."""
        return len(self._known_markets)
