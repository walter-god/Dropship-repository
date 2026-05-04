"""
XAUUSD AI Trader — entry point.

Scheduler jobs
--------------
  Every 15 minutes : fetch data → run enabled strategies → execute signals
  Every 15 minutes : sync open positions with MT5
  Daily at 02:00 UTC: run optimization + health check
  Daily at 23:00 UTC: send Telegram daily report
"""

from __future__ import annotations

import signal
import sys
import time
from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from alerts.telegram_bot import TelegramAlerter
from config import (
    DAILY_REPORT_HOUR_UTC,
    DAILY_REPORT_MINUTE_UTC,
    DATA_FETCH_INTERVAL_MINUTES,
)
from data.fetcher import fetch_multi_timeframe
from database import db_manager
from execution.trade_executor import TradeExecutor
from intelligence.optimizer import optimize_all_strategies
from intelligence.strategy_monitor import StrategyMonitor
from risk.risk_manager import RiskManager
from strategies.base_strategy import Signal
from strategies.breakout import BreakoutStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy
from strategies.momentum import MomentumStrategy
from strategies.trend_continuation import TrendContinuationStrategy
from utils.logger import get_logger

log = get_logger("main")


class XAUUSDTrader:
    def __init__(self):
        db_manager.init_db()

        # Strategies
        self._all_strategies = [
            LiquiditySweepStrategy(),
            TrendContinuationStrategy(),
            BreakoutStrategy(),
            MomentumStrategy(),
        ]

        # Core components
        self.risk = RiskManager()
        self.executor = TradeExecutor(self.risk)
        self.monitor = StrategyMonitor(self._all_strategies)
        self.alerter = TelegramAlerter()

        # Scheduler
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self._setup_jobs()

        # State
        self._strategy_status: Dict = {}

    # ── Scheduler setup ───────────────────────────────────────────────────────

    def _setup_jobs(self) -> None:
        # Data + signal job every 15 minutes
        self.scheduler.add_job(
            self._trading_cycle,
            trigger=IntervalTrigger(minutes=DATA_FETCH_INTERVAL_MINUTES),
            id="trading_cycle",
            max_instances=1,
            coalesce=True,
        )
        # Position sync every 15 minutes (offset 5 minutes from above)
        self.scheduler.add_job(
            self._sync_positions,
            trigger=IntervalTrigger(minutes=DATA_FETCH_INTERVAL_MINUTES, seconds=300),
            id="position_sync",
            max_instances=1,
            coalesce=True,
        )
        # Daily optimization at 02:00 UTC
        self.scheduler.add_job(
            self._daily_optimization,
            trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
            id="daily_optimization",
            max_instances=1,
        )
        # Daily report at configured time
        self.scheduler.add_job(
            self._daily_report,
            trigger=CronTrigger(
                hour=DAILY_REPORT_HOUR_UTC,
                minute=DAILY_REPORT_MINUTE_UTC,
                timezone="UTC",
            ),
            id="daily_report",
            max_instances=1,
        )

    # ── Scheduled job handlers ────────────────────────────────────────────────

    def _trading_cycle(self) -> None:
        log.debug("Trading cycle started")
        try:
            # Update account balance from MT5
            balance = self.executor.get_account_balance()
            if balance:
                self.risk.update_balance(balance)

            # Fetch live multi-timeframe data
            data = fetch_multi_timeframe()

            # Run each enabled strategy
            enabled = self.monitor.get_enabled_strategies()
            for strategy in enabled:
                try:
                    signal = strategy.generate_signal(data)
                    if signal is not None:
                        log.info("Signal: %s", signal)
                        self.alerter.send_signal(signal)
                        self.executor.execute_signal(signal)
                except Exception as exc:
                    log.error("[%s] strategy error: %s", strategy.name, exc)
                    self.alerter.send_error_alert(strategy.name, str(exc))
        except Exception as exc:
            log.error("Trading cycle failed: %s", exc)
            self.alerter.send_error_alert("trading_cycle", str(exc))

    def _sync_positions(self) -> None:
        try:
            self.executor.sync_positions()
        except Exception as exc:
            log.error("Position sync failed: %s", exc)

    def _daily_optimization(self) -> None:
        log.info("Daily optimization started")
        try:
            enabled = self.monitor.get_enabled_strategies()
            optimize_all_strategies(enabled)
            self._strategy_status = self.monitor.run_daily_health_check()
            # Send alerts for status changes
            for name, status in self._strategy_status.items():
                if not status.get("enabled", True):
                    self.alerter.send_strategy_disabled_alert(name, status.get("score", 0))
        except Exception as exc:
            log.error("Daily optimization failed: %s", exc)
            self.alerter.send_error_alert("daily_optimization", str(exc))

    def _daily_report(self) -> None:
        log.info("Sending daily report")
        try:
            if not self._strategy_status:
                self._strategy_status = self.monitor.get_status()
            self.alerter.send_daily_report(self._strategy_status)
        except Exception as exc:
            log.error("Daily report failed: %s", exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        log.info("=" * 60)
        log.info("XAUUSD AI Trader starting")
        log.info("=" * 60)

        self.scheduler.start()
        self.alerter.send_startup_message()

        # Run an immediate trading cycle on startup
        self._trading_cycle()

        log.info("Scheduler running — press Ctrl+C to stop")

    def stop(self) -> None:
        log.info("Shutting down XAUUSD AI Trader...")
        self.scheduler.shutdown(wait=False)
        log.info("Scheduler stopped. Goodbye.")


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    trader = XAUUSDTrader()

    def _handle_signal(sig, frame):
        trader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    trader.start()

    # Block main thread
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
