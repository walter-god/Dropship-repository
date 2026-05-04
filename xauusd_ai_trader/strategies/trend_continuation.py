"""
Trend Continuation Strategy (SMC)

Logic
-----
1. Determine HTF (H4/D1) trend direction via EMA cross (fast > slow = bullish).
2. On M15, wait for price to pull back into a valid Order Block or
   demand/supply zone that aligns with the HTF trend.
3. Confirm price is reacting (bullish candle inside demand zone for uptrend;
   bearish candle inside supply zone for downtrend).
4. Enter in the trend direction with OB boundaries defining initial SL/TP reference.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from config import (
    TREND_HTF_EMA_FAST,
    TREND_HTF_EMA_SLOW,
    TREND_OB_LOOKBACK,
    TREND_PULLBACK_MIN_PCT,
)
from strategies.base_strategy import BaseStrategy, Signal, ema, atr


class TrendContinuationStrategy(BaseStrategy):
    name = "trend_continuation"

    def generate_signal(self, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_h4 = data.get("H4", pd.DataFrame())
        df_m15 = data.get("M15", pd.DataFrame())

        if len(df_h4) < TREND_HTF_EMA_SLOW + 5 or len(df_m15) < TREND_OB_LOOKBACK + 5:
            return None

        fast_p = self.params.get("ema_fast", TREND_HTF_EMA_FAST)
        slow_p = self.params.get("ema_slow", TREND_HTF_EMA_SLOW)
        ob_lb = self.params.get("ob_lookback", TREND_OB_LOOKBACK)

        ema_fast = ema(df_h4["close"], fast_p)
        ema_slow = ema(df_h4["close"], slow_p)

        htf_bullish = float(ema_fast.iloc[-1]) > float(ema_slow.iloc[-1])
        htf_bearish = float(ema_fast.iloc[-1]) < float(ema_slow.iloc[-1])

        atr_val = self._atr(df_m15)

        if htf_bullish:
            return self._bullish_continuation(df_m15, df_h4, atr_val, ob_lb)
        if htf_bearish:
            return self._bearish_continuation(df_m15, df_h4, atr_val, ob_lb)
        return None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _find_demand_ob(self, df: pd.DataFrame, lookback: int) -> Optional[pd.Series]:
        """
        Demand OB = last significant bearish candle before a strong bullish move.
        We look for a bearish candle followed by at least 2 consecutive bullish candles.
        """
        window = df.iloc[-(lookback + 5):-1]
        for i in range(len(window) - 3, 0, -1):
            c = window.iloc[i]
            if c["close"] >= c["open"]:
                continue
            # Check 2 bullish candles after
            c1 = window.iloc[i + 1]
            c2 = window.iloc[i + 2] if i + 2 < len(window) else None
            if c1["close"] > c1["open"] and (c2 is None or c2["close"] > c2["open"]):
                return c
        return None

    def _find_supply_ob(self, df: pd.DataFrame, lookback: int) -> Optional[pd.Series]:
        """Supply OB = last bullish candle before a strong bearish impulse."""
        window = df.iloc[-(lookback + 5):-1]
        for i in range(len(window) - 3, 0, -1):
            c = window.iloc[i]
            if c["close"] <= c["open"]:
                continue
            c1 = window.iloc[i + 1]
            c2 = window.iloc[i + 2] if i + 2 < len(window) else None
            if c1["close"] < c1["open"] and (c2 is None or c2["close"] < c2["open"]):
                return c
        return None

    def _is_in_zone(self, price: float, candle: pd.Series, buffer_pct: float = 0.005) -> bool:
        low = min(candle["open"], candle["close"])
        high = max(candle["open"], candle["close"])
        buf = (high - low) * buffer_pct
        return low - buf <= price <= high + buf

    def _bullish_continuation(self, df_m15: pd.DataFrame, df_h4: pd.DataFrame,
                               atr_val: float, ob_lb: int) -> Optional[Signal]:
        ob = self._find_demand_ob(df_m15, ob_lb)
        if ob is None:
            return None

        last = df_m15.iloc[-1]
        if not self._is_in_zone(float(last["close"]), ob):
            return None

        # Confirm: current M15 candle is bullish (reacting off the demand OB)
        if last["close"] <= last["open"]:
            return None

        entry = float(last["close"])
        sl = float(min(ob["open"], ob["close"])) - atr_val * 0.5
        tp = entry + (entry - sl) * 2.0

        confidence = self._confidence(df_m15, df_h4, "BUY", atr_val, ob)
        return self._make_signal("BUY", entry, sl, tp, confidence, "M15",
                                  metadata={"ob_high": float(max(ob["open"], ob["close"])),
                                            "ob_low": float(min(ob["open"], ob["close"]))})

    def _bearish_continuation(self, df_m15: pd.DataFrame, df_h4: pd.DataFrame,
                               atr_val: float, ob_lb: int) -> Optional[Signal]:
        ob = self._find_supply_ob(df_m15, ob_lb)
        if ob is None:
            return None

        last = df_m15.iloc[-1]
        if not self._is_in_zone(float(last["close"]), ob):
            return None

        if last["close"] >= last["open"]:
            return None

        entry = float(last["close"])
        sl = float(max(ob["open"], ob["close"])) + atr_val * 0.5
        tp = entry - (sl - entry) * 2.0

        confidence = self._confidence(df_m15, df_h4, "SELL", atr_val, ob)
        return self._make_signal("SELL", entry, sl, tp, confidence, "M15",
                                  metadata={"ob_high": float(max(ob["open"], ob["close"])),
                                            "ob_low": float(min(ob["open"], ob["close"]))})

    def _confidence(self, df_m15: pd.DataFrame, df_h4: pd.DataFrame,
                    direction: str, atr_val: float, ob: pd.Series) -> float:
        score = 55.0
        # Strong OB candle body
        body = abs(ob["close"] - ob["open"])
        if body > atr_val * 0.4:
            score += 10
        # H4 trend strength (distance between EMAs)
        fast_p = self.params.get("ema_fast", TREND_HTF_EMA_FAST)
        slow_p = self.params.get("ema_slow", TREND_HTF_EMA_SLOW)
        e_fast = float(ema(df_h4["close"], fast_p).iloc[-1])
        e_slow = float(ema(df_h4["close"], slow_p).iloc[-1])
        ema_gap = abs(e_fast - e_slow)
        if ema_gap > atr_val * 0.5:
            score += 15
        # Volume confirmation on current candle
        avg_vol = df_m15["volume"].mean()
        if df_m15.iloc[-1]["volume"] > avg_vol * 1.2:
            score += 10
        # Pullback depth (deeper = better confluence)
        swing_high = df_m15["high"].rolling(20).max().iloc[-1]
        swing_low = df_m15["low"].rolling(20).min().iloc[-1]
        swing_range = swing_high - swing_low
        last_close = df_m15.iloc[-1]["close"]
        if direction == "BUY" and swing_range > 0:
            pullback_pct = (swing_high - last_close) / swing_range
            if pullback_pct > TREND_PULLBACK_MIN_PCT:
                score += 10
        elif direction == "SELL" and swing_range > 0:
            pullback_pct = (last_close - swing_low) / swing_range
            if pullback_pct > TREND_PULLBACK_MIN_PCT:
                score += 10
        return min(score, 95.0)
