//+------------------------------------------------------------------+
//| Backtester.mqh — Vectorized rolling 30-day backtest engine       |
//|                                                                  |
//| Runs a fast bar-by-bar simulation on historical M15 data using   |
//| the same signal logic as the live strategy objects.              |
//| Results feed into StrategyMonitor and Optimizer.                 |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Data/DataFetcher.mqh"
#include "../Database/DBManager.mqh"
#include "../Utils/Logger.mqh"

struct SBacktestResult
{
   string strategy;
   int    totalTrades;
   int    wins;
   int    losses;
   double winRate;
   double grossProfit;
   double grossLoss;
   double profitFactor;
   double maxDrawdownPct;
   double score;            // composite: 0.4*WR + 0.4*PF_norm + 0.2*(1-DD_norm)
};

//--- Minimal bar context for simulation
struct SSimBar
{
   double open, high, low, close;
   long   volume;
};

class CBacktester
{
private:
   //--- Score a strategy result into [0,1]
   double ComputeScore(const SBacktestResult &r)
   {
      // Win rate component (40%)
      double wrComp = MathMin(r.winRate, 1.0);

      // Profit factor component (40%): normalize; PF=1.5 maps to ~0.5, PF=3 maps to 1.0
      double pfComp = MathMin(MathMax((r.profitFactor - 1.0) / 2.0, 0.0), 1.0);

      // Drawdown component (20%): lower DD = higher score
      double ddComp = MathMax(1.0 - r.maxDrawdownPct / 20.0, 0.0);

      return 0.40 * wrComp + 0.40 * pfComp + 0.20 * ddComp;
   }

   //--- Load historical M15 bars from the broker for the lookback window
   int LoadHistoricalBars(SSimBar &bars[], int daysBack)
   {
      datetime fromTime = TimeCurrent() - (datetime)(daysBack * 86400);
      MqlRates rates[];
      ArraySetAsSeries(rates, false);  // chronological for simulation
      int copied = CopyRates(EA_SYMBOL, TF_ENTRY, fromTime, TimeCurrent(), rates);
      if(copied <= 0)
      {
         LogError("Backtester", StringFormat("CopyRates failed: %d", GetLastError()));
         return 0;
      }
      ArrayResize(bars, copied);
      for(int i = 0; i < copied; i++)
      {
         bars[i].open   = rates[i].open;
         bars[i].high   = rates[i].high;
         bars[i].low    = rates[i].low;
         bars[i].close  = rates[i].close;
         bars[i].volume = rates[i].tick_volume;
      }
      return copied;
   }

   //--- Inline ATR over the last `period` bars at position `pos` in chronological array
   double InlineATR(const SSimBar &bars[], int pos, int period)
   {
      if(pos < period) return 0.0;
      double sum = 0.0;
      for(int i = pos - period; i < pos; i++)
      {
         double tr = MathMax(bars[i].high - bars[i].low,
                    MathMax(MathAbs(bars[i].high - bars[i - 1].close),
                            MathAbs(bars[i].low  - bars[i - 1].close)));
         sum += tr;
      }
      return sum / period;
   }

   //--- Generic trade simulation loop shared by all strategies
   //    signalDir: +1=BUY, -1=SELL, 0=no trade
   //    Uses fixed ATR-based SL/TP multipliers passed in
   SBacktestResult SimulateTrades(const SSimBar &bars[], int n,
                                   const int signals[],
                                   const double slLevels[], const double tpLevels[],
                                   string stratName)
   {
      SBacktestResult r;
      r.strategy     = stratName;
      r.totalTrades  = 0;
      r.wins         = 0;
      r.losses       = 0;
      r.grossProfit  = 0.0;
      r.grossLoss    = 0.0;

      double equity = 10000.0;  // normalized starting equity for scoring
      double peak   = equity;
      double maxDD  = 0.0;

      bool   inTrade = false;
      int    tradeDir = 0;
      double sl = 0, tp = 0, entry = 0;
      double riskPer = equity * RISK_PERCENT_PER_TRADE / 100.0;

      for(int i = ATR_PERIOD + 1; i < n; i++)
      {
         if(!inTrade && signals[i] != 0)
         {
            inTrade  = true;
            tradeDir = signals[i];
            entry    = (tradeDir == 1) ? bars[i].close : bars[i].close;
            sl       = slLevels[i];
            tp       = tpLevels[i];
            double risk = MathAbs(entry - sl);
            if(risk <= 0) { inTrade = false; continue; }
            riskPer = equity * RISK_PERCENT_PER_TRADE / 100.0;
            r.totalTrades++;
            continue;
         }

         if(inTrade)
         {
            bool hitSL = false, hitTP = false;
            if(tradeDir == 1)
            {
               hitSL = (bars[i].low  <= sl);
               hitTP = (bars[i].high >= tp);
            }
            else
            {
               hitSL = (bars[i].high >= sl);
               hitTP = (bars[i].low  <= tp);
            }

            if(hitTP || hitSL)
            {
               double pnl;
               if(hitTP) { pnl = riskPer * MIN_RR_RATIO; r.wins++; r.grossProfit += pnl; }
               else       { pnl = -riskPer;               r.losses++;r.grossLoss  += MathAbs(pnl); }

               equity += pnl;
               if(equity > peak) peak = equity;
               double dd = (peak - equity) / peak * 100.0;
               if(dd > maxDD) maxDD = dd;
               inTrade = false;
            }
         }
      }

      r.winRate        = (r.totalTrades > 0) ? (double)r.wins / r.totalTrades : 0.0;
      r.profitFactor   = (r.grossLoss  > 0)  ? r.grossProfit / r.grossLoss    : (r.grossProfit > 0 ? 99.0 : 0.0);
      r.maxDrawdownPct = maxDD;
      r.score          = ComputeScore(r);
      return r;
   }

   //--- Generate signals for Liquidity Sweep strategy on historical data
   void GenerateLSSignals(const SSimBar &bars[], int n,
                          double slMulti, double tpMulti, int lookback, double tolPip,
                          int &signals[], double &slLevels[], double &tpLevels[])
   {
      ArrayResize(signals,  n); ArrayInitialize(signals,  0);
      ArrayResize(slLevels, n); ArrayInitialize(slLevels, 0);
      ArrayResize(tpLevels, n); ArrayInitialize(tpLevels, 0);

      for(int i = lookback + 5; i < n - 1; i++)
      {
         double atr = InlineATR(bars, i, ATR_PERIOD);
         if(atr <= 0) continue;

         // Find swing lows and highs
         double swingLow = 1e10, swingHigh = 0;
         for(int k = i - lookback; k < i; k++)
         {
            if(bars[k].low  < swingLow)  swingLow  = bars[k].low;
            if(bars[k].high > swingHigh) swingHigh = bars[k].high;
         }

         SSimBar prev = bars[i - 1];
         SSimBar cur  = bars[i];

         // Bullish sweep (swept low, closes above)
         if(prev.low < swingLow && prev.close > swingLow && cur.close > prev.close)
         {
            signals[i]  = 1;
            slLevels[i] = prev.low - atr * slMulti;
            tpLevels[i] = cur.close + (cur.close - slLevels[i]) * tpMulti;
         }
         // Bearish sweep (swept high, closes below)
         else if(prev.high > swingHigh && prev.close < swingHigh && cur.close < prev.close)
         {
            signals[i]  = -1;
            slLevels[i] = prev.high + atr * slMulti;
            tpLevels[i] = cur.close - (slLevels[i] - cur.close) * tpMulti;
         }
      }
   }

   //--- Generate signals for Trend Continuation (simplified proxy)
   void GenerateTCSignals(const SSimBar &bars[], int n,
                          double slMulti, double tpMulti, int obLookback,
                          int &signals[], double &slLevels[], double &tpLevels[])
   {
      ArrayResize(signals,  n); ArrayInitialize(signals,  0);
      ArrayResize(slLevels, n); ArrayInitialize(slLevels, 0);
      ArrayResize(tpLevels, n); ArrayInitialize(tpLevels, 0);

      for(int i = obLookback + 5; i < n - 1; i++)
      {
         double atr = InlineATR(bars, i, ATR_PERIOD);
         if(atr <= 0) continue;

         // HTF proxy: 20-bar SMA slope
         double smaNew = 0, smaOld = 0;
         for(int k = i - 10; k < i; k++) smaNew += bars[k].close;
         for(int k = i - 20; k < i - 10; k++) smaOld += bars[k].close;
         smaNew /= 10.0; smaOld /= 10.0;

         bool bullHTF = (smaNew > smaOld * 1.001);
         bool bearHTF = (smaNew < smaOld * 0.999);

         // Find OB: last down candle before a strong up candle
         if(bullHTF && bars[i].close < bars[i - 1].close)  // pullback
         {
            // Look for prior OB
            for(int k = i - 3; k >= MathMax(0, i - obLookback); k--)
            {
               bool isOB = (bars[k].close < bars[k].open) &&
                           (k + 1 < n) &&
                           (bars[k + 1].close > bars[k].high);
               if(isOB && bars[i].low <= bars[k].open && bars[i].close > bars[k].close)
               {
                  signals[i]  = 1;
                  slLevels[i] = bars[k].close - atr * slMulti;
                  tpLevels[i] = bars[i].close + (bars[i].close - slLevels[i]) * tpMulti;
                  break;
               }
            }
         }
         if(bearHTF && bars[i].close > bars[i - 1].close) // pullback
         {
            for(int k = i - 3; k >= MathMax(0, i - obLookback); k--)
            {
               bool isOB = (bars[k].close > bars[k].open) &&
                           (k + 1 < n) &&
                           (bars[k + 1].close < bars[k].low);
               if(isOB && bars[i].high >= bars[k].open && bars[i].close < bars[k].close)
               {
                  signals[i]  = -1;
                  slLevels[i] = bars[k].close + atr * slMulti;
                  tpLevels[i] = bars[i].close - (slLevels[i] - bars[i].close) * tpMulti;
                  break;
               }
            }
         }
      }
   }

   //--- Breakout signals on historical data
   void GenerateBOSignals(const SSimBar &bars[], int n,
                          double slMulti, double tpMulti, int consolidBars,
                          int &signals[], double &slLevels[], double &tpLevels[])
   {
      ArrayResize(signals,  n); ArrayInitialize(signals,  0);
      ArrayResize(slLevels, n); ArrayInitialize(slLevels, 0);
      ArrayResize(tpLevels, n); ArrayInitialize(tpLevels, 0);

      for(int i = consolidBars + ATR_PERIOD + 2; i < n - 1; i++)
      {
         double atr  = InlineATR(bars, i, ATR_PERIOD);
         double rAtr = InlineATR(bars, i, consolidBars);
         if(atr <= 0 || rAtr > atr * BO_ATR_ConsolThr) continue;

         double rHigh = 0, rLow = 1e10;
         for(int k = i - consolidBars; k < i; k++)
         {
            if(bars[k].high > rHigh) rHigh = bars[k].high;
            if(bars[k].low  < rLow)  rLow  = bars[k].low;
         }

         SSimBar b = bars[i];
         if(b.close > rHigh && b.close > b.open)
         {
            signals[i]  = 1;
            slLevels[i] = rLow - atr * slMulti;
            tpLevels[i] = b.close + (b.close - slLevels[i]) * tpMulti;
         }
         else if(b.close < rLow && b.close < b.open)
         {
            signals[i]  = -1;
            slLevels[i] = rHigh + atr * slMulti;
            tpLevels[i] = b.close - (slLevels[i] - b.close) * tpMulti;
         }
      }
   }

   //--- Momentum signals on historical data
   void GenerateMOMSignals(const SSimBar &bars[], int n,
                           double slMulti, double tpMulti, int rsiPeriod,
                           int &signals[], double &slLevels[], double &tpLevels[])
   {
      ArrayResize(signals,  n); ArrayInitialize(signals,  0);
      ArrayResize(slLevels, n); ArrayInitialize(slLevels, 0);
      ArrayResize(tpLevels, n); ArrayInitialize(tpLevels, 0);

      // Inline RSI
      double rsi[];
      ArrayResize(rsi, n); ArrayInitialize(rsi, 50);
      if(n <= rsiPeriod) return;
      double gain = 0, loss = 0;
      for(int i = 1; i <= rsiPeriod; i++)
      {
         double d = bars[i].close - bars[i - 1].close;
         gain += (d > 0 ? d : 0); loss += (d < 0 ? -d : 0);
      }
      gain /= rsiPeriod; loss /= rsiPeriod;
      rsi[rsiPeriod] = (loss == 0) ? 100 : 100 - 100 / (1 + gain / loss);
      for(int i = rsiPeriod + 1; i < n; i++)
      {
         double d = bars[i].close - bars[i - 1].close;
         gain = (gain * (rsiPeriod - 1) + (d > 0 ? d : 0)) / rsiPeriod;
         loss = (loss * (rsiPeriod - 1) + (d < 0 ? -d : 0)) / rsiPeriod;
         rsi[i] = (loss == 0) ? 100 : 100 - 100 / (1 + gain / loss);
      }

      for(int i = rsiPeriod + 5; i < n - 1; i++)
      {
         double atr = InlineATR(bars, i, ATR_PERIOD);
         if(atr <= 0) continue;
         SSimBar b = bars[i];

         // Bullish: RSI rising from OS
         if(rsi[i] > rsi[i - 1] && rsi[i - 2] < MOM_RSI_OS && b.close > b.open)
         {
            double swLow = b.low;
            for(int k = MathMax(0, i - 10); k < i; k++)
               if(bars[k].low < swLow) swLow = bars[k].low;
            signals[i]  = 1;
            slLevels[i] = swLow - atr * slMulti;
            tpLevels[i] = b.close + (b.close - slLevels[i]) * tpMulti;
         }
         // Bearish: RSI falling from OB
         else if(rsi[i] < rsi[i - 1] && rsi[i - 2] > MOM_RSI_OB && b.close < b.open)
         {
            double swHigh = b.high;
            for(int k = MathMax(0, i - 10); k < i; k++)
               if(bars[k].high > swHigh) swHigh = bars[k].high;
            signals[i]  = -1;
            slLevels[i] = swHigh + atr * slMulti;
            tpLevels[i] = b.close - (slLevels[i] - b.close) * tpMulti;
         }
      }
   }

public:
   //--- Run all four strategies for the last 30 days and return results
   int RunAllStrategies(SBacktestResult &results[],
                        double lsSlM=LS_SL_ATR_Multi,   double lsTpM=LS_TP_ATR_Multi,
                        int    lsLkb=LS_LiquidityLookback,
                        double tcSlM=TC_SL_ATR_Multi,   double tcTpM=TC_TP_ATR_Multi,
                        int    tcLkb=TC_OB_Lookback,
                        double boSlM=BO_SL_ATR_Multi,   double boTpM=BO_TP_ATR_Multi,
                        int    boLkb=BO_ConsolidationBars,
                        double moSlM=MOM_SL_ATR_Multi,  double moTpM=MOM_TP_ATR_Multi,
                        int    moRsi=MOM_RSI_Period)
   {
      SSimBar bars[];
      int n = LoadHistoricalBars(bars, OPT_BACKTEST_DAYS);
      if(n < 100)
      {
         LogError("Backtester", "Insufficient historical bars for backtest");
         ArrayResize(results, 0);
         return 0;
      }

      ArrayResize(results, 4);

      int sigs[]; double slLvl[], tpLvl[];

      GenerateLSSignals(bars, n, lsSlM, lsTpM, lsLkb, LS_EqualLevelTol * 0.0001,
                        sigs, slLvl, tpLvl);
      results[0] = SimulateTrades(bars, n, sigs, slLvl, tpLvl, "LiquiditySweep");

      GenerateTCSignals(bars, n, tcSlM, tcTpM, tcLkb, sigs, slLvl, tpLvl);
      results[1] = SimulateTrades(bars, n, sigs, slLvl, tpLvl, "TrendContinuation");

      GenerateBOSignals(bars, n, boSlM, boTpM, boLkb, sigs, slLvl, tpLvl);
      results[2] = SimulateTrades(bars, n, sigs, slLvl, tpLvl, "Breakout");

      GenerateMOMSignals(bars, n, moSlM, moTpM, moRsi, sigs, slLvl, tpLvl);
      results[3] = SimulateTrades(bars, n, sigs, slLvl, tpLvl, "Momentum");

      LogInfo("Backtester", StringFormat(
         "Backtest done (%d bars). LS=%.2f TC=%.2f BO=%.2f MOM=%.2f",
         n, results[0].score, results[1].score, results[2].score, results[3].score));

      return 4;
   }

   //--- Run a single strategy with given parameters (used by optimizer)
   SBacktestResult RunSingle(string strategy,
                             double slMulti, double tpMulti,
                             int    lookback, int rsiPeriod = 14)
   {
      SSimBar bars[];
      int n = LoadHistoricalBars(bars, OPT_BACKTEST_DAYS);
      SBacktestResult empty;
      empty.strategy = strategy; empty.score = 0;
      if(n < 100) return empty;

      int sigs[]; double slLvl[], tpLvl[];

      if(strategy == "LiquiditySweep")
         GenerateLSSignals(bars, n, slMulti, tpMulti, lookback, 0.0005, sigs, slLvl, tpLvl);
      else if(strategy == "TrendContinuation")
         GenerateTCSignals(bars, n, slMulti, tpMulti, lookback, sigs, slLvl, tpLvl);
      else if(strategy == "Breakout")
         GenerateBOSignals(bars, n, slMulti, tpMulti, lookback, sigs, slLvl, tpLvl);
      else if(strategy == "Momentum")
         GenerateMOMSignals(bars, n, slMulti, tpMulti, rsiPeriod, sigs, slLvl, tpLvl);
      else
         return empty;

      return SimulateTrades(bars, n, sigs, slLvl, tpLvl, strategy);
   }
};
