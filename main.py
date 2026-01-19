"""Main entry point for the Polymarket Telegram Bot."""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

import uvicorn

from config import config
from polymarket_client import PolymarketClient
from alert_tracker import AlertTracker
from telegram_bot import TelegramNotifier, TelegramBotHandler
from health_server import create_health_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class PolymarketBot:
    """Main bot orchestrator."""

    def __init__(self):
        self.polymarket = PolymarketClient()
        self.tracker = AlertTracker(
            volume_threshold=config.volume_threshold_usd,
            price_change_threshold=config.price_change_threshold,
        )
        self.notifier = TelegramNotifier(
            token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.bot_handler: Optional[TelegramBotHandler] = None

        self._running = False
        self._start_time = datetime.utcnow()
        self._last_check: Optional[datetime] = None
        self._alerts_sent_today = 0
        self._alerts_date = datetime.utcnow().date()
        self._cached_markets = []

    async def get_status(self) -> dict:
        """Get current bot status."""
        if datetime.utcnow().date() != self._alerts_date:
            self._alerts_sent_today = 0
            self._alerts_date = datetime.utcnow().date()

        return {
            "tracked_markets": self.tracker.tracked_market_count,
            "last_check": self._last_check.strftime("%Y-%m-%d %H:%M:%S UTC") if self._last_check else "never",
            "alerts_today": self._alerts_sent_today,
            "poll_interval": config.poll_interval_seconds,
            "uptime_seconds": int((datetime.utcnow() - self._start_time).total_seconds()),
        }

    async def get_trending(self):
        """Get trending markets."""
        if not self._cached_markets:
            self._cached_markets = await self.polymarket.get_top_markets_by_volume(limit=10)
        return self._cached_markets

    async def monitor_loop(self):
        """Main monitoring loop."""
        logger.info("Starting market monitoring loop")
        logger.info(f"Poll interval: {config.poll_interval_seconds} seconds")
        logger.info(f"Volume threshold: ${config.volume_threshold_usd:,.0f}")
        logger.info(f"Price change threshold: {config.price_change_threshold:.0%}")

        await self.notifier.send_message(
            "🚀 <b>Polymarket Bot Started</b>\n\n"
            f"Monitoring markets every {config.poll_interval_seconds} seconds.\n"
            f"Volume threshold: ${config.volume_threshold_usd:,.0f}\n"
            f"Price change threshold: {config.price_change_threshold:.0%}\n\n"
            "Use /status to check bot health."
        )

        while self._running:
            try:
                await self._check_markets()
            except Exception as e:
                logger.error(f"Error in monitoring loop iteration: {e}", exc_info=True)

            await asyncio.sleep(config.poll_interval_seconds)

    async def _check_markets(self):
        """Check markets for alerts."""
        logger.info("Checking markets...")

        try:
            markets = await self.polymarket.get_active_markets(
                limit=100,
                tags=config.watched_tags,
            )

            if not markets:
                logger.warning("No markets fetched from API")
                return

            logger.info(f"Fetched {len(markets)} active markets")

            self._cached_markets = markets[:10]

            alerts = self.tracker.check_markets(markets)

            if alerts:
                logger.info(f"Found {len(alerts)} alerts to send")
                sent = await self.notifier.send_alerts(alerts)
                self._alerts_sent_today += sent
                logger.info(f"Sent {sent}/{len(alerts)} alerts")
            else:
                logger.info("No new alerts")

            self._last_check = datetime.utcnow()

            self.tracker.cleanup_old_alerts()

        except Exception as e:
            logger.error(f"Error checking markets: {e}", exc_info=True)

    async def start(self):
        """Start the bot."""
        logger.info("Starting Polymarket Telegram Bot...")

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
            await self.notifier.send_message("🛑 <b>Polymarket Bot Stopped</b>")
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
