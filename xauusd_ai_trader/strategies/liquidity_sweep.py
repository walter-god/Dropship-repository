"""
Liquidity Sweep Strategy (SMC)

Logic
-----
1. Detect equal highs or equal lows within LIQSWEEP_LOOKBACK bars
   (liquidity pools sitting above/below price).
2. Identify a sweep candle that pierces through the pool but closes back inside
   (stop-hunt / liquidity grab pattern).
3. Look for an Order Block (OB) in the LIQSWEEP_OB_LOOKBACK bars following
   the sweep — the last bearish candle before a bullish impulse (for buys) or
   vice versa.
4. Optionally confirm with a Fair Value Gap (FVG) in the same direction.
5. Enter on the next bar open after OB confirmation.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import (
    LIQSWEEP_EQ_THRESHOLD_PIPS,
    LIQSWEEP_LOOKBACK,
    LIQSWEEP_OB_LOOKBACK,
)
from strategies.base_strategy import BaseStrategy, Signal, atr


class LiquiditySweepStrategy(BaseStrategy):
    name = "liquidity_sweep"

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal(self, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df = data.get("M15", pd.DataFrame())
        if len(df) < LIQSWEEP_LOOKBACK + 10:
            return None

        lookback = self.params.get("lookback", LIQSWEEP_LOOKBACK)
        eq_threshold = self.params.get("eq_threshold_pips", LIQSWEEP_EQ_THRESHOLD_PIPS)
        ob_lookback = self.params.get("ob_lookback", LIQSWEEP_OB_LOOKBACK)

        # Work on a copy of the tail to avoid mutations
        window = df.iloc[-(lookback + ob_lookback + 5):].copy()
        atr_val = self._atr(window)
        # Convert pip threshold to price units (for XAUUSD 1 pip ≈ $0.10)
        eq_price_threshold = eq_threshold * 0.10

        signal = self._check_bullish_sweep(window, atr_val, eq_price_threshold, ob_lookback)
        if signal:
            return signal
        return self._check_bearish_sweep(window, atr_val, eq_price_threshold, ob_lookback)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_equal_lows(self, df: pd.DataFrame, threshold: float) -> Optional[float]:
        lows = df["low"].values
        for i in range(len(lows) - 2, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                if abs(lows[i] - lows[j]) <= threshold:
                    return min(lows[i], lows[j])
        return None

    def _find_equal_highs(self, df: pd.DataFrame, threshold: float) -> Optional[float]:
        highs = df["high"].values
        for i in range(len(highs) - 2, 0, -1):
            for j in range(i - 1, max(i - 10, -1), -1):
                if abs(highs[i] - highs[j]) <= threshold:
                    return max(highs[i], highs[j])
        return None

    def _find_order_block_bullish(self, df: pd.DataFrame, sweep_idx: int,
                                   ob_lookback: int) -> Optional[int]:
        """Last bearish candle before a bullish impulse, after the sweep."""
        search = df.iloc[max(0, sweep_idx - ob_lookback): sweep_idx + 1]
        bearish = search[search["close"] < search["open"]]
        if bearish.empty:
            return None
        return bearish.index[-1]

    def _find_order_block_bearish(self, df: pd.DataFrame, sweep_idx: int,
                                   ob_lookback: int) -> Optional[int]:
        """Last bullish candle before a bearish impulse, after the sweep."""
        search = df.iloc[max(0, sweep_idx - ob_lookback): sweep_idx + 1]
        bullish = search[search["close"] > search["open"]]
        if bullish.empty:
            return None
        return bullish.index[-1]

    def _has_fvg_bullish(self, df: pd.DataFrame, from_idx: int) -> bool:
        """Check for a bullish FVG (gap between candle[i-2].high and candle[i].low)."""
        pos = df.index.get_loc(from_idx) if from_idx in df.index else -1
        if pos < 2:
            return False
        c = df.iloc[pos]
        c_prev2 = df.iloc[pos - 2]
        return c["low"] > c_prev2["high"]

    def _check_bullish_sweep(self, df: pd.DataFrame, atr_val: float,
                              threshold: float, ob_lookback: int) -> Optional[Signal]:
        pool_level = self._find_equal_lows(df, threshold)
        if pool_level is None:
            return None

        # Find sweep: a candle whose low pierces pool_level but closes above it
        for i in range(len(df) - 1, max(len(df) - 10, 0), -1):
            candle = df.iloc[i]
            if candle["low"] < pool_level and candle["close"] > pool_level:
                # Valid sweep candle found
                ob_idx = self._find_order_block_bullish(df, i, ob_lookback)
                if ob_idx is None:
                    continue
                ob_candle = df.loc[ob_idx]
                entry = float(df.iloc[-1]["close"])
                sl, tp = self._sl_tp("BUY", entry, atr_val)
                confidence = self._confidence_bullish(df, pool_level, ob_candle, atr_val)
                if confidence < 40:
                    return None
                return self._make_signal(
                    "BUY", entry, sl, tp, confidence, "M15",
                    metadata={"pool_level": pool_level, "ob_open": float(ob_candle["open"])},
                )
        return None

    def _check_bearish_sweep(self, df: pd.DataFrame, atr_val: float,
                              threshold: float, ob_lookback: int) -> Optional[Signal]:
        pool_level = self._find_equal_highs(df, threshold)
        if pool_level is None:
            return None

        for i in range(len(df) - 1, max(len(df) - 10, 0), -1):
            candle = df.iloc[i]
            if candle["high"] > pool_level and candle["close"] < pool_level:
                ob_idx = self._find_order_block_bearish(df, i, ob_lookback)
                if ob_idx is None:
                    continue
                ob_candle = df.loc[ob_idx]
                entry = float(df.iloc[-1]["close"])
                sl, tp = self._sl_tp("SELL", entry, atr_val)
                confidence = self._confidence_bearish(df, pool_level, ob_candle, atr_val)
                if confidence < 40:
                    return None
                return self._make_signal(
                    "SELL", entry, sl, tp, confidence, "M15",
                    metadata={"pool_level": pool_level, "ob_open": float(ob_candle["open"])},
                )
        return None

    def _confidence_bullish(self, df: pd.DataFrame, pool: float,
                             ob_candle: pd.Series, atr_val: float) -> float:
        score = 50.0
        # Bonus: strong sweep candle body
        last = df.iloc[-1]
        sweep_body = abs(last["close"] - last["open"])
        if sweep_body > atr_val * 0.5:
            score += 15
        # Bonus: price closed back above pool cleanly
        if last["close"] > pool + atr_val * 0.2:
            score += 10
        # Bonus: OB is a significant bearish candle
        ob_body = abs(ob_candle["close"] - ob_candle["open"])
        if ob_body > atr_val * 0.3:
            score += 10
        # Bonus: volume spike on sweep (if available)
        avg_vol = df["volume"].mean()
        if df.iloc[-1]["volume"] > avg_vol * 1.3:
            score += 15
        return min(score, 95.0)

    def _confidence_bearish(self, df: pd.DataFrame, pool: float,
                             ob_candle: pd.Series, atr_val: float) -> float:
        score = 50.0
        last = df.iloc[-1]
        sweep_body = abs(last["close"] - last["open"])
        if sweep_body > atr_val * 0.5:
            score += 15
        if last["close"] < pool - atr_val * 0.2:
            score += 10
        ob_body = abs(ob_candle["close"] - ob_candle["open"])
        if ob_body > atr_val * 0.3:
            score += 10
        avg_vol = df["volume"].mean()
        if df.iloc[-1]["volume"] > avg_vol * 1.3:
            score += 15
        return min(score, 95.0)
