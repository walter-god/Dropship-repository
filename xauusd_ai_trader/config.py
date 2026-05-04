"""
Central configuration — all tuneable parameters and environment-variable bindings.
Sensitive credentials are read from the .env file via python-dotenv.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# MetaTrader 5
# ---------------------------------------------------------------------------
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")          # Path to terminal64.exe on Windows VPS
MT5_SYMBOL = "XAUUSD"
MT5_MAGIC = 20240101                           # Unique magic number for this EA

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
DATA_FETCH_INTERVAL_MINUTES = 15
SYMBOL = "XAUUSD"
YAHOO_SYMBOL = "GC=F"                         # Yahoo Finance gold futures ticker

# Timeframes (MT5 constants are mapped in fetcher.py)
PRIMARY_TF = "M15"
HTF = "H4"                                    # Higher timeframe for trend bias
HTF_D1 = "D1"

# Bars to fetch per request
BARS_M15 = 500
BARS_H4 = 200
BARS_D1 = 100

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DAILY_REPORT_HOUR_UTC = 23
DAILY_REPORT_MINUTE_UTC = 0

# ---------------------------------------------------------------------------
# Risk management
# ---------------------------------------------------------------------------
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "10000"))   # USD; updated at runtime
RISK_PER_TRADE_PCT = 0.01          # 1 % of account per trade
DAILY_LOSS_LIMIT_PCT = 0.03        # 3 % of account
MIN_RR_RATIO = 2.0                 # Minimum reward-to-risk ratio
MAX_OPEN_TRADES = 3
CIRCUIT_BREAKER_CONSECUTIVE_LOSSES = 3
CIRCUIT_BREAKER_PAUSE_HOURS = 2

# ---------------------------------------------------------------------------
# Strategy parameters (defaults; overridden by optimizer)
# ---------------------------------------------------------------------------
# Shared
ATR_PERIOD = 14
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0

# Liquidity Sweep
LIQSWEEP_LOOKBACK = 20            # Bars to look back for equal highs/lows
LIQSWEEP_EQ_THRESHOLD_PIPS = 5   # Max pip difference to consider "equal"
LIQSWEEP_OB_LOOKBACK = 5         # Bars to look back for order block after sweep

# Trend Continuation
TREND_HTF_EMA_FAST = 20
TREND_HTF_EMA_SLOW = 50
TREND_OB_LOOKBACK = 10
TREND_PULLBACK_MIN_PCT = 0.3      # Minimum pullback % of the swing before re-entry

# Breakout
BREAKOUT_CONSOLIDATION_BARS = 20  # Bars to measure low-ATR consolidation
BREAKOUT_ATR_QUIET_MULT = 0.7     # ATR must be below this fraction of 50-bar average
BREAKOUT_VOL_MULT = 1.5           # Volume must exceed this multiple of average on breakout

# Momentum
MOM_RSI_PERIOD = 14
MOM_RSI_OB = 70
MOM_RSI_OS = 30
MOM_MACD_FAST = 12
MOM_MACD_SLOW = 26
MOM_MACD_SIGNAL = 9
MOM_FVG_MIN_PIPS = 10             # Minimum Fair Value Gap size in pips

# ---------------------------------------------------------------------------
# Intelligence / optimization
# ---------------------------------------------------------------------------
BACKTEST_ROLLING_DAYS = 30
OPTUNA_TRIALS = 50                # Trials per strategy per daily run
OPTUNA_TIMEOUT_SECONDS = 300      # Max seconds per optimization run
STRATEGY_SCORE_WEIGHTS = {
    "win_rate": 0.40,
    "profit_factor": 0.40,
    "max_drawdown": 0.20,         # Inverted — lower drawdown = higher score
}
STRATEGY_DISABLE_THRESHOLD = 0.40
STRATEGY_DISABLE_CONSECUTIVE_DAYS = 3

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = BASE_DIR / "database" / "trading.db"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
