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
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1

# Filling modes — retcode 10030 (INVALID_FILL) means the broker rejects the mode.
# We probe all three and cache whichever works for the session.
ORDER_FILLING_FOK    = 0  # Fill-or-Kill: must fill the entire volume immediately
ORDER_FILLING_IOC    = 1  # Immediate-or-Cancel: fill what's available, cancel rest
ORDER_FILLING_RETURN = 2  # Return: partial fills allowed (common on ECN/STP brokers)

_FILLING_MODE_NAMES = {
    ORDER_FILLING_FOK:    "FOK",
    ORDER_FILLING_IOC:    "IOC",
    ORDER_FILLING_RETURN: "RETURN",
}

_mt5_connected = False
_cached_filling_mode: Optional[int] = None  # set after first successful probe


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


def _broker_supported_filling_modes(mt5, symbol: str) -> list[int]:
    """
    Read the broker's advertised filling-mode bitmask from symbol_info and
    return supported modes in preference order.

    Bitmask bits (MetaTrader 5 docs):
      bit 0 (value 1) → FOK
      bit 1 (value 2) → IOC
      bit 2 (value 4) → RETURN (called BOOK in some docs)
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        # Cannot determine — try all in order
        return [ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN]

    mask = getattr(info, "filling_mode", 7)  # default to all bits set
    modes = []
    if mask & 1:
        modes.append(ORDER_FILLING_FOK)
    if mask & 2:
        modes.append(ORDER_FILLING_IOC)
    if mask & 4:
        modes.append(ORDER_FILLING_RETURN)

    if not modes:
        modes = [ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN]

    log.debug("Broker filling_mode bitmask=%d → supported: %s",
              mask, [_FILLING_MODE_NAMES[m] for m in modes])
    return modes


def _probe_filling_mode(mt5, base_request: dict, symbol: str) -> Optional[int]:
    """
    Try each supported filling mode with a check_order call (no real order placed).
    Falls back to live order_send probing if check_order is not conclusive.
    Returns the first working filling mode constant, or None if all fail.
    """
    global _cached_filling_mode
    if _cached_filling_mode is not None:
        return _cached_filling_mode

    modes = _broker_supported_filling_modes(mt5, symbol)

    for mode in modes:
        req = {**base_request, "type_filling": mode}
        # Use order_check() first — it validates without placing an order
        check = mt5.order_check(req)
        if check is not None and check.retcode in (0, 10009):
            log.info("Filling mode %s accepted by broker (order_check)", _FILLING_MODE_NAMES[mode])
            _cached_filling_mode = mode
            return mode
        if check is not None and check.retcode != 10030:
            # A non-filling error (e.g. no price) — the mode itself is valid
            log.info(
                "Filling mode %s assumed valid (order_check retcode=%d != 10030)",
                _FILLING_MODE_NAMES[mode], check.retcode,
            )
            _cached_filling_mode = mode
            return mode
        log.debug("Filling mode %s rejected (retcode=%s)", _FILLING_MODE_NAMES[mode],
                  check.retcode if check else "None")

    log.warning("No filling mode passed order_check — will try live probing")
    return None


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

        base_request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": MT5_SYMBOL,
            "volume": pos.volume,
            "type": close_type,
            "position": mt5_ticket,
            "price": close_price,
            "deviation": 20,
            "magic": MT5_MAGIC,
            "comment": "xauusd_bot_close",
        }
        filling = _cached_filling_mode or _probe_filling_mode(mt5, base_request, MT5_SYMBOL)
        modes_to_try = ([filling] if filling is not None
                        else [ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN])

        result = None
        for mode in modes_to_try:
            result = mt5.order_send({**base_request, "type_filling": mode})
            if result and result.retcode == 10009:
                break
            if result and result.retcode == 10030:
                log.debug("Close: filling mode %s rejected, trying next",
                          _FILLING_MODE_NAMES.get(mode, mode))
                continue
            break  # any other retcode is a real error, stop trying modes

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

        base_request = {
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
        }

        # Determine filling mode: use cached value, probe via order_check, or
        # fall back to trying all modes live (handles retcode 10030).
        filling = _probe_filling_mode(mt5, base_request, MT5_SYMBOL)
        modes_to_try: list[int] = (
            [filling] if filling is not None
            else [ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN]
        )

        for attempt in range(1, 4):  # up to 3 send attempts per mode
            for mode in modes_to_try:
                request = {**base_request, "type_filling": mode}
                result = mt5.order_send(request)

                if result and result.retcode == 10009:
                    # Success — cache and return
                    global _cached_filling_mode
                    _cached_filling_mode = mode
                    log.info(
                        "Order placed — ticket=%d filling=%s attempt=%d",
                        result.order, _FILLING_MODE_NAMES[mode], attempt,
                    )
                    return result.order

                if result and result.retcode == 10030:
                    # Invalid filling mode — try next mode in this attempt
                    log.warning(
                        "Filling mode %s rejected by broker (retcode=10030) — trying next",
                        _FILLING_MODE_NAMES.get(mode, mode),
                    )
                    continue

                # Any other retcode is a genuine execution error
                log.warning(
                    "Order attempt %d/%d failed: retcode=%s comment=%s filling=%s",
                    attempt, 3,
                    result.retcode if result else "N/A",
                    result.comment if result else "N/A",
                    _FILLING_MODE_NAMES.get(mode, mode),
                )
                break  # retry the whole attempt loop after a delay

            else:
                # All filling modes returned 10030 — nothing to retry
                log.error("All filling modes rejected by broker — aborting order")
                return None

            time.sleep(attempt)  # 1s → 2s → 3s between attempts

        return None
