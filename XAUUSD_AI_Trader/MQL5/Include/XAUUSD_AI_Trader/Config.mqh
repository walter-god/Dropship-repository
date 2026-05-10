//+------------------------------------------------------------------+
//| Config.mqh — Central configuration for XAUUSD AI Trader         |
//+------------------------------------------------------------------+
#pragma once

//--- Telegram credentials (set in EA input panel or via extern)
extern string TelegramBotToken    = "YOUR_BOT_TOKEN_HERE";
extern string TelegramChatID      = "YOUR_CHAT_ID_HERE";

//--- Trading symbol
#define EA_SYMBOL                 "XAUUSD"
#define EA_MAGIC                  20240601

//--- Timeframes used by strategies
#define TF_ENTRY                  PERIOD_M15
#define TF_HTF_TREND              PERIOD_H4
#define TF_DAILY                  PERIOD_D1

//--- Data fetch interval (seconds) — 15 minutes
#define DATA_FETCH_INTERVAL       900

//--- Lookback bars for structure analysis
#define LOOKBACK_BARS             200
#define SWING_LOOKBACK            20
#define ATR_PERIOD                14

//--- Risk management
#define RISK_PERCENT_PER_TRADE    1.0     // 1% account risk per trade
#define DAILY_LOSS_LIMIT_PCT      3.0     // halt if daily DD >= 3%
#define MAX_OPEN_TRADES           3
#define MIN_RR_RATIO              2.0     // minimum 1:2 risk:reward
#define CIRCUIT_BREAKER_LOSSES    3       // consecutive losses before pause
#define CIRCUIT_BREAKER_PAUSE_MIN 120     // pause duration in minutes

//--- Strategy enable flags (also controlled dynamically by StrategyMonitor)
input bool UseStrategyLiquiditySweep   = true;
input bool UseStrategyTrendContinuation = true;
input bool UseStrategyBreakout         = true;
input bool UseStrategyMomentum         = true;

//--- Liquidity Sweep parameters
input int    LS_LiquidityLookback  = 30;    // bars to look back for equal highs/lows
input double LS_EqualLevelTol      = 0.5;   // pip tolerance to consider levels "equal"
input double LS_SL_ATR_Multi       = 1.5;
input double LS_TP_ATR_Multi       = 3.0;

//--- Trend Continuation parameters
input int    TC_OB_Lookback        = 50;    // order block lookback bars
input double TC_SL_ATR_Multi       = 1.5;
input double TC_TP_ATR_Multi       = 3.0;
input int    TC_PullbackBars       = 10;    // max bars in pullback

//--- Breakout parameters
input int    BO_ConsolidationBars  = 20;    // bars to define consolidation range
input double BO_ATR_ConsolThr      = 0.5;   // ATR multiplier below which = consolidation
input double BO_SL_ATR_Multi       = 1.5;
input double BO_TP_ATR_Multi       = 3.0;
input int    BO_VolumeLookback     = 20;    // bars for average volume baseline

//--- Momentum parameters
input int    MOM_RSI_Period        = 14;
input double MOM_RSI_OB            = 70.0;
input double MOM_RSI_OS            = 30.0;
input int    MOM_MACD_Fast         = 12;
input int    MOM_MACD_Slow         = 26;
input int    MOM_MACD_Signal       = 9;
input double MOM_SL_ATR_Multi      = 1.5;
input double MOM_TP_ATR_Multi      = 3.0;
input int    MOM_FVG_Lookback      = 10;

//--- Intelligence / Optimization
#define OPT_BACKTEST_DAYS         30      // rolling window in days
#define OPT_MIN_WIN_RATE          0.40    // minimum acceptable win rate
#define OPT_MIN_PROFIT_FACTOR     1.20
#define OPT_MAX_DRAWDOWN_PCT      15.0
#define OPT_SCORE_THRESHOLD       0.40    // disable strategy below this
#define OPT_DISABLE_STREAK        3       // consecutive poor days before disable
#define OPT_DAILY_TRIALS          50      // optimizer trials per strategy per day

//--- Daily report time (server time hours/minutes)
#define REPORT_HOUR               23
#define REPORT_MINUTE             0

//--- File paths (written to MT5 Files sandbox)
#define LOG_FILE                  "XAUUSD_AI\\logs\\ea_log.csv"
#define TRADES_DB_FILE            "XAUUSD_AI\\db\\trades.csv"
#define BACKTEST_DB_FILE          "XAUUSD_AI\\db\\backtests.csv"
#define STRATEGY_STATE_FILE       "XAUUSD_AI\\db\\strategy_state.csv"
#define OPTIMIZER_PARAMS_FILE     "XAUUSD_AI\\db\\optimizer_params.csv"

//--- Confidence score weights
#define CONF_WEIGHT_STRUCTURE     0.35
#define CONF_WEIGHT_MOMENTUM      0.30
#define CONF_WEIGHT_HTF_TREND     0.20
#define CONF_WEIGHT_RISK_REWARD   0.15
