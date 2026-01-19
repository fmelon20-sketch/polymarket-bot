"""Health check server for Railway monitoring."""

import logging
from datetime import datetime
from typing import Callable, Awaitable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def create_health_app(
    get_status: Callable[[], Awaitable[dict]],
) -> FastAPI:
    """Create a FastAPI app with health check endpoints."""

    app = FastAPI(
        title="Polymarket Telegram Bot",
        description="Health check API for the Polymarket monitoring bot",
        version="1.0.0",
    )

    @app.get("/")
    async def root():
        """Root endpoint - simple alive check."""
        return {"status": "ok", "service": "polymarket-telegram-bot"}

    @app.get("/health")
    async def health():
        """Health check endpoint for Railway."""
        try:
            status = await get_status()
            return JSONResponse(
                content={
                    "status": "healthy",
                    "timestamp": datetime.utcnow().isoformat(),
                    "tracked_markets": status.get("tracked_markets", 0),
                    "last_check": status.get("last_check", "never"),
                    "alerts_today": status.get("alerts_today", 0),
                    "uptime_seconds": status.get("uptime_seconds", 0),
                },
                status_code=200,
            )
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return JSONResponse(
                content={
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                },
                status_code=503,
            )

    @app.get("/metrics")
    async def metrics():
        """Metrics endpoint for monitoring."""
        try:
            status = await get_status()
            return {
                "tracked_markets": status.get("tracked_markets", 0),
                "alerts_sent_today": status.get("alerts_today", 0),
                "poll_interval_seconds": status.get("poll_interval", 180),
                "last_check_timestamp": status.get("last_check", "never"),
                "uptime_seconds": status.get("uptime_seconds", 0),
            }
        except Exception as e:
            logger.error(f"Metrics endpoint failed: {e}")
            return {"error": str(e)}

    return app
