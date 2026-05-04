# XAUUSD AI Trader

Autonomous AI-powered trading system for Gold (XAUUSD) running 24/7 on a Linux VPS.

## Architecture Overview

```
xauusd_ai_trader/
├── main.py                    # Entry point — APScheduler orchestrator
├── config.py                  # All settings (env-backed)
├── .env.template              # Secrets template
├── data/
│   └── fetcher.py             # MT5 → Twelve Data → Yahoo Finance waterfall
├── strategies/
│   ├── base_strategy.py       # Abstract base + Signal dataclass
│   ├── liquidity_sweep.py     # SMC liquidity sweep + OB entry
│   ├── trend_continuation.py  # HTF EMA trend + M15 OB pullback
│   ├── breakout.py            # Consolidation → breakout + volume
│   └── momentum.py            # RSI + MACD + FVG momentum
├── intelligence/
│   ├── backtester.py          # vectorbt backtesting engine (pandas fallback)
│   ├── optimizer.py           # optuna hyperparameter search
│   └── strategy_monitor.py    # Health scoring + auto-disable
├── risk/
│   └── risk_manager.py        # Position sizing, daily limits, circuit breaker
├── execution/
│   └── trade_executor.py      # MT5 order execution + position sync
├── alerts/
│   └── telegram_bot.py        # Signal messages + daily report
├── database/
│   └── db_manager.py          # SQLite — trades, backtest results, strategy state
└── utils/
    └── logger.py              # Rotating file + coloured console logger
```

---

## Quick Start (Ubuntu 22.04 VPS)

### 1. System dependencies

```bash
sudo apt update && sudo apt install -y python3.10 python3.10-venv python3-pip git
```

### 2. Clone and set up virtual environment

```bash
git clone <your-repo-url> ~/xauusd_trader
cd ~/xauusd_trader/xauusd_ai_trader

python3.10 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

> **MetaTrader 5 note:** The `MetaTrader5` Python package only runs on Windows.
> On a Linux VPS you have two options:
> - Run MT5 on a Windows VPS and expose the Python API over a remote bridge.
> - Use the system in data-only mode (Yahoo Finance / Twelve Data) and send signals
>   to Telegram only — disable MT5 execution in `config.py`.

### 3. Configure secrets

```bash
cp .env.template .env
nano .env          # Fill in MT5, Telegram, and API key values
```

Required `.env` variables:

| Variable | Description |
|---|---|
| `MT5_LOGIN` | MT5 account number |
| `MT5_PASSWORD` | MT5 password |
| `MT5_SERVER` | Broker server name (e.g. `ICMarkets-Demo`) |
| `MT5_PATH` | Path to `terminal64.exe` (Windows VPS only) |
| `TWELVE_DATA_API_KEY` | Free key from twelvedata.com |
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat or channel ID |
| `ACCOUNT_BALANCE` | Starting balance for position sizing |

### 4. Test the system

```bash
source .venv/bin/activate
cd ~/xauusd_trader/xauusd_ai_trader
python main.py
```

Check `logs/trader.log` for output. The system will immediately run a trading
cycle and send a Telegram startup message if configured.

---

## Systemd Service (24/7 operation)

### Create the service file

```bash
sudo nano /etc/systemd/system/xauusd-trader.service
```

Paste the following (adjust paths as needed):

```ini
[Unit]
Description=XAUUSD AI Trader
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/xauusd_trader/xauusd_ai_trader
ExecStart=/home/ubuntu/xauusd_trader/xauusd_ai_trader/.venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable xauusd-trader
sudo systemctl start xauusd-trader

# Check status
sudo systemctl status xauusd-trader

# View live logs
sudo journalctl -u xauusd-trader -f
```

---

## Strategy Details

### 1. Liquidity Sweep (`liquidity_sweep.py`)
Detects equal highs/lows (liquidity pools), identifies stop-hunt candles that
pierce those levels but close back inside, then enters on an Order Block
confirmation in the direction of the reversal.

**Key parameters:** `lookback`, `eq_threshold_pips`, `ob_lookback`, `sl_multiplier`, `tp_multiplier`

### 2. Trend Continuation (`trend_continuation.py`)
Uses H4 EMA(20/50) cross to establish higher-timeframe trend direction, then on
M15 waits for a pullback into a valid demand/supply Order Block and enters in
the trend direction.

**Key parameters:** `ema_fast`, `ema_slow`, `ob_lookback`, `sl_multiplier`, `tp_multiplier`

### 3. Breakout (`breakout.py`)
Detects low-ATR consolidation ranges, identifies breakout candles closing
outside the range with volume confirmation, enters on breakout close or on a
retest of the broken level.

**Key parameters:** `consolidation_bars`, `atr_quiet_mult`, `vol_mult`, `sl_multiplier`, `tp_multiplier`

### 4. Momentum (`momentum.py`)
Combines RSI > 50 (buy) / < 50 (sell), MACD histogram direction, HTF EMA
bias, and a Fair Value Gap to enter high-momentum moves at a retrace level.

**Key parameters:** `rsi_period`, `macd_fast`, `macd_slow`, `macd_signal`, `fvg_min_pips`

---

## Risk Management

| Rule | Value |
|---|---|
| Risk per trade | 1% of account balance |
| Daily loss limit | 3% of account balance |
| Max open trades | 3 |
| Min R:R ratio | 1:2 |
| Circuit breaker | 3 consecutive losses → 2-hour pause |

---

## Intelligence Engine

- **Backtesting:** Rolling 30-day window using `vectorbt` (pandas fallback if unavailable)
- **Optimization:** `optuna` TPE sampler, 50 trials per strategy per day
- **Health scoring:** `win_rate × 0.4 + profit_factor_norm × 0.4 + (1 - max_drawdown) × 0.2`
- **Auto-disable:** Score < 0.4 for 3 consecutive days → strategy disabled automatically

---

## Telegram Signal Format

```
🟢 XAUUSD BUY SIGNAL
━━━━━━━━━━━━━━━━━━━━━━
📊 Strategy: Liquidity Sweep
⏱ Timeframe: M15
━━━━━━━━━━━━━━━━━━━━━━
💰 Entry: 2345.50
🛑 Stop Loss: 2338.20
🎯 Take Profit: 2360.10
⚖️ R:R Ratio: 1:2.1
━━━━━━━━━━━━━━━━━━━━━━
🔥 Confidence: 78% ███████░░░
🕐 Time (UTC): 2026-05-04 14:30
```

---

## Updating parameters without restart

Edit `.env` or the relevant `params` dict in `config.py` and restart the service:

```bash
sudo systemctl restart xauusd-trader
```

The daily optimizer at 02:00 UTC will automatically update strategy parameters
in the database without requiring a restart.

---

## Monitoring

```bash
# Live log tail
sudo journalctl -u xauusd-trader -f --output=cat

# SQLite — recent trades
sqlite3 database/trading.db "SELECT strategy, direction, entry_price, pnl, status FROM trades ORDER BY id DESC LIMIT 20;"

# Strategy health
sqlite3 database/trading.db "SELECT strategy, enabled, consecutive_fails FROM strategy_state;"

# Last backtest scores
sqlite3 database/trading.db "SELECT strategy, run_date, score, win_rate, profit_factor FROM backtest_results ORDER BY id DESC LIMIT 20;"
```
