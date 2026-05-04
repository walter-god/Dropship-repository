"""
Telegram alert system.

Sends:
  - Trade signal messages (entry, SL, TP, confidence, strategy)
  - Daily summary report at 23:00 UTC
  - Circuit breaker / daily loss limit alerts
  - Strategy health change alerts
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN
from database import db_manager
from strategies.base_strategy import Signal
from utils.logger import get_logger

log = get_logger(__name__)

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    log.warning("python-telegram-bot not installed — Telegram alerts disabled")


class TelegramAlerter:
    def __init__(self, token: str = TELEGRAM_TOKEN, chat_id: str = TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self._bot: Optional["Bot"] = None
        if TELEGRAM_AVAILABLE and token and chat_id:
            self._bot = Bot(token=token)
        else:
            log.warning("Telegram bot not configured — alerts will be logged only")

    # ── Internal send ─────────────────────────────────────────────────────────

    def _send(self, text: str) -> None:
        if self._bot is None:
            log.info("[TELEGRAM ALERT]\n%s", text)
            return
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                self._bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            )
            loop.close()
        except Exception as exc:
            log.error("Telegram send failed: %s", exc)

    # ── Signal alert ──────────────────────────────────────────────────────────

    def send_signal(self, signal: Signal) -> None:
        direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
        rr = signal.rr_ratio
        conf_bar = self._confidence_bar(signal.confidence)
        msg = (
            f"{direction_emoji} <b>XAUUSD {signal.direction} SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Strategy:</b> {signal.strategy.replace('_', ' ').title()}\n"
            f"⏱ <b>Timeframe:</b> {signal.timeframe}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Entry:</b> {signal.entry_price:.2f}\n"
            f"🛑 <b>Stop Loss:</b> {signal.stop_loss:.2f}\n"
            f"🎯 <b>Take Profit:</b> {signal.take_profit:.2f}\n"
            f"⚖️ <b>R:R Ratio:</b> 1:{rr:.1f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 <b>Confidence:</b> {signal.confidence:.0f}% {conf_bar}\n"
            f"🕐 <b>Time (UTC):</b> {signal.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
        )
        if signal.metadata:
            extras = []
            for k, v in signal.metadata.items():
                if isinstance(v, float):
                    extras.append(f"  • {k}: {v:.2f}")
                else:
                    extras.append(f"  • {k}: {v}")
            msg += "━━━━━━━━━━━━━━━━━━━━━━\n<i>" + "\n".join(extras) + "</i>\n"
        log.info("Signal alert sent: %s", signal)
        self._send(msg)

    # ── Daily report ──────────────────────────────────────────────────────────

    def send_daily_report(self, strategy_status: Dict[str, Dict]) -> None:
        trades = db_manager.get_trades_today()
        closed = [t for t in trades if t["status"] == "CLOSED"]
        wins = [t for t in closed if (t["pnl"] or 0) > 0]
        total_pnl = sum(t["pnl"] or 0 for t in closed)
        win_rate = len(wins) / len(closed) * 100 if closed else 0.0

        active_strats = [name for name, s in strategy_status.items() if s.get("enabled", True)]
        disabled_strats = [name for name, s in strategy_status.items() if not s.get("enabled", True)]

        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        msg = (
            f"📋 <b>DAILY TRADING REPORT</b>\n"
            f"🗓 {datetime.now(timezone.utc).strftime('%Y-%m-%d')} UTC\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Trades:</b> {len(closed)}\n"
            f"✅ <b>Wins:</b> {len(wins)}  ❌ <b>Losses:</b> {len(closed) - len(wins)}\n"
            f"🏆 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"{pnl_emoji} <b>Net PnL:</b> ${total_pnl:+.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>Active Strategies:</b> {', '.join(active_strats) or 'None'}\n"
            f"🔴 <b>Disabled Strategies:</b> {', '.join(disabled_strats) or 'None'}\n"
        )
        if strategy_status:
            msg += "━━━━━━━━━━━━━━━━━━━━━━\n<b>Strategy Scores:</b>\n"
            for name, s in strategy_status.items():
                score = s.get("score", 0.0)
                status_icon = "🟢" if s.get("enabled", True) else "🔴"
                msg += f"  {status_icon} {name.replace('_', ' ').title()}: {score:.3f}\n"

        log.info("Daily report sent")
        self._send(msg)

    # ── Risk alerts ───────────────────────────────────────────────────────────

    def send_circuit_breaker_alert(self, consecutive_losses: int, pause_hours: int) -> None:
        msg = (
            f"⚠️ <b>CIRCUIT BREAKER TRIGGERED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❌ {consecutive_losses} consecutive losing trades\n"
            f"⏸ Trading PAUSED for <b>{pause_hours} hours</b>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        log.warning("Circuit breaker alert sent")
        self._send(msg)

    def send_daily_loss_limit_alert(self, daily_pnl: float, limit: float) -> None:
        msg = (
            f"🚨 <b>DAILY LOSS LIMIT HIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 Daily PnL: <b>${daily_pnl:+.2f}</b>\n"
            f"🛑 Limit: <b>${limit:.2f}</b>\n"
            f"⏹ All trading STOPPED for today\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        log.warning("Daily loss limit alert sent")
        self._send(msg)

    def send_strategy_disabled_alert(self, strategy_name: str, score: float) -> None:
        msg = (
            f"⚠️ <b>STRATEGY AUTO-DISABLED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Strategy: <b>{strategy_name.replace('_', ' ').title()}</b>\n"
            f"📉 Score: <b>{score:.3f}</b> (below threshold)\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self._send(msg)

    def send_strategy_enabled_alert(self, strategy_name: str, score: float) -> None:
        msg = (
            f"✅ <b>STRATEGY RE-ENABLED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Strategy: <b>{strategy_name.replace('_', ' ').title()}</b>\n"
            f"📈 Score: <b>{score:.3f}</b>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self._send(msg)

    def send_startup_message(self) -> None:
        msg = (
            f"🤖 <b>XAUUSD AI TRADER STARTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ System online\n"
            f"📡 Data feed: Active\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self._send(msg)

    def send_error_alert(self, component: str, error: str) -> None:
        msg = (
            f"🔴 <b>SYSTEM ERROR</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ Component: <b>{component}</b>\n"
            f"❌ Error: <code>{error[:300]}</code>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        log.error("Error alert: [%s] %s", component, error)
        self._send(msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _confidence_bar(confidence: float) -> str:
        filled = int(confidence / 10)
        return "█" * filled + "░" * (10 - filled)
