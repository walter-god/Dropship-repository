# XAUUSD AI Trader — Autonomous Gold Trading EA (MQL5)

Fully autonomous Expert Advisor for **XAUUSD (Gold)** built entirely in **MQL5** for MetaTrader 5.  
Runs 24/7 on a Windows VPS. No Docker, no Python — pure native MQL5.

---

## Architecture Overview

```
XAUUSD_AI_Trader/
└── MQL5/
    ├── Experts/
    │   └── XAUUSD_AI_Trader/
    │       └── XAUUSD_AI_Trader.mq5     ← Main EA entry point
    └── Include/
        └── XAUUSD_AI_Trader/
            ├── Config.mqh               ← All settings & input parameters
            ├── Data/
            │   └── DataFetcher.mqh      ← OHLCV cache (M15 / H4 / D1)
            ├── Strategies/
            │   ├── BaseStrategy.mqh     ← Abstract base + SMC utilities
            │   ├── LiquiditySweep.mqh   ← Equal H/L sweeps + OB/FVG confirm
            │   ├── TrendContinuation.mqh← HTF OB pullback entries
            │   ├── Breakout.mqh         ← Low-ATR range breakout + volume
            │   └── Momentum.mqh         ← RSI + MACD + FVG momentum
            ├── Intelligence/
            │   ├── Backtester.mqh       ← Rolling 30-day bar simulation
            │   ├── Optimizer.mqh        ← Random-sample parameter tuning
            │   └── StrategyMonitor.mqh  ← Health scoring + auto-disable
            ├── Risk/
            │   └── RiskManager.mqh      ← 1% risk, 3% daily limit, CB
            ├── Execution/
            │   └── TradeExecutor.mqh    ← CTrade order management
            ├── Alerts/
            │   └── TelegramBot.mqh      ← WebRequest → Telegram Bot API
            ├── Database/
            │   └── DBManager.mqh        ← CSV logging (trades + backtests)
            └── Utils/
                └── Logger.mqh           ← File + Print logging
```

---

## Strategy Layer (Smart Money Concepts)

| Strategy | Logic |
|---|---|
| **Liquidity Sweep** | Detect equal highs/lows → sweep above/below → reverse entry confirmed by OB or FVG |
| **Trend Continuation** | H4 trend + M15 pullback into demand/supply OB → rejection candle entry |
| **Breakout** | Low-ATR consolidation → strong close outside range with volume confirmation |
| **Momentum** | RSI oversold/overbought recovery + MACD crossover + FVG confluence |

---

## Intelligence Engine

- **Backtester**: Bar-by-bar simulation on rolling 30-day M15 history — runs inline in MQL5 with no external dependencies
- **Optimizer**: 50 random-sample trials per strategy per day (equivalent to a lightweight grid search); best params auto-applied to live strategies
- **StrategyMonitor**: Scores each strategy (40% win rate + 40% profit factor + 20% drawdown); disables any strategy scoring below `0.4` for 3 consecutive days; re-enables when it recovers

---

## Risk Management

| Rule | Setting |
|---|---|
| Risk per trade | 1% of account balance |
| Daily loss limit | 3% — all positions closed, trading halts |
| Circuit breaker | 3 consecutive losses → 2-hour trading pause |
| Max open trades | 3 simultaneously |
| Minimum R:R | 1 : 2 (hard-enforced before any order) |

---

## Telegram Alerts

Every event sends a formatted message to your Telegram channel:

- **Signal alert** — strategy, direction, entry, SL, TP, lot size, confidence %
- **Trade closed** — result (WIN/LOSS), PnL
- **Daily report** — 23:00 UTC — trades, win rate, daily PnL, strategy health
- **Risk alerts** — circuit breaker triggered, daily loss limit hit

---

## Installation

### 1. Copy files to MetaTrader 5

Copy the entire `MQL5/` folder into your MT5 data directory:

```
%APPDATA%\MetaQuotes\Terminal\<terminal-id>\MQL5\
```

Or use the MetaEditor menu: **File → Open Data Folder**, then place:
- `Experts/XAUUSD_AI_Trader/XAUUSD_AI_Trader.mq5`
- `Include/XAUUSD_AI_Trader/` (all subdirectories)

### 2. Compile the EA

Open `XAUUSD_AI_Trader.mq5` in **MetaEditor** (F4 from MT5) and press **Compile** (F7).  
There should be 0 errors.

### 3. Allow WebRequests (required for Telegram)

In MT5: **Tools → Options → Expert Advisors**

Tick **"Allow WebRequests for listed URL"** and add:
```
https://api.telegram.org
```

### 4. Create a Telegram Bot

1. Message `@BotFather` on Telegram → `/newbot` → copy the **Bot Token**
2. Add the bot to your channel/group and get the **Chat ID**  
   (send a message then visit `https://api.telegram.org/bot<TOKEN>/getUpdates`)

### 5. Attach the EA to XAUUSD Chart

- Open a **XAUUSD M15** chart in MT5
- Drag `XAUUSD_AI_Trader` from the Navigator panel onto the chart
- In the EA settings:
  - Set **InpTelegramToken** = your bot token
  - Set **InpTelegramChatID** = your chat ID
  - Adjust strategy toggles and risk parameters as needed
- Enable **"Allow Algo Trading"** (the green play button)

### 6. Configure Strategy Parameters

All parameters are available in the EA's **Inputs** tab:

| Parameter | Default | Description |
|---|---|---|
| `UseStrategyLiquiditySweep` | true | Enable/disable Liquidity Sweep |
| `UseStrategyTrendContinuation` | true | Enable/disable Trend Continuation |
| `UseStrategyBreakout` | true | Enable/disable Breakout |
| `UseStrategyMomentum` | true | Enable/disable Momentum |
| `LS_LiquidityLookback` | 30 | Bars to look back for equal levels |
| `LS_SL_ATR_Multi` | 1.5 | ATR multiplier for Stop Loss |
| `LS_TP_ATR_Multi` | 3.0 | ATR multiplier for Take Profit |
| `TC_OB_Lookback` | 50 | H4 Order Block lookback bars |
| `BO_ConsolidationBars` | 20 | Bars defining consolidation range |
| `MOM_RSI_Period` | 14 | RSI period |
| `MOM_RSI_OB` | 70 | RSI overbought threshold |
| `MOM_RSI_OS` | 30 | RSI oversold threshold |

---

## Running 24/7 on a Windows VPS

MetaTrader 5 runs natively on **Windows**. For 24/7 uptime:

### Option A — Windows Task Scheduler (simple)

1. Install MT5 on your VPS  
2. Create a scheduled task to launch `terminal64.exe` on system startup:
   ```
   Action: Start a program
   Program: C:\Program Files\MetaTrader 5\terminal64.exe
   Arguments: /portable
   Run: At system startup
   ```

### Option B — Windows Service Wrapper (robust)

Use **NSSM** (Non-Sucking Service Manager) to wrap MT5 as a Windows service:

```bat
nssm install MT5Trader "C:\Program Files\MetaTrader 5\terminal64.exe"
nssm set MT5Trader AppParameters "/portable"
nssm set MT5Trader Start SERVICE_AUTO_START
nssm set MT5Trader ObjectName LocalSystem
net start MT5Trader
```

Download NSSM: https://nssm.cc/download

### VPS Recommendations

| Provider | Spec | Notes |
|---|---|---|
| Contabo | 4 vCPU, 8GB RAM | Budget-friendly, EU/US locations |
| Vultr | 2 vCPU, 4GB RAM | Fast spin-up |
| AWS EC2 | t3.medium | Windows Server 2022 AMI |

Minimum: **2 vCPU, 4GB RAM, Windows Server 2019+**

---

## Data Persistence

All data is written to MT5's sandboxed **Files** folder:

```
%APPDATA%\MetaQuotes\Terminal\<id>\MQL5\Files\XAUUSD_AI\
├── logs\
│   └── ea_log.csv          ← All log entries with timestamps
└── db\
    ├── trades.csv           ← Every closed trade (full record)
    ├── backtests.csv        ← Daily backtest results per strategy
    ├── strategy_state.csv   ← Enabled/disabled state + poor-day streaks
    └── optimizer_params.csv ← Best parameters per strategy
```

---

## Backtesting in MT5 Strategy Tester

1. In MT5: **View → Strategy Tester** (Ctrl+R)
2. Select EA: `XAUUSD_AI_Trader`
3. Symbol: `XAUUSD`, Timeframe: `M15`
4. Mode: **Every tick based on real ticks** (most accurate)
5. Date range: last 6–12 months
6. Set Telegram inputs to empty strings (no alerts during backtest)
7. Press **Start**

For **Optimization** (MT5 built-in):
- Switch to **Optimization** mode
- Select parameters to optimize (SL/TP multipliers, lookback periods)
- MT5 will run the genetic algorithm across parameter space

---

## Key MQL5 Concepts Used

| Feature | Usage |
|---|---|
| `EventSetTimer(15)` | 15-second polling; data refresh gated to 15-min intervals |
| `OnTimer()` | All scheduled work: data refresh, optimization, daily report |
| `OnTradeTransaction()` | Detect closed deals for PnL logging + Telegram notification |
| `CTrade` class | Order opening/closing with slippage and filling mode control |
| `WebRequest()` | HTTP POST to Telegram Bot API |
| `CopyRates()` | Pull M15/H4/D1 OHLCV bars from the broker |
| `iRSI() / iMACD()` | Indicator handles for the Momentum strategy |
| `FileOpen() / FileWrite()` | CSV-based persistence (trades, backtests, state) |

---

## Troubleshooting

| Issue | Fix |
|---|---|
| EA not trading | Check "Allow Algo Trading" is enabled (green button in toolbar) |
| No Telegram messages | Add `https://api.telegram.org` to allowed URLs in Options |
| "DataFetcher init failed" | Ensure XAUUSD is in Market Watch and has sufficient history |
| Compile errors on `<Trade\Trade.mqh>` | MT5 Standard Library must be installed (reinstall MT5 if missing) |
| No history for backtest | Right-click XAUUSD chart → Download History |

---

## License

This EA is provided for educational and research purposes.  
Always test thoroughly on a **demo account** before live trading.  
Past performance of backtests does not guarantee future results.
