"""
Vectorised backtesting engine using vectorbt.

Wraps each strategy's generate_signal() into a signal-array format that
vectorbt can process efficiently over a rolling 30-day window.

For each strategy it produces:
  - win_rate      : fraction of profitable trades
  - profit_factor : gross profit / gross loss
  - max_drawdown  : maximum peak-to-trough equity drawdown (fraction)
  - total_trades  : number of closed trades in the window
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    BACKTEST_ROLLING_DAYS,
    ATR_PERIOD,
    ATR_MULTIPLIER_SL,
    ATR_MULTIPLIER_TP,
)
from data.fetcher import fetch_ohlcv
from strategies.base_strategy import atr, BaseStrategy, Signal
from utils.logger import get_logger

log = get_logger(__name__)

try:
    import vectorbt as vbt
    VBT_AVAILABLE = True
except ImportError:
    VBT_AVAILABLE = False
    log.warning("vectorbt not installed — falling back to pandas-based backtester")


# ── Pandas fallback backtester ────────────────────────────────────────────────

def _pandas_backtest(
    entries: pd.Series,
    exits: pd.Series,
    close: pd.Series,
    sl_pct: float,
    tp_pct: float,
) -> Dict:
    """Simple bar-by-bar backtest — O(n) pandas loop over trade lifecycle."""
    in_trade = False
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    direction = "BUY"
    trades: List[float] = []

    for i in range(len(close)):
        if not in_trade:
            if entries.iloc[i] == 1:
                entry_price = float(close.iloc[i])
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price * (1 + tp_pct)
                in_trade = True
                direction = "BUY"
            elif entries.iloc[i] == -1:
                entry_price = float(close.iloc[i])
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 - tp_pct)
                in_trade = True
                direction = "SELL"
        else:
            price = float(close.iloc[i])
            if direction == "BUY":
                if price <= sl_price:
                    trades.append(sl_price - entry_price)
                    in_trade = False
                elif price >= tp_price:
                    trades.append(tp_price - entry_price)
                    in_trade = False
            else:
                if price >= sl_price:
                    trades.append(entry_price - sl_price)
                    in_trade = False
                elif price <= tp_price:
                    trades.append(entry_price - tp_price)
                    in_trade = False

    if not trades:
        return {"win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0, "total_trades": 0}

    arr = np.array(trades)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    gross_profit = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 1e-9
    win_rate = len(wins) / len(arr)
    profit_factor = gross_profit / gross_loss

    # Drawdown via equity curve
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / (peak + 1e-9)
    max_dd = float(dd.max())

    return {
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown": round(max_dd, 4),
        "total_trades": len(arr),
    }


# ── Signal generator adapter ──────────────────────────────────────────────────

def _generate_signal_array(
    strategy: BaseStrategy,
    df_m15: pd.DataFrame,
    df_h4: pd.DataFrame,
    df_d1: pd.DataFrame,
    window: int = 50,
) -> Tuple[pd.Series, pd.Series]:
    """
    Roll a window over M15 data, calling strategy.generate_signal() at each step.
    Returns (entries, exits) as integer Series: 1=buy, -1=sell, 0=nothing.
    """
    entries = pd.Series(0, index=df_m15.index, dtype=int)
    # Simple approach: only track entry, SL/TP handled by _pandas_backtest
    for i in range(window, len(df_m15)):
        slice_m15 = df_m15.iloc[i - window: i]
        # Approximate H4/D1 slice by last available bars
        slice_h4 = df_h4.iloc[max(0, i // 4 - 50): i // 4 + 1] if len(df_h4) > 0 else df_h4
        slice_d1 = df_d1.iloc[max(0, i // 16 - 20): i // 16 + 1] if len(df_d1) > 0 else df_d1
        try:
            signal = strategy.generate_signal({
                "M15": slice_m15.copy(),
                "H4": slice_h4.copy() if len(slice_h4) > 5 else df_h4.copy(),
                "D1": slice_d1.copy() if len(slice_d1) > 3 else df_d1.copy(),
            })
            if signal is not None:
                entries.iloc[i] = 1 if signal.direction == "BUY" else -1
        except Exception as exc:
            log.debug("Signal error at bar %d: %s", i, exc)
            continue

    exits = pd.Series(0, index=df_m15.index, dtype=int)
    return entries, exits


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(
    strategy: BaseStrategy,
    params: Optional[Dict] = None,
    rolling_days: int = BACKTEST_ROLLING_DAYS,
) -> Dict:
    """
    Run a backtest for the given strategy over the last `rolling_days` days.
    Returns a results dict with win_rate, profit_factor, max_drawdown, total_trades.
    """
    if params:
        strategy.params = params

    log.info("Backtesting [%s] over %d days", strategy.name, rolling_days)

    try:
        df_m15 = fetch_ohlcv("M15", bars=rolling_days * 96)   # ≈ 96 M15 bars/day
        df_h4 = fetch_ohlcv("H4", bars=rolling_days * 6)
        df_d1 = fetch_ohlcv("D1", bars=rolling_days)
    except Exception as exc:
        log.error("Data fetch failed during backtest: %s", exc)
        return {"win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 1.0, "total_trades": 0}

    sl_pct = (params or {}).get("sl_multiplier", ATR_MULTIPLIER_SL) * 0.005
    tp_pct = (params or {}).get("tp_multiplier", ATR_MULTIPLIER_TP) * 0.005

    entries, exits = _generate_signal_array(strategy, df_m15, df_h4, df_d1)

    if VBT_AVAILABLE:
        try:
            return _vbt_backtest(df_m15, entries, sl_pct, tp_pct)
        except Exception as exc:
            log.warning("vectorbt backtest failed (%s) — using pandas fallback", exc)

    return _pandas_backtest(entries, exits, df_m15["close"], sl_pct, tp_pct)


def _vbt_backtest(df_m15: pd.DataFrame, entries: pd.Series,
                   sl_pct: float, tp_pct: float) -> Dict:
    close = df_m15["close"]
    buy_entries = entries == 1
    sell_entries = entries == -1

    results_list = []
    for direction, ent in [("BUY", buy_entries), ("SELL", sell_entries)]:
        if not ent.any():
            continue
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=ent,
            exits=pd.Series(False, index=close.index),
            sl_stop=sl_pct,
            tp_stop=tp_pct,
            freq="15T",
        )
        stats = pf.stats()
        results_list.append({
            "win_rate": float(stats.get("Win Rate [%]", 0)) / 100,
            "profit_factor": float(stats.get("Profit Factor", 0)),
            "max_drawdown": float(stats.get("Max Drawdown [%]", 100)) / 100,
            "total_trades": int(stats.get("Total Trades", 0)),
        })

    if not results_list:
        return {"win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 1.0, "total_trades": 0}

    # Aggregate BUY + SELL results
    total = sum(r["total_trades"] for r in results_list)
    if total == 0:
        return {"win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 1.0, "total_trades": 0}
    win_rate = sum(r["win_rate"] * r["total_trades"] for r in results_list) / total
    pf = sum(r["profit_factor"] * r["total_trades"] for r in results_list) / total
    max_dd = max(r["max_drawdown"] for r in results_list)
    return {
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4),
        "max_drawdown": round(max_dd, 4),
        "total_trades": total,
    }
