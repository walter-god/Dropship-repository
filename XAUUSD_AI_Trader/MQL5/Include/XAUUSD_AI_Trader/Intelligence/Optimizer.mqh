//+------------------------------------------------------------------+
//| Optimizer.mqh — Grid-search parameter optimizer                  |
//|                                                                  |
//| MQL5 cannot call Python/Optuna directly, so we implement a       |
//| grid-search with OPT_DAILY_TRIALS random-sample trials per       |
//| strategy per day, driven by a random seed that changes daily.    |
//| Best parameter set is persisted to CSV and loaded on startup.    |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Utils/Logger.mqh"
#include "Backtester.mqh"

struct SOptParams
{
   string strategy;
   double slMulti;
   double tpMulti;
   int    lookback;
   int    rsiPeriod;   // Momentum only
   double bestScore;
};

class COptimizer
{
private:
   CBacktester* m_backtester;
   string       m_paramsFile;

   //--- Deterministic pseudo-random sampling
   uint m_seed;
   uint NextRand()
   {
      m_seed = m_seed * 1664525u + 1013904223u;
      return m_seed;
   }
   double RandDouble(double lo, double hi)
   {
      return lo + (double)(NextRand() % 100000) / 100000.0 * (hi - lo);
   }
   int RandInt(int lo, int hi)
   {
      return lo + (int)(NextRand() % (uint)(hi - lo + 1));
   }

   void SaveParams(const SOptParams &p)
   {
      // Append or update: read all, replace row for strategy, rewrite
      string lines[];
      int fh = FileOpen(m_paramsFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh != INVALID_HANDLE)
      {
         if(!FileIsEnding(fh)) FileReadString(fh); // skip header
         while(!FileIsEnding(fh))
         {
            string s = FileReadString(fh);
            string slM = FileReadString(fh);
            string tpM = FileReadString(fh);
            string lkb = FileReadString(fh);
            string rsi = FileReadString(fh);
            string sc  = FileReadString(fh);
            if(s == p.strategy) continue;
            int idx = ArraySize(lines);
            ArrayResize(lines, idx + 1);
            lines[idx] = s+","+slM+","+tpM+","+lkb+","+rsi+","+sc;
         }
         FileClose(fh);
      }

      fh = FileOpen(m_paramsFile, FILE_WRITE | FILE_ANSI | FILE_TXT);
      if(fh == INVALID_HANDLE) return;
      FileWriteString(fh, "Strategy,SLMulti,TPMulti,Lookback,RSIPeriod,BestScore\n");
      for(int i = 0; i < ArraySize(lines); i++)
         FileWriteString(fh, lines[i] + "\n");
      FileWriteString(fh, StringFormat("%s,%.4f,%.4f,%d,%d,%.4f\n",
                                       p.strategy, p.slMulti, p.tpMulti,
                                       p.lookback, p.rsiPeriod, p.bestScore));
      FileClose(fh);
   }

public:
   COptimizer() : m_backtester(NULL), m_paramsFile(OPTIMIZER_PARAMS_FILE), m_seed(12345) {}

   void Init(CBacktester* bt)
   {
      m_backtester = bt;
      m_seed = (uint)(TimeGMT() & 0xFFFFFF);
      if(!FileIsExist(m_paramsFile))
      {
         int fh = FileOpen(m_paramsFile, FILE_WRITE | FILE_ANSI | FILE_TXT);
         if(fh != INVALID_HANDLE)
         {
            FileWriteString(fh, "Strategy,SLMulti,TPMulti,Lookback,RSIPeriod,BestScore\n");
            FileClose(fh);
         }
      }
      LogInfo("Optimizer", "Initialized. Seed=" + IntegerToString(m_seed));
   }

   //--- Run OPT_DAILY_TRIALS random-sample trials for one strategy
   SOptParams OptimizeStrategy(string strategy)
   {
      SOptParams best;
      best.strategy  = strategy;
      best.bestScore = -1.0;
      best.slMulti   = 1.5;
      best.tpMulti   = 3.0;
      best.lookback  = 30;
      best.rsiPeriod = 14;

      LogInfo("Optimizer", StringFormat("Optimizing %s (%d trials)...",
              strategy, OPT_DAILY_TRIALS));

      for(int t = 0; t < OPT_DAILY_TRIALS; t++)
      {
         double slM  = RandDouble(1.0, 3.0);
         double tpM  = RandDouble(2.0, 5.0);
         int    lkb  = RandInt(15, 60);
         int    rsi  = RandInt(9, 21);

         SBacktestResult r = m_backtester.RunSingle(strategy, slM, tpM, lkb, rsi);
         if(r.score > best.bestScore)
         {
            best.bestScore = r.score;
            best.slMulti   = slM;
            best.tpMulti   = tpM;
            best.lookback  = lkb;
            best.rsiPeriod = rsi;
         }
      }

      SaveParams(best);
      LogInfo("Optimizer", StringFormat(
         "%s best: SL=%.2f TP=%.2f LKB=%d RSI=%d Score=%.4f",
         strategy, best.slMulti, best.tpMulti, best.lookback, best.rsiPeriod, best.bestScore));
      return best;
   }

   //--- Run optimization for all 4 strategies (called once per day)
   void OptimizeAll(SOptParams &results[])
   {
      ArrayResize(results, 4);
      m_seed = (uint)(TimeGMT() & 0xFFFFFF);  // re-seed daily

      string strategies[4] = {"LiquiditySweep", "TrendContinuation", "Breakout", "Momentum"};
      for(int i = 0; i < 4; i++)
         results[i] = OptimizeStrategy(strategies[i]);
   }

   //--- Load best known params for a strategy
   bool LoadParams(string strategy, SOptParams &p)
   {
      int fh = FileOpen(m_paramsFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh == INVALID_HANDLE) return false;
      if(!FileIsEnding(fh)) FileReadString(fh); // skip header
      while(!FileIsEnding(fh))
      {
         string s   = FileReadString(fh);
         double slM = StringToDouble(FileReadString(fh));
         double tpM = StringToDouble(FileReadString(fh));
         int    lkb = (int)StringToInteger(FileReadString(fh));
         int    rsi = (int)StringToInteger(FileReadString(fh));
         double sc  = StringToDouble(FileReadString(fh));
         if(s == strategy)
         {
            p.strategy  = s;
            p.slMulti   = slM;
            p.tpMulti   = tpM;
            p.lookback  = lkb;
            p.rsiPeriod = rsi;
            p.bestScore = sc;
            FileClose(fh);
            return true;
         }
      }
      FileClose(fh);
      return false;
   }
};
