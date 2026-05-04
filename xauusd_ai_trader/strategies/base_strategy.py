"""
Abstract base class for all trading strategies.

Every concrete strategy must implement:
  - generate_signal(data) → Optional[Signal]

and may override:
  - name (class attribute)
  - calculate_confidence(data, signal) → float  (0–100)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import ATR_PERIOD, ATR_MULTIPLIER_SL, ATR_MULTIPLIER_TP, MT5_SYMBOL
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class Signal:
    strategy: str
    direction: str          # "BUY" or "SELL"
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float       # 0–100
    timeframe: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict = field(default_factory=dict)

    @property
    def rr_ratio(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk else 0.0

    def __str__(self) -> str:
        return (
            f"[{self.strategy}] {self.direction} {self.symbol} @ {self.entry_price:.2f} | "
            f"SL {self.stop_loss:.2f} | TP {self.take_profit:.2f} | "
            f"RR {self.rr_ratio:.2f} | Conf {self.confidence:.0f}%"
        )


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


class BaseStrategy(ABC):
    name: str = "base"

    def __init__(self, params: Optional[Dict] = None):
        self.params = params or {}
        self.log = get_logger(f"strategy.{self.name}")

    # ── Interface ─────────────────────────────────────────────────────────────

    @abstractmethod
    def generate_signal(
        self,
        data: Dict[str, pd.DataFrame],
    ) -> Optional[Signal]:
        """
        Analyse multi-timeframe data and return a Signal or None.

        Parameters
        ----------
        data : dict with keys "M15", "H4", "D1" — each a OHLCV DataFrame
               indexed by UTC datetime.
        """

    # ── Helpers shared across strategies ─────────────────────────────────────

    def _atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """Current ATR value (last bar)."""
        p = period or self.params.get("atr_period", ATR_PERIOD)
        return float(atr(df, p).iloc[-1])

    def _sl_tp(
        self,
        direction: str,
        entry: float,
        atr_value: float,
        sl_mult: Optional[float] = None,
        tp_mult: Optional[float] = None,
    ) -> tuple[float, float]:
        """Derive SL and TP from ATR multiples."""
        sl_m = sl_mult or self.params.get("sl_multiplier", ATR_MULTIPLIER_SL)
        tp_m = tp_mult or self.params.get("tp_multiplier", ATR_MULTIPLIER_TP)
        if direction == "BUY":
            sl = entry - atr_value * sl_m
            tp = entry + atr_value * tp_m
        else:
            sl = entry + atr_value * sl_m
            tp = entry - atr_value * tp_m
        return round(sl, 2), round(tp, 2)

    def _make_signal(
        self,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        timeframe: str = "M15",
        metadata: Optional[Dict] = None,
    ) -> Signal:
        return Signal(
            strategy=self.name,
            direction=direction,
            symbol=MT5_SYMBOL,
            entry_price=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            confidence=round(confidence, 1),
            timeframe=timeframe,
            metadata=metadata or {},
        )
