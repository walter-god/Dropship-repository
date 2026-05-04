"""
Risk management engine.

Responsibilities
----------------
- Position sizing based on 1 % account risk
- Daily loss limit (3 %) guard
- Circuit breaker (3 consecutive losses → 2-hour pause)
- Maximum concurrent open trades (3)
- Minimum R:R ratio enforcement (1:2)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import (
    ACCOUNT_BALANCE,
    CIRCUIT_BREAKER_CONSECUTIVE_LOSSES,
    CIRCUIT_BREAKER_PAUSE_HOURS,
    DAILY_LOSS_LIMIT_PCT,
    MAX_OPEN_TRADES,
    MIN_RR_RATIO,
    RISK_PER_TRADE_PCT,
)
from database import db_manager
from utils.logger import get_logger

log = get_logger(__name__)


class RiskManager:
    def __init__(self, account_balance: Optional[float] = None):
        self._lock = threading.Lock()
        self.account_balance = account_balance or ACCOUNT_BALANCE
        self._consecutive_losses: int = 0
        self._circuit_breaker_until: Optional[datetime] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def update_balance(self, new_balance: float) -> None:
        with self._lock:
            self.account_balance = new_balance

    def calculate_lot_size(self, entry: float, stop_loss: float,
                            pip_value: float = 1.0) -> float:
        """
        Lot size so that a full stop-loss hit equals RISK_PER_TRADE_PCT of balance.

        For XAUUSD: 1 lot = 100 oz; pip value ≈ $1 per 0.01 price move per lot.
        pip_value parameter lets callers override for broker-specific values.
        """
        risk_dollars = self.account_balance * RISK_PER_TRADE_PCT
        sl_distance = abs(entry - stop_loss)
        if sl_distance == 0:
            log.warning("SL distance is zero — defaulting to 0.01 lot")
            return 0.01
        # For gold: 1 lot = 100 units; each 1.0 price move on 1 lot = $100
        # lot_size = risk_dollars / (sl_distance * 100)
        lot_size = risk_dollars / (sl_distance * 100 * pip_value)
        lot_size = max(0.01, round(lot_size, 2))
        log.debug(
            "Lot size calc: balance=%.2f risk_pct=%.2f sl_dist=%.4f → %.2f lots",
            self.account_balance, RISK_PER_TRADE_PCT, sl_distance, lot_size,
        )
        return lot_size

    def check_rr_ratio(self, entry: float, stop_loss: float, take_profit: float) -> bool:
        """Return True if the trade meets the minimum R:R ratio."""
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        if risk == 0:
            return False
        rr = reward / risk
        if rr < MIN_RR_RATIO:
            log.debug("R:R %.2f below minimum %.2f — trade rejected", rr, MIN_RR_RATIO)
            return False
        return True

    def is_daily_loss_limit_hit(self) -> bool:
        daily_pnl = db_manager.get_daily_pnl()
        limit = -self.account_balance * DAILY_LOSS_LIMIT_PCT
        if daily_pnl <= limit:
            log.warning(
                "Daily loss limit hit: PnL=%.2f limit=%.2f — halting trading", daily_pnl, limit
            )
            return True
        return False

    def is_circuit_breaker_active(self) -> bool:
        with self._lock:
            if self._circuit_breaker_until is None:
                return False
            now = datetime.now(timezone.utc)
            if now < self._circuit_breaker_until:
                remaining = (self._circuit_breaker_until - now).seconds // 60
                log.warning("Circuit breaker active — %d minutes remaining", remaining)
                return True
            self._circuit_breaker_until = None
            self._consecutive_losses = 0
            return False

    def is_max_trades_reached(self) -> bool:
        open_trades = db_manager.get_open_trades()
        if len(open_trades) >= MAX_OPEN_TRADES:
            log.info("Max open trades (%d) reached", MAX_OPEN_TRADES)
            return True
        return False

    def can_trade(self) -> bool:
        """Single-call gate for all pre-trade risk checks."""
        if self.is_circuit_breaker_active():
            return False
        if self.is_daily_loss_limit_hit():
            return False
        if self.is_max_trades_reached():
            return False
        return True

    def register_trade_result(self, won: bool) -> None:
        """Call after each trade closes to update the circuit breaker state."""
        with self._lock:
            if won:
                self._consecutive_losses = 0
                log.debug("Winning trade registered — consecutive losses reset")
            else:
                self._consecutive_losses += 1
                log.info(
                    "Losing trade registered — consecutive losses: %d",
                    self._consecutive_losses,
                )
                if self._consecutive_losses >= CIRCUIT_BREAKER_CONSECUTIVE_LOSSES:
                    self._circuit_breaker_until = datetime.now(timezone.utc) + timedelta(
                        hours=CIRCUIT_BREAKER_PAUSE_HOURS
                    )
                    log.warning(
                        "Circuit breaker TRIGGERED — trading paused for %d hours",
                        CIRCUIT_BREAKER_PAUSE_HOURS,
                    )

    def get_status(self) -> dict:
        daily_pnl = db_manager.get_daily_pnl()
        open_trades = len(db_manager.get_open_trades())
        return {
            "account_balance": self.account_balance,
            "daily_pnl": daily_pnl,
            "daily_loss_limit": -self.account_balance * DAILY_LOSS_LIMIT_PCT,
            "consecutive_losses": self._consecutive_losses,
            "circuit_breaker_active": self.is_circuit_breaker_active(),
            "circuit_breaker_until": (
                self._circuit_breaker_until.isoformat()
                if self._circuit_breaker_until else None
            ),
            "open_trades": open_trades,
            "max_open_trades": MAX_OPEN_TRADES,
        }
