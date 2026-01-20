"""Main entry point for the Polymarket Telegram Bot - Edge-focused version."""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

import uvicorn

from config import config
from polymarket_client import PolymarketClient
from alert_tracker import AlertTracker
from telegram_bot import TelegramNotifier, TelegramBotHandler
from health_server import create_health_app
from edge_filter import edge_filter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class PolymarketBot:
    """Main bot orchestrator - Edge-focused for early market positioning."""

    def __init__(self):
        self.polymarket = PolymarketClient()
        self.tracker = AlertTracker(
            liquidity_threshold=config.liquidity_threshold_usd,
            price_change_threshold=config.price_change_threshold,
            volume_spike_threshold=config.volume_spike_threshold,
            min_liquidity_for_alerts=config.min_liquidity_for_alerts,
        )
        self.notifier = TelegramNotifier(
            token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.bot_handler: Optional[TelegramBotHandler] = None

        self._running = False
        self._start_time = datetime.now(timezone.utc)
        self._last_check: Optional[datetime] = None
        self._alerts_sent_today = 0
        self._alerts_date = datetime.now(timezone.utc).date()
        self._cached_edge_markets = []
        self._edge_markets_count = 0
        self._total_markets_count = 0
        self._initial_scan_done = False

    async def get_status(self) -> dict:
        """Get current bot status."""
        if datetime.now(timezone.utc).date() != self._alerts_date:
            self._alerts_sent_today = 0
            self._alerts_date = datetime.now(timezone.utc).date()

        return {
            "tracked_markets": self._total_markets_count,
            "edge_markets": self._edge_markets_count,
            "last_check": self._last_check.strftime("%Y-%m-%d %H:%M:%S UTC") if self._last_check else "never",
            "alerts_today": self._alerts_sent_today,
            "poll_interval": config.poll_interval_seconds,
            "uptime_seconds": int((datetime.now(timezone.utc) - self._start_time).total_seconds()),
            "initial_scan_done": self._initial_scan_done,
        }

    async def get_trending(self):
        """Get trending markets in edge domains."""
        return self._cached_edge_markets[:10]

    async def _do_initial_scan(self):
        """Do a full scan of ALL markets at startup to learn what exists."""
        logger.info("Starting initial full market scan (this may take a minute)...")

        await self.notifier.send_message(
            "🔄 <b>Scan initial en cours...</b>\n\n"
            "Apprentissage de tous les marchés Polymarket.\n"
            "Cela peut prendre 1-2 minutes."
        )

        try:
            all_markets = await self.polymarket.get_all_active_markets()
            self._total_markets_count = len(all_markets)

            # Filter to find edge markets (exclude dead markets for trending)
            edge_markets = []
            edge_markets_alive = []
            for market in all_markets:
                if edge_filter.matches_edge(market.question, market.tags):
                    edge_markets.append(market)
                    if not market.is_dead:
                        edge_markets_alive.append(market)

            self._edge_markets_count = len(edge_markets)

            # Cache top ALIVE edge markets by liquidity for /trending
            edge_markets_alive.sort(key=lambda m: m.liquidity, reverse=True)
            self._cached_edge_markets = edge_markets_alive[:50]

            # Learn all markets (no alerts on initial scan)
            self.tracker.check_markets(all_markets)

            self._initial_scan_done = True
            self._last_check = datetime.now(timezone.utc)

            logger.info(f"Initial scan complete: {self._total_markets_count} total, {self._edge_markets_count} edge markets")

            await self.notifier.send_message(
                f"✅ <b>Scan initial terminé!</b>\n\n"
                f"📊 Marchés totaux: {self._total_markets_count:,}\n"
                f"🎯 Marchés edge: {self._edge_markets_count}\n\n"
                f"Le bot surveille maintenant les nouveaux marchés et changements."
            )

        except Exception as e:
            logger.error(f"Error during initial scan: {e}", exc_info=True)
            await self.notifier.send_message(
                f"⚠️ <b>Erreur lors du scan initial</b>\n\n"
                f"Le bot va réessayer avec un scan partiel."
            )
            self._initial_scan_done = True  # Continue anyway

    async def monitor_loop(self):
        """Main monitoring loop - optimized for fast new market detection."""
        logger.info("Starting market monitoring loop")
        logger.info(f"Poll interval: {config.poll_interval_seconds} seconds")
        logger.info(f"Liquidity threshold: ${config.liquidity_threshold_usd:,.0f}")
        logger.info(f"Price change threshold: {config.price_change_threshold:.0%}")

        # List edge domains
        from edge_filter import EdgeDomain
        domains = [edge_filter.get_domain_name(d) for d in EdgeDomain]
        domains_str = ", ".join(domains)

        await self.notifier.send_message(
            "🚀 <b>Polymarket Edge Bot Démarré</b>\n\n"
            f"⚡ Surveillance toutes les {config.poll_interval_seconds} secondes\n"
            f"💧 Seuil liquidité: ${config.liquidity_threshold_usd:,.0f}\n"
            f"📊 Seuil changement prix: {config.price_change_threshold:.0%}\n\n"
            f"🎯 <b>Domaines surveillés:</b>\n{domains_str}\n\n"
            "Utilise /status pour voir l'état du bot\n"
            "Utilise /trending pour voir les marchés edge actifs"
        )

        # Do initial full scan
        await self._do_initial_scan()

        # Then regular monitoring
        while self._running:
            try:
                await self._check_markets()
            except Exception as e:
                logger.error(f"Error in monitoring loop iteration: {e}", exc_info=True)

            await asyncio.sleep(config.poll_interval_seconds)

    async def _check_markets(self):
        """Check markets for alerts - focused on edge domains."""
        logger.info("Checking markets...")

        try:
            # Fetch ALL markets to catch new ones in any category
            # This is the key change - we scan everything to find new edge markets
            all_markets = await self.polymarket.get_all_active_markets()

            if not all_markets:
                logger.warning("No markets fetched from API")
                return

            self._total_markets_count = len(all_markets)
            logger.info(f"Fetched {len(all_markets)} active markets")

            # Find and cache edge markets (exclude dead for trending)
            edge_markets = []
            edge_markets_alive = []
            for market in all_markets:
                if edge_filter.matches_edge(market.question, market.tags):
                    edge_markets.append(market)
                    if not market.is_dead:
                        edge_markets_alive.append(market)

            self._edge_markets_count = len(edge_markets)

            # Update cached ALIVE edge markets by liquidity for /trending
            edge_markets_alive.sort(key=lambda m: m.liquidity, reverse=True)
            self._cached_edge_markets = edge_markets_alive[:50]

            # Check for alerts (only edge domains will trigger)
            alerts = self.tracker.check_markets(all_markets)

            if alerts:
                logger.info(f"Found {len(alerts)} alerts to send")
                sent = await self.notifier.send_alerts(alerts)
                self._alerts_sent_today += sent
                logger.info(f"Sent {sent}/{len(alerts)} alerts")
            else:
                logger.info(f"No new alerts (tracking {self._edge_markets_count} edge markets)")

            self._last_check = datetime.now(timezone.utc)
            self.tracker.cleanup_old_alerts()

        except Exception as e:
            logger.error(f"Error checking markets: {e}", exc_info=True)

    async def start(self):
        """Start the bot."""
        logger.info("Starting Polymarket Edge Bot...")

        try:
            config.validate()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            sys.exit(1)

        self._running = True

        self.bot_handler = TelegramBotHandler(
            token=config.telegram_bot_token,
            notifier=self.notifier,
            get_status_callback=self.get_status,
            get_trending_callback=self.get_trending,
        )

        await self.bot_handler.start()

        health_app = create_health_app(self.get_status)

        uvicorn_config = uvicorn.Config(
            app=health_app,
            host="0.0.0.0",
            port=config.health_port,
            log_level="warning",
        )
        health_server = uvicorn.Server(uvicorn_config)

        try:
            await asyncio.gather(
                self.monitor_loop(),
                health_server.serve(),
            )
        except asyncio.CancelledError:
            logger.info("Bot tasks cancelled")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the bot gracefully."""
        logger.info("Stopping bot...")
        self._running = False

        if self.bot_handler:
            await self.bot_handler.stop()

        await self.polymarket.close()

        try:
            await self.notifier.send_message("🛑 <b>Polymarket Edge Bot Arrêté</b>")
        except Exception:
            pass

        logger.info("Bot stopped")


def main():
    """Main entry point."""
    bot = PolymarketBot()

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        bot._running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
