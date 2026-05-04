"""
MT5 trade execution layer.

Responsibilities
----------------
- Submit market orders to MT5 with SL/TP
- Monitor open positions and close them when SL/TP is hit externally
- Update RiskManager on trade closure outcomes
- Gracefully handle MT5 disconnections (pause execution, do not crash)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH, MT5_SYMBOL, MT5_MAGIC
from database import db_manager
from risk.risk_manager import RiskManager
from strategies.base_strategy import Signal
from utils.logger import get_logger

log = get_logger(__name__)

# MT5 order type constants
OP_BUY = 0
OP_SELL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1
ORDER_FILLING_IOC = 1

_mt5_connected = False


def _get_mt5():
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        return None


def _ensure_connected() -> bool:
    global _mt5_connected
    mt5 = _get_mt5()
    if mt5 is None:
        log.warning("MetaTrader5 package unavailable — execution disabled")
        return False
    if not mt5.initialize(path=MT5_PATH if MT5_PATH else None):
        log.error("MT5 initialize() failed: %s", mt5.last_error())
        _mt5_connected = False
        return False
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            log.error("MT5 login failed: %s", mt5.last_error())
            _mt5_connected = False
            return False
    _mt5_connected = True
    return True


def _disconnect():
    mt5 = _get_mt5()
    if mt5:
        mt5.shutdown()


class TradeExecutor:
    def __init__(self, risk_manager: RiskManager):
        self.risk = risk_manager

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_signal(self, signal: Signal) -> Optional[int]:
        """
        Submit a trade to MT5 from a Signal. Returns the DB trade ID or None on failure.
        """
        if not self.risk.can_trade():
            log.info("Risk manager blocked trade: %s", signal)
            return None

        if not self.risk.check_rr_ratio(signal.entry_price, signal.stop_loss, signal.take_profit):
            log.info("R:R ratio too low for signal: %s", signal)
            return None

        lot_size = self.risk.calculate_lot_size(signal.entry_price, signal.stop_loss)

        # Persist to DB before execution so we have a record even on MT5 failure
        trade_record = {
            "strategy": signal.strategy,
            "direction": signal.direction,
            "symbol": signal.symbol,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "lot_size": lot_size,
            "confidence": signal.confidence,
            "timeframe": signal.timeframe,
            "mt5_ticket": None,
        }
        trade_id = db_manager.insert_trade(trade_record)

        ticket = self._send_order(signal, lot_size)
        if ticket:
            db_manager._update_ticket(trade_id, ticket)
            log.info("Order placed — ticket=%d | %s", ticket, signal)
        else:
            log.error("Order FAILED for signal: %s", signal)

        return trade_id

    def close_trade(self, trade_id: int, mt5_ticket: int) -> bool:
        """Manually close an open position by ticket."""
        mt5 = _get_mt5()
        if mt5 is None or not _ensure_connected():
            log.error("Cannot close trade — MT5 unavailable")
            return False

        position = mt5.positions_get(ticket=mt5_ticket)
        if not position:
            log.warning("No position found for ticket %d", mt5_ticket)
            return False

        pos = position[0]
        close_type = ORDER_TYPE_SELL if pos.type == ORDER_TYPE_BUY else ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(MT5_SYMBOL)
        close_price = tick.bid if close_type == ORDER_TYPE_SELL else tick.ask

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": MT5_SYMBOL,
            "volume": pos.volume,
            "type": close_type,
            "position": mt5_ticket,
            "price": close_price,
            "deviation": 20,
            "magic": MT5_MAGIC,
            "comment": "xauusd_bot_close",
            "type_filling": ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result and result.retcode == 10009:
            pnl = pos.profit
            db_manager.close_trade(trade_id, close_price, pnl)
            self.risk.register_trade_result(pnl > 0)
            log.info("Closed ticket=%d pnl=%.2f", mt5_ticket, pnl)
            return True
        log.error("Close failed for ticket=%d: %s", mt5_ticket,
                   result.comment if result else "no result")
        return False

    def sync_positions(self) -> None:
        """
        Reconcile DB open trades against MT5 live positions.
        Close DB records for positions that MT5 has already closed (SL/TP hit).
        """
        mt5 = _get_mt5()
        if mt5 is None or not _ensure_connected():
            return

        open_db_trades = db_manager.get_open_trades()
        if not open_db_trades:
            return

        live_tickets = {p.ticket for p in (mt5.positions_get(symbol=MT5_SYMBOL) or [])}

        for trade in open_db_trades:
            ticket = trade["mt5_ticket"]
            if ticket is None:
                continue
            if ticket not in live_tickets:
                # Position closed by MT5 (SL/TP hit or manual close)
                history = mt5.history_deals_get(position=ticket)
                pnl = 0.0
                close_price = 0.0
                if history:
                    for deal in history:
                        pnl += deal.profit
                    close_price = history[-1].price
                db_manager.close_trade(trade["id"], close_price, pnl)
                self.risk.register_trade_result(pnl > 0)
                log.info("Synced closed position ticket=%d pnl=%.2f", ticket, pnl)

    def get_account_balance(self) -> Optional[float]:
        """Fetch live account balance from MT5."""
        mt5 = _get_mt5()
        if mt5 is None or not _ensure_connected():
            return None
        info = mt5.account_info()
        return float(info.balance) if info else None

    # ── Private order sending ─────────────────────────────────────────────────

    def _send_order(self, signal: Signal, lot_size: float) -> Optional[int]:
        mt5 = _get_mt5()
        if mt5 is None:
            log.warning("MT5 unavailable — order not sent (paper mode)")
            return None
        if not _ensure_connected():
            return None

        tick = mt5.symbol_info_tick(MT5_SYMBOL)
        if tick is None:
            log.error("Cannot get tick for %s", MT5_SYMBOL)
            return None

        order_type = ORDER_TYPE_BUY if signal.direction == "BUY" else ORDER_TYPE_SELL
        price = tick.ask if signal.direction == "BUY" else tick.bid

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": MT5_SYMBOL,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": signal.stop_loss,
            "tp": signal.take_profit,
            "deviation": 20,
            "magic": MT5_MAGIC,
            "comment": f"xauusd_{signal.strategy}",
            "type_filling": ORDER_FILLING_IOC,
        }

        for attempt in range(3):
            result = mt5.order_send(request)
            if result and result.retcode == 10009:
                return result.order
            log.warning(
                "Order attempt %d failed: retcode=%s comment=%s",
                attempt + 1,
                result.retcode if result else "N/A",
                result.comment if result else "N/A",
            )
            time.sleep(1)

        return None
