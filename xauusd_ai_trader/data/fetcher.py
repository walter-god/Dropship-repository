"""
Live XAUUSD data fetching layer.

Priority:
  1. MetaTrader 5 Python library  (primary)
  2. Twelve Data REST API         (first fallback)
  3. Yahoo Finance via yfinance   (last fallback)

Provides a unified DataFrame with OHLCV + datetime index (UTC).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from config import (
    BARS_D1, BARS_H4, BARS_M15,
    MT5_LOGIN, MT5_PASSWORD, MT5_PATH, MT5_SERVER,
    MT5_SYMBOL, SYMBOL, TWELVE_DATA_API_KEY, YAHOO_SYMBOL,
)
from utils.logger import get_logger

log = get_logger(__name__)

# MT5 timeframe constants (values match MetaTrader 5 Python lib)
_MT5_TF = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408,
}

_mt5_available: Optional[bool] = None   # cached after first attempt


def _try_import_mt5():
    """Import MetaTrader5 lazily — it only installs on Windows."""
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        return None


def _mt5_connect() -> bool:
    global _mt5_available
    if _mt5_available is False:
        return False
    mt5 = _try_import_mt5()
    if mt5 is None:
        _mt5_available = False
        log.warning("MetaTrader5 package not available — using fallback data source")
        return False
    kwargs = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if not mt5.initialize(**kwargs):
        _mt5_available = False
        log.warning("MT5 initialize() failed: %s", mt5.last_error())
        return False
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            _mt5_available = False
            log.warning("MT5 login failed: %s", mt5.last_error())
            return False
    _mt5_available = True
    return True


def _mt5_fetch(timeframe: str, bars: int) -> Optional[pd.DataFrame]:
    mt5 = _try_import_mt5()
    if mt5 is None:
        return None
    tf_const = _MT5_TF.get(timeframe)
    if tf_const is None:
        log.error("Unknown timeframe: %s", timeframe)
        return None
    rates = mt5.copy_rates_from_pos(MT5_SYMBOL, tf_const, 0, bars)
    if rates is None or len(rates) == 0:
        log.warning("MT5 returned no data for %s %s", MT5_SYMBOL, timeframe)
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    df = df[["time", "open", "high", "low", "close", "volume"]].set_index("time")
    return df


def _twelve_data_fetch(timeframe: str, bars: int) -> Optional[pd.DataFrame]:
    if not TWELVE_DATA_API_KEY:
        return None
    _tf_map = {"M15": "15min", "H4": "4h", "D1": "1day"}
    interval = _tf_map.get(timeframe)
    if interval is None:
        return None
    try:
        import requests
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={SYMBOL}&interval={interval}&outputsize={bars}"
            f"&apikey={TWELVE_DATA_API_KEY}&format=JSON&timezone=UTC"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "values" not in data:
            log.warning("Twelve Data error: %s", data.get("message", "unknown"))
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df = df.sort_values("datetime").set_index("datetime")
        df = df.rename(columns={"volume": "volume"})[["open", "high", "low", "close", "volume"]]
        for col in df.columns:
            df[col] = pd.to_numeric(df[col])
        return df
    except Exception as exc:
        log.warning("Twelve Data fetch failed: %s", exc)
        return None


def _yahoo_fetch(timeframe: str, bars: int) -> Optional[pd.DataFrame]:
    _tf_map = {"M15": "15m", "H4": "1h", "D1": "1d"}
    interval = _tf_map.get(timeframe, "15m")
    _period_map = {"M15": "7d", "H4": "60d", "D1": "180d"}
    period = _period_map.get(timeframe, "7d")
    try:
        ticker = yf.Ticker(YAHOO_SYMBOL)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            return None
        df.index = df.index.tz_convert("UTC")
        df = df.rename(columns={"Open": "open", "High": "high",
                                  "Low": "low", "Close": "close", "Volume": "volume"})
        df = df[["open", "high", "low", "close", "volume"]].tail(bars)
        return df
    except Exception as exc:
        log.warning("Yahoo Finance fetch failed: %s", exc)
        return None


def fetch_ohlcv(timeframe: str = "M15", bars: int = BARS_M15) -> pd.DataFrame:
    """
    Fetch OHLCV data for XAUUSD. Falls back automatically through the three
    source hierarchy and raises RuntimeError if all fail.
    """
    # 1. MT5
    if _mt5_connect():
        df = _mt5_fetch(timeframe, bars)
        if df is not None and not df.empty:
            log.debug("Data via MT5 — %d bars (%s)", len(df), timeframe)
            return df

    # 2. Twelve Data
    df = _twelve_data_fetch(timeframe, bars)
    if df is not None and not df.empty:
        log.info("Data via Twelve Data — %d bars (%s)", len(df), timeframe)
        return df

    # 3. Yahoo Finance
    df = _yahoo_fetch(timeframe, bars)
    if df is not None and not df.empty:
        log.info("Data via Yahoo Finance — %d bars (%s)", len(df), timeframe)
        return df

    raise RuntimeError(f"All data sources failed for {timeframe}")


def fetch_multi_timeframe() -> dict[str, pd.DataFrame]:
    """Fetch M15, H4, and D1 bars in one call for strategy consumption."""
    return {
        "M15": fetch_ohlcv("M15", BARS_M15),
        "H4":  fetch_ohlcv("H4",  BARS_H4),
        "D1":  fetch_ohlcv("D1",  BARS_D1),
    }


def get_current_price() -> float:
    """Return the latest close price from M15 data."""
    df = fetch_ohlcv("M15", bars=2)
    return float(df["close"].iloc[-1])
