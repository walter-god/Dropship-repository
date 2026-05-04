"""
Momentum Plays Strategy (SMC)

Logic
-----
1. Determine H4 bias: HTF EMA slope to confirm directional bias.
2. On M15: RSI > 50 (for buys) or RSI < 50 (for sells), MACD histogram
   trending in signal direction, price displacement ≥ MOM_FVG_MIN_PIPS.
3. Detect a Fair Value Gap (FVG) in the direction of momentum:
   - Bullish FVG: candle[i-2].high < candle[i].low
   - Bearish FVG: candle[i-2].low > candle[i].high
4. Enter when price retraces into the FVG midpoint.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    MOM_FVG_MIN_PIPS,
    MOM_MACD_FAST,
    MOM_MACD_SIGNAL,
    MOM_MACD_SLOW,
    MOM_RSI_OB,
    MOM_RSI_OS,
    MOM_RSI_PERIOD,
)
from strategies.base_strategy import BaseStrategy, Signal, ema, atr


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int, slow: int, signal: int) -> Tuple[pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, histogram


def _find_fvg(df: pd.DataFrame, direction: str,
               min_pips: float = MOM_FVG_MIN_PIPS) -> Optional[Tuple[float, float]]:
    """
    Returns (fvg_low, fvg_high) of the most recent FVG in given direction.
    min_pips in gold pips (1 pip = $0.10).
    """
    min_price = min_pips * 0.10
    for i in range(len(df) - 1, 1, -1):
        c_prev2 = df.iloc[i - 2]
        c_curr = df.iloc[i]
        if direction == "BUY":
            if c_curr["low"] > c_prev2["high"] and (c_curr["low"] - c_prev2["high"]) >= min_price:
                return float(c_prev2["high"]), float(c_curr["low"])
        else:
            if c_curr["high"] < c_prev2["low"] and (c_prev2["low"] - c_curr["high"]) >= min_price:
                return float(c_curr["high"]), float(c_prev2["low"])
    return None


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def generate_signal(self, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_h4 = data.get("H4", pd.DataFrame())
        df_m15 = data.get("M15", pd.DataFrame())

        min_bars = max(MOM_MACD_SLOW, MOM_RSI_PERIOD) + 30
        if len(df_m15) < min_bars or len(df_h4) < 50:
            return None

        rsi_period = self.params.get("rsi_period", MOM_RSI_PERIOD)
        macd_fast = self.params.get("macd_fast", MOM_MACD_FAST)
        macd_slow = self.params.get("macd_slow", MOM_MACD_SLOW)
        macd_signal = self.params.get("macd_signal", MOM_MACD_SIGNAL)
        fvg_min_pips = self.params.get("fvg_min_pips", MOM_FVG_MIN_PIPS)

        # HTF bias via H4 EMA slope
        h4_ema = ema(df_h4["close"], 20)
        htf_bias = "BUY" if float(h4_ema.iloc[-1]) > float(h4_ema.iloc[-5]) else "SELL"

        # M15 indicators
        rsi_series = _rsi(df_m15["close"], rsi_period)
        _, macd_hist = _macd(df_m15["close"], macd_fast, macd_slow, macd_signal)
        atr_val = self._atr(df_m15)

        rsi_now = float(rsi_series.iloc[-1])
        hist_now = float(macd_hist.iloc[-1])
        hist_prev = float(macd_hist.iloc[-2])

        if htf_bias == "BUY":
            if rsi_now < 50:
                return None
            if hist_now <= 0 or hist_now < hist_prev:
                return None  # MACD histogram not rising
            fvg = _find_fvg(df_m15, "BUY", fvg_min_pips)
            if fvg is None:
                return None
            fvg_low, fvg_high = fvg
            last_close = float(df_m15.iloc[-1]["close"])
            # Enter when price is inside or just above the FVG
            if not (fvg_low <= last_close <= fvg_high + atr_val * 0.5):
                return None
            entry = last_close
            sl, tp = self._sl_tp("BUY", entry, atr_val)
            confidence = self._confidence(rsi_now, hist_now, hist_prev, df_m15, "BUY", atr_val)
            return self._make_signal("BUY", entry, sl, tp, confidence, "M15",
                                      metadata={"fvg_low": fvg_low, "fvg_high": fvg_high,
                                                 "rsi": round(rsi_now, 1),
                                                 "macd_hist": round(hist_now, 4)})

        else:  # SELL bias
            if rsi_now > 50:
                return None
            if hist_now >= 0 or hist_now > hist_prev:
                return None
            fvg = _find_fvg(df_m15, "SELL", fvg_min_pips)
            if fvg is None:
                return None
            fvg_low, fvg_high = fvg
            last_close = float(df_m15.iloc[-1]["close"])
            if not (fvg_low - atr_val * 0.5 <= last_close <= fvg_high):
                return None
            entry = last_close
            sl, tp = self._sl_tp("SELL", entry, atr_val)
            confidence = self._confidence(rsi_now, hist_now, hist_prev, df_m15, "SELL", atr_val)
            return self._make_signal("SELL", entry, sl, tp, confidence, "M15",
                                      metadata={"fvg_low": fvg_low, "fvg_high": fvg_high,
                                                 "rsi": round(rsi_now, 1),
                                                 "macd_hist": round(hist_now, 4)})

    def _confidence(self, rsi: float, hist_now: float, hist_prev: float,
                    df: pd.DataFrame, direction: str, atr_val: float) -> float:
        score = 50.0

        # RSI distance from 50 (stronger momentum = higher confidence)
        rsi_dist = abs(rsi - 50)
        score += min(rsi_dist * 0.5, 15)

        # MACD histogram acceleration
        if hist_now != 0 and hist_prev != 0 and abs(hist_prev) > 0:
            accel = abs(hist_now - hist_prev) / abs(hist_prev)
            score += min(accel * 10, 15)

        # Volume
        avg_vol = df["volume"].mean()
        last_vol = float(df.iloc[-1]["volume"])
        if last_vol > avg_vol * 1.3:
            score += 10

        # Strong momentum candle
        last = df.iloc[-1]
        body = abs(last["close"] - last["open"])
        if body > atr_val * 0.5:
            score += 10

        return min(score, 92.0)
