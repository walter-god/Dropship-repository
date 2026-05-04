"""
Breakout Strategy (SMC)

Logic
-----
1. Detect a consolidation range: BREAKOUT_CONSOLIDATION_BARS bars where ATR
   is below BREAKOUT_ATR_QUIET_MULT × 50-bar ATR average.
2. Define the range high and low within the consolidation window.
3. Detect a breakout candle that closes strongly outside the range with
   volume ≥ BREAKOUT_VOL_MULT × average volume.
4. Enter on the breakout candle close OR on a retest of the broken level
   (broken range high becomes support; broken range low becomes resistance).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    BREAKOUT_ATR_QUIET_MULT,
    BREAKOUT_CONSOLIDATION_BARS,
    BREAKOUT_VOL_MULT,
    ATR_PERIOD,
)
from strategies.base_strategy import BaseStrategy, Signal, atr


class BreakoutStrategy(BaseStrategy):
    name = "breakout"

    def generate_signal(self, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df = data.get("M15", pd.DataFrame())
        if len(df) < BREAKOUT_CONSOLIDATION_BARS + ATR_PERIOD + 10:
            return None

        consol_bars = self.params.get("consolidation_bars", BREAKOUT_CONSOLIDATION_BARS)
        atr_quiet_mult = self.params.get("atr_quiet_mult", BREAKOUT_ATR_QUIET_MULT)
        vol_mult = self.params.get("vol_mult", BREAKOUT_VOL_MULT)

        atr_series = atr(df, ATR_PERIOD)
        atr_val = float(atr_series.iloc[-1])
        atr_50_avg = float(atr_series.iloc[-50:].mean()) if len(atr_series) >= 50 else atr_val

        # Check consolidation window (exclude the last candle — it's the potential breakout)
        consol_window = df.iloc[-(consol_bars + 1):-1]
        consol_atr_avg = float(atr_series.iloc[-(consol_bars + 1):-1].mean())

        if consol_atr_avg >= atr_50_avg * atr_quiet_mult:
            return None  # Not in a quiet consolidation

        range_high = float(consol_window["high"].max())
        range_low = float(consol_window["low"].min())
        range_size = range_high - range_low

        if range_size < atr_val * 0.5:
            return None  # Range too small to be meaningful

        # Breakout candle = last closed bar
        last = df.iloc[-1]
        avg_vol = float(df["volume"].iloc[-20:].mean())
        vol_ok = float(last["volume"]) >= avg_vol * vol_mult

        # Bullish breakout
        if last["close"] > range_high and last["close"] > last["open"]:
            if vol_ok:
                entry = float(last["close"])
                sl, tp = self._sl_tp("BUY", entry, atr_val)
                # SL below range high (broken level becomes support)
                sl = range_high - atr_val * 0.3
                confidence = self._confidence(df, "BUY", last, avg_vol, range_size, atr_val)
                return self._make_signal(
                    "BUY", entry, sl, tp, confidence, "M15",
                    metadata={"range_high": range_high, "range_low": range_low,
                               "range_size": range_size},
                )
            # Wait for retest of range_high
            if abs(last["close"] - range_high) <= atr_val * 0.3 and last["close"] > last["open"]:
                entry = float(last["close"])
                sl = range_high - atr_val * 0.5
                tp = entry + (entry - sl) * 2.5
                confidence = self._confidence(df, "BUY", last, avg_vol, range_size, atr_val,
                                               retest=True)
                return self._make_signal(
                    "BUY", entry, sl, tp, confidence, "M15",
                    metadata={"range_high": range_high, "range_low": range_low, "retest": True},
                )

        # Bearish breakout
        if last["close"] < range_low and last["close"] < last["open"]:
            if vol_ok:
                entry = float(last["close"])
                sl, tp = self._sl_tp("SELL", entry, atr_val)
                sl = range_low + atr_val * 0.3
                confidence = self._confidence(df, "SELL", last, avg_vol, range_size, atr_val)
                return self._make_signal(
                    "SELL", entry, sl, tp, confidence, "M15",
                    metadata={"range_high": range_high, "range_low": range_low,
                               "range_size": range_size},
                )
            if abs(last["close"] - range_low) <= atr_val * 0.3 and last["close"] < last["open"]:
                entry = float(last["close"])
                sl = range_low + atr_val * 0.5
                tp = entry - (sl - entry) * 2.5
                confidence = self._confidence(df, "SELL", last, avg_vol, range_size, atr_val,
                                               retest=True)
                return self._make_signal(
                    "SELL", entry, sl, tp, confidence, "M15",
                    metadata={"range_high": range_high, "range_low": range_low, "retest": True},
                )

        return None

    def _confidence(self, df: pd.DataFrame, direction: str, candle: pd.Series,
                    avg_vol: float, range_size: float, atr_val: float,
                    retest: bool = False) -> float:
        score = 50.0

        # Volume confirmation
        vol_ratio = float(candle["volume"]) / avg_vol if avg_vol > 0 else 1.0
        score += min(vol_ratio * 5, 20)

        # Candle body strength
        body = abs(candle["close"] - candle["open"])
        candle_range = candle["high"] - candle["low"]
        if candle_range > 0:
            body_pct = body / candle_range
            score += body_pct * 15

        # Range quality (larger well-defined ranges break better)
        if range_size > atr_val * 2:
            score += 10

        # Retest entries are slightly less confident (needs more confirmation)
        if retest:
            score -= 5

        return min(score, 92.0)
