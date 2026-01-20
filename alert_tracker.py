"""Alert tracking and detection for Polymarket markets - Edge-focused version."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from html import escape
from polymarket_client import Market
from edge_filter import edge_filter, EdgeMatch

logger = logging.getLogger(__name__)

# Patterns to detect daily/routine markets (weather, sports with specific dates)
DAILY_MARKET_PATTERNS = [
    # Weather with specific dates: "on January 19", "on 2026-01-19"
    r'\bon\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b',
    r'\bon\s+\d{4}-\d{2}-\d{2}\b',
    # Temperature ranges (daily weather markets)
    r'temperature.*be\s+(between\s+)?\d+(-\d+)?°?f',
    r'highest temperature.*on\s+',
    r'lowest temperature.*on\s+',
    # Daily sports with specific dates
    r'\bwin\s+on\s+\d{4}-\d{2}-\d{2}\b',
    r'\bmatch\s+on\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b',
]

# Patterns to detect live/in-play sports markets (no PRICE_CHANGE/VOLUME alerts for these)
LIVE_SPORTS_PATTERNS = [
    # Match outcomes with "vs" or "v" (indicates specific match) - e.g., "Liverpool vs Marseille"
    r'\bvs\.?\s+\w+',
    r'\s+v\s+\w+',  # "Team A v Team B"
    # Spread betting - e.g., "Spread: FC Barcelona (-1.5)"
    r'\bspread:\s*',
    r'\(-?\d+\.?\d*\)',  # Point spreads like (-1.5)
    # Over/Under markets - e.g., "O/U 2.5", "O/U 3.5"
    r'\bo/u\s+\d+',
    r'\bover/under\s+\d+',
    # Both teams to score
    r'\bboth\s+teams\s+to\s+score',
    # Specific match questions
    r'\b(win|beat|defeat)\s+(against|vs)',
    # Score/goal related
    r'\bscore\s+(\d+\+?|over|under|more|at least)',
    r'\bgoals?\s+(in|during|by|for)',
    r'\bclean\s+sheet',
    # First/next scorer
    r'(first|next)\s+(goal)?scorer',
    r'score\s+(first|next)',
    # Match result
    r'\b(halftime|half-time|full-time|fulltime)\s+(result|score)',
    r'\bend\s+in\s+a\s+draw',  # "will X vs Y end in a draw"
    # Sport-specific live markets
    r'\b(red|yellow)\s+card',
    r'\bpenalty\s+(kick|scored|missed)',
    r'\bcorners?\s+(over|under|\d+)',
    # Direct team matchups (Team A vs Team B format without "vs" keyword)
    r'^[A-Z][\w\s]+\s+vs?\s+[A-Z][\w\s]+$',  # Full line match
]

LIVE_SPORTS_COMPILED = [re.compile(p, re.IGNORECASE) for p in LIVE_SPORTS_PATTERNS]


def is_live_sports_market(question: str) -> bool:
    """Check if a market is a live sports match market (should skip PRICE_CHANGE alerts)."""
    for pattern in LIVE_SPORTS_COMPILED:
        if pattern.search(question):
            return True
    return False

DAILY_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in DAILY_MARKET_PATTERNS]


def is_daily_market(question: str) -> bool:
    """Check if a market is a daily/routine market that should be excluded."""
    for pattern in DAILY_PATTERNS_COMPILED:
        if pattern.search(question):
            return True
    return False


def extract_market_group(question: str) -> str:
    """
    Extract a group identifier from a market question.
    Markets in the same group are similar (e.g., same event, different outcomes).
    """
    # Remove specific numbers, dates, temperature ranges to group similar markets
    group = question.lower()

    # Remove temperature ranges (45°F, 46-47°F, etc.)
    group = re.sub(r'\d+(-\d+)?°?f', 'TEMP', group)

    # Remove specific dates
    group = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', group)
    group = re.sub(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}', 'DATE', group)

    # Remove specific percentages
    group = re.sub(r'\d+(\.\d+)?%', 'PCT', group)

    # Remove specific scores
    group = re.sub(r'\d+-\d+', 'SCORE', group)

    # Normalize whitespace
    group = re.sub(r'\s+', ' ', group).strip()

    return group


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
        lines.append(f'🔗 <a href="{escape(self.market.url)}">Ouvrir sur Polymarket</a>')

        return "\n".join(lines)


class AlertTracker:
    """Tracks market state and detects alertable changes - Edge-focused."""

    def __init__(
        self,
        liquidity_threshold: float = 1000,
        price_change_threshold: float = 0.10,
        volume_spike_threshold: float = 1.0,
        min_liquidity_for_alerts: float = 2000,
    ):
        self.liquidity_threshold = liquidity_threshold
        self.price_change_threshold = price_change_threshold
        self.volume_spike_threshold = volume_spike_threshold
        self.min_liquidity_for_alerts = min_liquidity_for_alerts

        # Track known markets and their last known state
        self._known_markets: dict[str, dict] = {}
        self._alerted_markets: set[str] = set()
        self._initialized: bool = False

        # Track recently alerted groups to avoid spam (group_key -> timestamp)
        self._alerted_groups: dict[str, datetime] = {}
        self.group_cooldown_minutes: int = 60  # 1 hour cooldown per group

    def _get_market_state(self, market: Market) -> dict:
        """Get the current state of a market for comparison."""
        return {
            "prices": dict(zip(market.outcomes, market.outcome_prices)),
            "volume_24h": market.volume_24h,
            "liquidity": market.liquidity,
            "last_seen": datetime.now(timezone.utc),
        }

    def _is_group_on_cooldown(self, group_key: str) -> bool:
        """Check if a market group is on cooldown."""
        if group_key not in self._alerted_groups:
            return False

        last_alert = self._alerted_groups[group_key]
        elapsed = (datetime.now(timezone.utc) - last_alert).total_seconds() / 60

        return elapsed < self.group_cooldown_minutes

    def _mark_group_alerted(self, group_key: str):
        """Mark a group as recently alerted."""
        self._alerted_groups[group_key] = datetime.now(timezone.utc)

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

        # FILTER 1: Exclude daily/routine markets (weather with specific dates, etc.)
        if is_daily_market(market.question):
            # Still track but don't alert
            if market_id not in self._known_markets:
                self._known_markets[market_id] = self._get_market_state(market)
            logger.debug(f"Skipping daily market: {market.question[:50]}...")
            return []

        # Get the market group for cooldown tracking
        market_group = extract_market_group(market.question)

        # Get previous state if any
        previous_state = self._known_markets.get(market_id)

        # NEW MARKET DETECTION
        if previous_state is None:
            # On first run, just learn markets without alerting
            if not self._initialized:
                pass  # Just learn, don't alert
            # Alert for new edge markets with sufficient liquidity
            # NO group cooldown for new markets - we want ALL of them!
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
            # FILTER 2: Minimum liquidity for price/volume alerts
            if market.liquidity < self.min_liquidity_for_alerts:
                # Update state but skip alerts for small markets
                self._known_markets[market_id] = self._get_market_state(market)
                return alerts

            # FILTER 3: Skip alerts if no real volume (volume 24h = 0 means no real activity)
            if market.volume_24h < 100:  # Minimum $100 volume to consider real activity
                self._known_markets[market_id] = self._get_market_state(market)
                logger.debug(f"Skipping low volume market: {market.question[:50]}... (vol: ${market.volume_24h})")
                return alerts

            # PRICE CHANGE DETECTION
            # Skip price change alerts for live sports matches (no value in these alerts)
            if not is_live_sports_market(market.question):
                for outcome, current_price in zip(market.outcomes, market.outcome_prices):
                    previous_price = previous_state["prices"].get(outcome)
                    if previous_price is not None and previous_price > 0:
                        price_change = current_price - previous_price

                        if abs(price_change) >= self.price_change_threshold:
                            alert_key = f"price_{market_id}_{outcome}_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                            # Check group cooldown
                            if alert_key not in self._alerted_markets and not self._is_group_on_cooldown(market_group):
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
                                self._mark_group_alerted(market_group)
                                logger.info(f"Price change alert: {market.question[:50]}... [{price_change:+.1%}]")
                                break  # One alert per market per check

            # VOLUME SPIKE DETECTION
            # Also skip for live sports (same logic as price change)
            if not is_live_sports_market(market.question):
                prev_volume = previous_state["volume_24h"]
                # Only alert if previous volume was substantial (>$500) to avoid spam on newly tracked markets
                if prev_volume >= 500:
                    volume_increase = (market.volume_24h - prev_volume) / prev_volume
                    if volume_increase > self.volume_spike_threshold:
                        alert_key = f"volume_{market_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
                        # Check group cooldown
                        if alert_key not in self._alerted_markets and not self._is_group_on_cooldown(market_group):
                            alerts.append(Alert(
                                alert_type=AlertType.VOLUME_SPIKE,
                                market=market,
                                message=f"Pic de volume détecté: +{volume_increase:.0%}",
                                edge_match=edge_match,
                                metadata={"volume_increase": volume_increase},
                            ))
                            self._alerted_markets.add(alert_key)
                            self._mark_group_alerted(market_group)
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
