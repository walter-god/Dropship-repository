//+------------------------------------------------------------------+
//| XAUUSD_AI_Trader.mq5 — Autonomous XAUUSD AI Trading EA         |
//|                                                                  |
//| Architecture:                                                    |
//|  Data Layer      → CDataFetcher   (15-min timer)                |
//|  Strategy Layer  → 4 SMC strategies (LS, TC, BO, MOM)          |
//|  Intelligence    → CBacktester + COptimizer + CStrategyMonitor  |
//|  Execution       → CTradeExecutor (CTrade-based)               |
//|  Alerts          → CTelegramBot   (WebRequest)                  |
//|  Risk            → CRiskManager   (1% risk, 3% daily limit,    |
//|                                    circuit breaker)             |
//|  Logging         → CLogger + CDBManager (CSV files)            |
//+------------------------------------------------------------------+
#property copyright "XAUUSD AI Trader"
#property version   "1.00"
#property strict

//--- Include all modules
#include "../../Include/XAUUSD_AI_Trader/Config.mqh"
#include "../../Include/XAUUSD_AI_Trader/Utils/Logger.mqh"
#include "../../Include/XAUUSD_AI_Trader/Database/DBManager.mqh"
#include "../../Include/XAUUSD_AI_Trader/Data/DataFetcher.mqh"
#include "../../Include/XAUUSD_AI_Trader/Risk/RiskManager.mqh"
#include "../../Include/XAUUSD_AI_Trader/Strategies/LiquiditySweep.mqh"
#include "../../Include/XAUUSD_AI_Trader/Strategies/TrendContinuation.mqh"
#include "../../Include/XAUUSD_AI_Trader/Strategies/Breakout.mqh"
#include "../../Include/XAUUSD_AI_Trader/Strategies/Momentum.mqh"
#include "../../Include/XAUUSD_AI_Trader/Intelligence/Backtester.mqh"
#include "../../Include/XAUUSD_AI_Trader/Intelligence/Optimizer.mqh"
#include "../../Include/XAUUSD_AI_Trader/Intelligence/StrategyMonitor.mqh"
#include "../../Include/XAUUSD_AI_Trader/Execution/TradeExecutor.mqh"
#include "../../Include/XAUUSD_AI_Trader/Alerts/TelegramBot.mqh"

//--- Additional Telegram inputs (exposed in EA settings panel)
input string InpTelegramToken  = "YOUR_BOT_TOKEN";
input string InpTelegramChatID = "YOUR_CHAT_ID";

//--- Module instances
CLogger*          g_logger   = NULL;   // also assigned to global g_Logger
CDBManager*       g_db       = NULL;
CDataFetcher*     g_fetcher  = NULL;
CRiskManager*     g_risk     = NULL;
CTelegramBot*     g_telegram = NULL;
CBacktester*      g_bt       = NULL;
COptimizer*       g_opt      = NULL;
CStrategyMonitor* g_monitor  = NULL;
CTradeExecutor*   g_exec     = NULL;

CLiquiditySweep*    g_ls  = NULL;
CTrendContinuation* g_tc  = NULL;
CBreakout*          g_bo  = NULL;
CMomentum*          g_mom = NULL;

//--- State
datetime g_lastDataRefresh     = 0;
datetime g_lastDailyOptimize   = 0;
datetime g_lastDailyReport     = 0;
bool     g_dailyReportSentToday = false;
datetime g_lastBarTime          = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   //--- Logger
   g_logger = new CLogger();
   if(!g_logger.Init(LOG_FILE))
   {
      Print("CRITICAL: Logger init failed");
      return INIT_FAILED;
   }
   g_Logger = g_logger;   // set global pointer used by LogInfo etc.
   LogInfo("EA", "=== XAUUSD AI Trader v1.00 Starting ===");

   //--- Database
   g_db = new CDBManager();
   if(!g_db.Init())
   {
      LogError("EA", "DBManager init failed");
      return INIT_FAILED;
   }

   //--- Telegram
   g_telegram = new CTelegramBot();
   g_telegram.Init(InpTelegramToken, InpTelegramChatID);

   //--- Risk Manager
   g_risk = new CRiskManager();
   g_risk.Init();

   //--- Data Fetcher
   g_fetcher = new CDataFetcher();
   if(!g_fetcher.Init())
   {
      LogError("EA", "DataFetcher init failed");
      g_telegram.SendRiskAlert("INIT FAILED", "DataFetcher could not load market data.");
      return INIT_FAILED;
   }

   //--- Strategies
   g_ls  = new CLiquiditySweep();    g_ls.Init();
   g_tc  = new CTrendContinuation();
   g_bo  = new CBreakout();
   g_mom = new CMomentum();
   if(!g_mom.Init())
   {
      LogError("EA", "Momentum strategy indicator init failed");
      return INIT_FAILED;
   }

   g_ls.SetDataFetcher(g_fetcher);
   g_tc.SetDataFetcher(g_fetcher);
   g_bo.SetDataFetcher(g_fetcher);
   g_mom.SetDataFetcher(g_fetcher);

   g_ls.SetEnabled(UseStrategyLiquiditySweep);
   g_tc.SetEnabled(UseStrategyTrendContinuation);
   g_bo.SetEnabled(UseStrategyBreakout);
   g_mom.SetEnabled(UseStrategyMomentum);

   //--- Intelligence
   g_bt      = new CBacktester();
   g_opt     = new COptimizer();    g_opt.Init(g_bt);
   g_monitor = new CStrategyMonitor(); g_monitor.Init(g_db);

   //--- Apply saved optimal parameters if they exist
   ApplyOptimizedParams();

   //--- Executor
   g_exec = new CTradeExecutor();
   g_exec.Init(g_risk, g_db);

   //--- 15-second timer (we gate data refresh internally to 15-min intervals)
   EventSetTimer(15);

   g_telegram.SendStartupMessage();
   LogInfo("EA", "Initialization complete. Timer active.");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();

   string reasonStr = IntegerToString(reason);
   g_telegram.SendShutdownMessage("Deinit reason=" + reasonStr);

   //--- Cleanup (reverse order)
   if(g_mom)      { g_mom.Deinit();     delete g_mom;     g_mom     = NULL; }
   if(g_bo)       { delete g_bo;        g_bo      = NULL; }
   if(g_tc)       { delete g_tc;        g_tc      = NULL; }
   if(g_ls)       { delete g_ls;        g_ls      = NULL; }
   if(g_exec)     { delete g_exec;      g_exec    = NULL; }
   if(g_monitor)  { delete g_monitor;   g_monitor = NULL; }
   if(g_opt)      { delete g_opt;       g_opt     = NULL; }
   if(g_bt)       { delete g_bt;        g_bt      = NULL; }
   if(g_fetcher)  { g_fetcher.Deinit(); delete g_fetcher; g_fetcher = NULL; }
   if(g_risk)     { delete g_risk;      g_risk    = NULL; }
   if(g_telegram) { delete g_telegram;  g_telegram= NULL; }
   if(g_db)       { delete g_db;        g_db      = NULL; }

   if(g_logger)   { g_logger.Deinit(); delete g_logger; g_logger = NULL; g_Logger = NULL; }
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(!g_risk || !g_fetcher) return;
   g_risk.Update();

   // Emergency close if daily loss limit just triggered
   if(g_risk.IsDailyLimitHit())
   {
      static bool limitAlertSent = false;
      if(!limitAlertSent)
      {
         g_exec.CloseAllPositions("Daily loss limit hit");
         g_telegram.SendRiskAlert("DAILY LOSS LIMIT",
            StringFormat("Trading halted. Loss=%.2f%% of daily balance.",
                         MathAbs(g_risk.GetDailyLossPct())));
         limitAlertSent = true;
      }
      return;
   }

   // Re-arm when a new day resets the limit
   static datetime lastLimitDay = 0;
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt); dt.hour=0; dt.min=0; dt.sec=0;
   datetime today = StructToTime(dt);
   if(today != lastLimitDay) { lastLimitDay = today; }
}

//+------------------------------------------------------------------+
void OnTimer()
{
   if(!g_fetcher || !g_risk || !g_exec) return;

   g_risk.Update();

   datetime now = TimeGMT();

   //--- 15-minute data refresh + strategy analysis
   if(now - g_lastDataRefresh >= DATA_FETCH_INTERVAL)
   {
      g_lastDataRefresh = now;
      if(g_fetcher.Refresh())
         RunStrategyAnalysis();
      else
         LogWarning("EA", "Data refresh failed — skipping analysis cycle");
   }

   //--- Daily optimization (run once per day at a fixed offset from midnight)
   MqlDateTime dt;
   TimeToStruct(now, dt);
   datetime todayMidnight;
   MqlDateTime td; td = dt; td.hour=0; td.min=0; td.sec=0;
   todayMidnight = StructToTime(td);

   if(now - g_lastDailyOptimize >= 86400 || g_lastDailyOptimize == 0)
   {
      // Run only if at least 1 hour past midnight to ensure enough data
      if(dt.hour >= 1)
      {
         g_lastDailyOptimize = now;
         RunDailyOptimization();
      }
   }

   //--- Daily Telegram report at 23:00 UTC
   if(dt.hour == REPORT_HOUR && dt.min >= REPORT_MINUTE && !g_dailyReportSentToday)
   {
      SendDailyReport();
      g_dailyReportSentToday = true;
   }
   // Reset report flag at midnight
   if(dt.hour == 0) g_dailyReportSentToday = false;
}

//+------------------------------------------------------------------+
//| Run all enabled strategies and attempt execution                 |
//+------------------------------------------------------------------+
void RunStrategyAnalysis()
{
   if(g_risk.IsDailyLimitHit() || g_risk.IsCircuitBreakerActive()) return;

   CBaseStrategy* strategies[4];
   strategies[0] = g_ls;
   strategies[1] = g_tc;
   strategies[2] = g_bo;
   strategies[3] = g_mom;

   for(int i = 0; i < 4; i++)
   {
      if(!strategies[i].IsEnabled()) continue;

      // Sync with StrategyMonitor
      if(!g_monitor.IsEnabled(strategies[i].GetName()))
      {
         strategies[i].SetEnabled(false);
         continue;
      }

      STradeSignal sig = strategies[i].Analyze();
      if(!sig.isValid)   continue;

      double lots = g_risk.CalcLotSize(sig.entryPrice, sig.stopLoss);
      bool   sent = g_exec.Execute(sig);

      if(sent)
         g_telegram.SendSignalAlert(sig, lots);
   }
}

//+------------------------------------------------------------------+
//| Daily optimization and health check                              |
//+------------------------------------------------------------------+
void RunDailyOptimization()
{
   LogInfo("EA", "=== Daily Optimization Starting ===");

   SOptParams optParams[];
   g_opt.OptimizeAll(optParams);
   ApplyOptimizedParams();

   SBacktestResult btResults[];
   g_bt.RunAllStrategies(btResults);
   g_monitor.UpdateFromBacktest(btResults, ArraySize(btResults));

   // Persist backtest results
   for(int i = 0; i < ArraySize(btResults); i++)
   {
      SBacktestRecord rec;
      rec.runDate        = TimeGMT();
      rec.strategy       = btResults[i].strategy;
      rec.totalTrades    = btResults[i].totalTrades;
      rec.winRate        = btResults[i].winRate;
      rec.profitFactor   = btResults[i].profitFactor;
      rec.maxDrawdownPct = btResults[i].maxDrawdownPct;
      rec.score          = btResults[i].score;
      rec.strategyEnabled = g_monitor.IsEnabled(btResults[i].strategy);
      rec.params         = "";
      g_db.LogBacktest(rec);
   }

   LogInfo("EA", "=== Daily Optimization Complete ===");
}

//+------------------------------------------------------------------+
//| Push best optimizer params into live strategy objects            |
//+------------------------------------------------------------------+
void ApplyOptimizedParams()
{
   SOptParams p;
   if(g_opt.LoadParams("LiquiditySweep", p))
      g_ls.SetParams(p.lookback, LS_EqualLevelTol, p.slMulti, p.tpMulti);

   if(g_opt.LoadParams("TrendContinuation", p))
      g_tc.SetParams(p.lookback, p.slMulti, p.tpMulti, TC_PullbackBars);

   if(g_opt.LoadParams("Breakout", p))
      g_bo.SetParams(p.lookback, BO_ATR_ConsolThr, p.slMulti, p.tpMulti, BO_VolumeLookback);

   if(g_opt.LoadParams("Momentum", p))
      g_mom.SetParams(p.rsiPeriod, MOM_RSI_OB, MOM_RSI_OS, p.slMulti, p.tpMulti, MOM_FVG_Lookback);
}

//+------------------------------------------------------------------+
//| Send 23:00 UTC daily Telegram summary                            |
//+------------------------------------------------------------------+
void SendDailyReport()
{
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   MqlDateTime startDt = dt;
   startDt.hour = 0; startDt.min = 0; startDt.sec = 0;
   datetime dayStart = StructToTime(startDt);

   STradeRecord trades[];
   int n = g_db.LoadTradesForDate(dayStart, TimeGMT(), trades);

   int    wins   = 0;
   double pnl    = 0.0;
   for(int i = 0; i < n; i++)
   {
      pnl += trades[i].pnl;
      if(trades[i].isWin) wins++;
   }

   g_telegram.SendDailySummary(n, wins, pnl,
                                g_risk.GetDailyLossPct(),
                                g_monitor.BuildSummary());
}

//+------------------------------------------------------------------+
//| Track closed positions to log and notify                         |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult  &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal_type != DEAL_TYPE_BUY && trans.deal_type != DEAL_TYPE_SELL) return;

   // Only log closing deals (DEAL_ENTRY_OUT)
   CDealInfo deal;
   if(!deal.SelectByIndex(HistoryDealGetTicket(0))) return;
   if(deal.Entry() != DEAL_ENTRY_OUT) return;
   if(deal.Magic() != EA_MAGIC) return;

   g_exec.OnPositionClosed(
      deal.Ticket(),
      deal.Comment(),
      deal.Price(),        // exit price
      deal.Price(),
      0, 0,               // SL/TP not available directly here
      deal.Volume(),
      deal.DealType() == DEAL_TYPE_BUY,
      deal.Time());

   // Notify Telegram
   double pnl = deal.Profit();
   g_telegram.SendTradeResult(
      deal.Comment(),
      deal.DealType() == DEAL_TYPE_BUY,
      0, deal.Price(), pnl, pnl > 0);

   // Check circuit breaker state after close
   if(g_risk.IsCircuitBreakerActive())
      g_telegram.SendRiskAlert("CIRCUIT BREAKER",
         StringFormat("3 consecutive losses. Trading paused until %s UTC.",
                      TimeToString(g_risk.GetCircuitBreakerUntil(),
                                   TIME_DATE | TIME_SECONDS)));
}

//+------------------------------------------------------------------+
//| Chart event: manual commands via EA comment field                |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
   // Placeholder for dashboard interaction (e.g. object click to reset CB)
}
