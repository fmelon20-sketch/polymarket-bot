"""Alert tracking and detection for Polymarket markets - Edge-focused version."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from polymarket_client import Market
from edge_filter import edge_filter, EdgeMatch

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alerts that can be triggered."""
    NEW_MARKET = "new_market"
    PRICE_CHANGE = "price_change"
    VOLUME_SPIKE = "volume_spike"


@dataclass
class Alert:
    """Represents an alert to be sent."""
    alert_type: AlertType
    market: Market
    message: str
    edge_match: Optional[EdgeMatch] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    def format_telegram_message(self) -> str:
        """Format the alert as a Telegram message."""
        lines = []

        # Header with alert type and domain
        if self.alert_type == AlertType.NEW_MARKET:
            emoji = "🚨"
            title = "NOUVEAU MARCHÉ"
        elif self.alert_type == AlertType.PRICE_CHANGE:
            emoji = "📊"
            title = "MOUVEMENT DE PRIX"
        else:
            emoji = "🔥"
            title = "PIC DE VOLUME"

        # Add domain info if we have an edge match
        if self.edge_match:
            domain_emoji = edge_filter.get_domain_emoji(self.edge_match.domain)
            domain_name = edge_filter.get_domain_name(self.edge_match.domain)
            lines.append(f"{emoji} <b>{title}</b> {domain_emoji} {domain_name}")
        else:
            lines.append(f"{emoji} <b>{title}</b>")

        lines.append("")

        # Market question
        lines.append(f"<b>{self.market.question}</b>")
        lines.append("")

        # Prices
        lines.append(f"💹 {self.market.formatted_prices}")

        # Liquidity and volume
        lines.append(f"💧 Liquidité: ${self.market.liquidity:,.0f}")
        lines.append(f"💰 Volume 24h: ${self.market.volume_24h:,.0f}")

        # Price change details if applicable
        if self.metadata.get("price_change"):
            change = self.metadata["price_change"]
            direction = "📈" if change > 0 else "📉"
            lines.append(f"{direction} Changement: {change:+.1%}")
            if self.metadata.get("previous_price") is not None:
                lines.append(f"Prix précédent: {self.metadata['previous_price']*100:.1f}%")

        # Volume spike details
        if self.metadata.get("volume_increase"):
            lines.append(f"📈 Volume +{self.metadata['volume_increase']:.0%}")

        # Keywords matched (for transparency)
        if self.edge_match and self.edge_match.matched_keywords:
            keywords = ", ".join(self.edge_match.matched_keywords[:3])
            lines.append(f"🔍 Mots-clés: {keywords}")

        lines.append("")
        lines.append(f"🔗 <a href=\"{self.market.url}\">Ouvrir sur Polymarket</a>")

        return "\n".join(lines)


class AlertTracker:
    """Tracks market state and detects alertable changes - Edge-focused."""

    def __init__(
        self,
        liquidity_threshold: float = 1000,
        price_change_threshold: float = 0.10,
        volume_spike_threshold: float = 0.50,
    ):
        self.liquidity_threshold = liquidity_threshold
        self.price_change_threshold = price_change_threshold
        self.volume_spike_threshold = volume_spike_threshold

        # Track known markets and their last known state
        self._known_markets: dict[str, dict] = {}
        self._alerted_markets: set[str] = set()
        self._initialized: bool = False

    def _get_market_state(self, market: Market) -> dict:
        """Get the current state of a market for comparison."""
        return {
            "prices": dict(zip(market.outcomes, market.outcome_prices)),
            "volume_24h": market.volume_24h,
            "liquidity": market.liquidity,
            "last_seen": datetime.now(timezone.utc),
        }

    def check_market(self, market: Market) -> list[Alert]:
        """Check a market for alertable conditions - only for edge domains."""
        alerts = []
        market_id = market.id

        # First, check if this market matches our edge domains
        edge_match = edge_filter.check_market(market.question, market.tags)

        # If no edge match, we still track it but don't alert
        if not edge_match:
            # Still update known markets for tracking
            if market_id not in self._known_markets:
                self._known_markets[market_id] = self._get_market_state(market)
            return []

        # Get previous state if any
        previous_state = self._known_markets.get(market_id)

        # NEW MARKET DETECTION
        if previous_state is None:
            # On first run, just learn markets without alerting
            if not self._initialized:
                pass  # Just learn, don't alert
            # Alert for new edge markets with sufficient liquidity
            elif market.liquidity >= self.liquidity_threshold:
                alert_key = f"new_{market_id}"
                if alert_key not in self._alerted_markets:
                    alerts.append(Alert(
                        alert_type=AlertType.NEW_MARKET,
                        market=market,
                        message=f"Nouveau marché détecté dans ton domaine!",
                        edge_match=edge_match,
                    ))
                    self._alerted_markets.add(alert_key)
                    logger.info(f"New edge market alert: {market.question[:50]}... [{edge_match.domain.value}]")
        else:
            # PRICE CHANGE DETECTION
            for outcome, current_price in zip(market.outcomes, market.outcome_prices):
                previous_price = previous_state["prices"].get(outcome)
                if previous_price is not None and previous_price > 0:
                    price_change = current_price - previous_price

                    if abs(price_change) >= self.price_change_threshold:
                        alert_key = f"price_{market_id}_{outcome}_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                        if alert_key not in self._alerted_markets:
                            alerts.append(Alert(
                                alert_type=AlertType.PRICE_CHANGE,
                                market=market,
                                message=f"Mouvement de prix significatif pour {outcome}",
                                edge_match=edge_match,
                                metadata={
                                    "outcome": outcome,
                                    "price_change": price_change,
                                    "previous_price": previous_price,
                                    "current_price": current_price,
                                },
                            ))
                            self._alerted_markets.add(alert_key)
                            logger.info(f"Price change alert: {market.question[:50]}... [{price_change:+.1%}]")
                            break  # One alert per market per check

            # VOLUME SPIKE DETECTION
            prev_volume = previous_state["volume_24h"]
            if prev_volume > 0:
                volume_increase = (market.volume_24h - prev_volume) / prev_volume
                if volume_increase > self.volume_spike_threshold:
                    alert_key = f"volume_{market_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                    if alert_key not in self._alerted_markets:
                        alerts.append(Alert(
                            alert_type=AlertType.VOLUME_SPIKE,
                            market=market,
                            message=f"Pic de volume détecté: +{volume_increase:.0%}",
                            edge_match=edge_match,
                            metadata={"volume_increase": volume_increase},
                        ))
                        self._alerted_markets.add(alert_key)
                        logger.info(f"Volume spike alert: {market.question[:50]}... [+{volume_increase:.0%}]")

        # Update known state
        self._known_markets[market_id] = self._get_market_state(market)

        return alerts

    def check_markets(self, markets: list[Market]) -> list[Alert]:
        """Check multiple markets for alerts."""
        all_alerts = []
        edge_markets_count = 0

        for market in markets:
            try:
                alerts = self.check_market(market)
                all_alerts.extend(alerts)

                # Count edge markets
                if edge_filter.matches_edge(market.question, market.tags):
                    edge_markets_count += 1

            except Exception as e:
                logger.error(f"Error checking market {market.id}: {e}")

        # After first run, mark as initialized
        if not self._initialized and markets:
            self._initialized = True
            logger.info(
                f"Initial load complete. Tracking {len(self._known_markets)} markets total, "
                f"{edge_markets_count} in your edge domains. Future changes will trigger alerts."
            )

        return all_alerts

    def get_edge_markets(self, markets: list[Market]) -> list[tuple[Market, EdgeMatch]]:
        """Get all markets that match edge domains."""
        edge_markets = []
        for market in markets:
            edge_match = edge_filter.check_market(market.question, market.tags)
            if edge_match:
                edge_markets.append((market, edge_match))
        return edge_markets

    def cleanup_old_alerts(self, hours: int = 24):
        """Remove old alert keys to allow re-alerting."""
        current_hour = datetime.now(timezone.utc).strftime('%Y%m%d%H')
        self._alerted_markets = {
            key for key in self._alerted_markets
            if current_hour in key or "_" not in key
        }

    @property
    def tracked_market_count(self) -> int:
        """Get the number of markets being tracked."""
        return len(self._known_markets)

    @property
    def is_initialized(self) -> bool:
        """Check if initial market load is complete."""
        return self._initialized
