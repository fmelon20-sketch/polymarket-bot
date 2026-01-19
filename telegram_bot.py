"""Telegram bot for sending Polymarket alerts."""

import logging
from typing import Optional

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import config
from alert_tracker import Alert

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Handles sending notifications to Telegram."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._bot: Optional[Bot] = None

    @property
    def bot(self) -> Bot:
        """Lazy initialize the bot."""
        if self._bot is None:
            self._bot = Bot(token=self.token)
        return self._bot

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=False,
    )
    async def send_message(self, text: str, parse_mode: str = ParseMode.HTML) -> bool:
        """Send a message to the configured chat."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            logger.info(f"Message sent to {self.chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_alert(self, alert: Alert) -> bool:
        """Send an alert to Telegram."""
        message = alert.format_telegram_message()
        return await self.send_message(message)

    async def send_alerts(self, alerts: list[Alert]) -> int:
        """Send multiple alerts, return count of successful sends."""
        success_count = 0
        for alert in alerts:
            if await self.send_alert(alert):
                success_count += 1
        return success_count

    async def send_status(
        self,
        tracked_markets: int,
        last_check: str,
        alerts_sent_today: int,
        is_healthy: bool,
    ) -> bool:
        """Send a status update."""
        status_emoji = "✅" if is_healthy else "⚠️"
        message = f"""
{status_emoji} <b>Bot Status</b>

📊 Markets tracked: {tracked_markets}
🕐 Last check: {last_check}
📬 Alerts sent today: {alerts_sent_today}
⚙️ Poll interval: {config.poll_interval_seconds}s
🎯 Volume threshold: ${config.volume_threshold_usd:,.0f}
📈 Price change threshold: {config.price_change_threshold:.0%}

Status: {"Running" if is_healthy else "Issues detected"}
        """.strip()

        return await self.send_message(message)

    async def send_trending_report(self, markets: list) -> bool:
        """Send a trending markets report."""
        if not markets:
            return await self.send_message("📈 <b>No trending markets found</b>")

        lines = ["📈 <b>Trending Markets</b>", ""]

        for i, market in enumerate(markets[:10], 1):
            lines.append(f"<b>{i}. {market.question}</b>")
            lines.append(f"   {market.formatted_prices}")
            lines.append(f"   💰 Vol 24h: ${market.volume_24h:,.0f}")
            lines.append("")

        return await self.send_message("\n".join(lines))


class TelegramBotHandler:
    """Handles Telegram bot commands."""

    def __init__(
        self,
        token: str,
        notifier: TelegramNotifier,
        get_status_callback,
        get_trending_callback,
    ):
        self.token = token
        self.notifier = notifier
        self.get_status_callback = get_status_callback
        self.get_trending_callback = get_trending_callback
        self.application: Optional[Application] = None

    async def start(self):
        """Initialize and start the bot application."""
        self.application = Application.builder().token(self.token).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("trending", self.cmd_trending))
        self.application.add_handler(CommandHandler("help", self.cmd_help))

        # Initialize the application (required for python-telegram-bot v21+)
        await self.application.initialize()
        await self.application.start()

        # Start polling for updates in the background
        await self.application.updater.start_polling(drop_pending_updates=True)

        logger.info("Telegram bot started and listening for commands")

    async def stop(self):
        """Stop the bot application."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Telegram bot stopped")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome = """
👋 <b>Welcome to Polymarket Alert Bot!</b>

I monitor Polymarket prediction markets and send you alerts about:
• 🆕 New high-volume markets
• 📊 Significant price changes
• 🔥 Volume spikes
• 📈 Trending markets

<b>Commands:</b>
/status - Check bot status
/trending - See trending markets
/help - Show this help message

The bot automatically monitors markets and sends alerts based on configured thresholds.
        """.strip()
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        try:
            status = await self.get_status_callback()
            message = f"""
✅ <b>Bot Status</b>

📊 Markets tracked: {status['tracked_markets']}
🕐 Last check: {status['last_check']}
📬 Alerts sent today: {status['alerts_today']}
⚙️ Poll interval: {status['poll_interval']}s

Status: Running
            """.strip()
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Error in /status command: {e}")
            await update.message.reply_text(
                "⚠️ Error fetching status. Bot is running but encountered an issue.",
                parse_mode=ParseMode.HTML,
            )

    async def cmd_trending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trending command."""
        try:
            markets = await self.get_trending_callback()
            if not markets:
                await update.message.reply_text(
                    "📈 No trending markets found at the moment.",
                    parse_mode=ParseMode.HTML,
                )
                return

            lines = ["📈 <b>Trending Markets</b>", ""]

            for i, market in enumerate(markets[:5], 1):
                lines.append(f"<b>{i}. {market.question[:80]}{'...' if len(market.question) > 80 else ''}</b>")
                lines.append(f"   {market.formatted_prices}")
                lines.append(f"   💰 Vol 24h: ${market.volume_24h:,.0f}")
                lines.append(f"   🔗 <a href=\"{market.url}\">View</a>")
                lines.append("")

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Error in /trending command: {e}")
            await update.message.reply_text(
                "⚠️ Error fetching trending markets.",
                parse_mode=ParseMode.HTML,
            )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self.cmd_start(update, context)
