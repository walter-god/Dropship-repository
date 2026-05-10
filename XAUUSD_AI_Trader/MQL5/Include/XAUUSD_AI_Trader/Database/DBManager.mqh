//+------------------------------------------------------------------+
//| DBManager.mqh — CSV-based persistence for trades and backtests   |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Utils/Logger.mqh"

//--- Trade record written after each closed position
struct STradeRecord
{
   string   strategy;
   string   direction;        // "BUY" | "SELL"
   double   entryPrice;
   double   exitPrice;
   double   stopLoss;
   double   takeProfit;
   double   lotSize;
   double   pnl;
   double   confidence;
   datetime openTime;
   datetime closeTime;
   bool     isWin;
};

//--- Backtest result per strategy per day
struct SBacktestRecord
{
   datetime runDate;
   string   strategy;
   int      totalTrades;
   double   winRate;
   double   profitFactor;
   double   maxDrawdownPct;
   double   score;
   bool     strategyEnabled;
   // Optimized params stored as serialized string  "key=val;key=val"
   string   params;
};

class CDBManager
{
private:
   string m_tradesFile;
   string m_backtestFile;
   string m_stratStateFile;

   bool AppendRow(string filePath, string row)
   {
      int fh = FileOpen(filePath, FILE_WRITE | FILE_READ | FILE_ANSI | FILE_SHARE_READ | FILE_TXT);
      if(fh == INVALID_HANDLE)
      {
         fh = FileOpen(filePath, FILE_WRITE | FILE_ANSI | FILE_TXT);
         if(fh == INVALID_HANDLE) return false;
      }
      FileSeek(fh, 0, SEEK_END);
      FileWriteString(fh, row + "\n");
      FileClose(fh);
      return true;
   }

   string EscapeCSV(string s)
   {
      // Wrap in quotes if contains comma
      if(StringFind(s, ",") >= 0)
         return "\"" + s + "\"";
      return s;
   }

public:
   CDBManager()
      : m_tradesFile(TRADES_DB_FILE),
        m_backtestFile(BACKTEST_DB_FILE),
        m_stratStateFile(STRATEGY_STATE_FILE) {}

   bool Init()
   {
      // Write headers if files don't exist
      if(!FileIsExist(m_tradesFile))
      {
         string h = "OpenTime,CloseTime,Strategy,Direction,EntryPrice,ExitPrice,"
                    "StopLoss,TakeProfit,LotSize,PnL,Confidence,IsWin";
         AppendRow(m_tradesFile, h);
      }
      if(!FileIsExist(m_backtestFile))
      {
         string h = "RunDate,Strategy,TotalTrades,WinRate,ProfitFactor,"
                    "MaxDrawdownPct,Score,Enabled,Params";
         AppendRow(m_backtestFile, h);
      }
      if(!FileIsExist(m_stratStateFile))
      {
         string h = "Strategy,Enabled,PoorDayStreak,LastScore,LastUpdateDate";
         AppendRow(m_stratStateFile, h);
      }
      LogInfo("DBManager", "Initialized. Files ready.");
      return true;
   }

   bool LogTrade(const STradeRecord &rec)
   {
      string row = StringFormat("%s,%s,%s,%s,%.5f,%.5f,%.5f,%.5f,%.4f,%.2f,%.1f,%d",
                                TimeToString(rec.openTime,  TIME_DATE | TIME_SECONDS),
                                TimeToString(rec.closeTime, TIME_DATE | TIME_SECONDS),
                                EscapeCSV(rec.strategy),
                                rec.direction,
                                rec.entryPrice,
                                rec.exitPrice,
                                rec.stopLoss,
                                rec.takeProfit,
                                rec.lotSize,
                                rec.pnl,
                                rec.confidence,
                                rec.isWin ? 1 : 0);
      return AppendRow(m_tradesFile, row);
   }

   bool LogBacktest(const SBacktestRecord &rec)
   {
      string row = StringFormat("%s,%s,%d,%.4f,%.4f,%.4f,%.4f,%d,%s",
                                TimeToString(rec.runDate, TIME_DATE),
                                EscapeCSV(rec.strategy),
                                rec.totalTrades,
                                rec.winRate,
                                rec.profitFactor,
                                rec.maxDrawdownPct,
                                rec.score,
                                rec.strategyEnabled ? 1 : 0,
                                EscapeCSV(rec.params));
      return AppendRow(m_backtestFile, row);
   }

   //--- Load the last N backtest records for a given strategy
   int LoadRecentBacktests(string strategyName, int maxRecords, SBacktestRecord &out[])
   {
      ArrayResize(out, 0);
      int fh = FileOpen(m_backtestFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh == INVALID_HANDLE) return 0;

      // Skip header
      if(!FileIsEnding(fh)) FileReadString(fh);

      SBacktestRecord tmp[];
      ArrayResize(tmp, 0);

      while(!FileIsEnding(fh))
      {
         string dateStr    = FileReadString(fh);
         string strat      = FileReadString(fh);
         int    trades     = (int)StringToInteger(FileReadString(fh));
         double winRate    = StringToDouble(FileReadString(fh));
         double pf         = StringToDouble(FileReadString(fh));
         double dd         = StringToDouble(FileReadString(fh));
         double score      = StringToDouble(FileReadString(fh));
         bool   enabled    = StringToInteger(FileReadString(fh)) == 1;
         string params     = FileReadString(fh);

         if(strat == strategyName || strategyName == "")
         {
            int idx = ArraySize(tmp);
            ArrayResize(tmp, idx + 1);
            tmp[idx].runDate        = StringToTime(dateStr);
            tmp[idx].strategy       = strat;
            tmp[idx].totalTrades    = trades;
            tmp[idx].winRate        = winRate;
            tmp[idx].profitFactor   = pf;
            tmp[idx].maxDrawdownPct = dd;
            tmp[idx].score          = score;
            tmp[idx].strategyEnabled = enabled;
            tmp[idx].params         = params;
         }
      }
      FileClose(fh);

      // Return last maxRecords
      int total = ArraySize(tmp);
      int start = MathMax(0, total - maxRecords);
      int count = total - start;
      ArrayResize(out, count);
      for(int i = 0; i < count; i++)
         out[i] = tmp[start + i];

      return count;
   }

   //--- Load trades for a date range (for daily reporting)
   int LoadTradesForDate(datetime fromTime, datetime toTime, STradeRecord &out[])
   {
      ArrayResize(out, 0);
      int fh = FileOpen(m_tradesFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh == INVALID_HANDLE) return 0;

      // Skip header
      if(!FileIsEnding(fh)) FileReadString(fh);

      while(!FileIsEnding(fh))
      {
         string openStr   = FileReadString(fh);
         string closeStr  = FileReadString(fh);
         string strat     = FileReadString(fh);
         string dir       = FileReadString(fh);
         double entry     = StringToDouble(FileReadString(fh));
         double exitP     = StringToDouble(FileReadString(fh));
         double sl        = StringToDouble(FileReadString(fh));
         double tp        = StringToDouble(FileReadString(fh));
         double lot       = StringToDouble(FileReadString(fh));
         double pnl       = StringToDouble(FileReadString(fh));
         double conf      = StringToDouble(FileReadString(fh));
         bool   win       = StringToInteger(FileReadString(fh)) == 1;

         datetime ot = StringToTime(openStr);
         datetime ct = StringToTime(closeStr);

         if(ct >= fromTime && ct <= toTime)
         {
            int idx = ArraySize(out);
            ArrayResize(out, idx + 1);
            out[idx].openTime   = ot;
            out[idx].closeTime  = ct;
            out[idx].strategy   = strat;
            out[idx].direction  = dir;
            out[idx].entryPrice = entry;
            out[idx].exitPrice  = exitP;
            out[idx].stopLoss   = sl;
            out[idx].takeProfit = tp;
            out[idx].lotSize    = lot;
            out[idx].pnl        = pnl;
            out[idx].confidence = conf;
            out[idx].isWin      = win;
         }
      }
      FileClose(fh);
      return ArraySize(out);
   }

   //--- Persist strategy enabled/disabled state + poor-day streak
   bool SaveStrategyState(string strategy, bool enabled, int poorDayStreak,
                          double lastScore, datetime lastUpdate)
   {
      // Rewrite the entire state file (small, only 4 strategies)
      string lines[];
      int fh = FileOpen(m_stratStateFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh != INVALID_HANDLE)
      {
         if(!FileIsEnding(fh)) FileReadString(fh); // skip header
         while(!FileIsEnding(fh))
         {
            string s  = FileReadString(fh);
            string en = FileReadString(fh);
            string ps = FileReadString(fh);
            string ls = FileReadString(fh);
            string lu = FileReadString(fh);
            if(s == strategy) continue; // will be replaced
            int idx = ArraySize(lines);
            ArrayResize(lines, idx + 1);
            lines[idx] = StringFormat("%s,%s,%s,%s,%s", s, en, ps, ls, lu);
         }
         FileClose(fh);
      }

      fh = FileOpen(m_stratStateFile, FILE_WRITE | FILE_ANSI | FILE_TXT);
      if(fh == INVALID_HANDLE) return false;
      FileWriteString(fh, "Strategy,Enabled,PoorDayStreak,LastScore,LastUpdateDate\n");
      for(int i = 0; i < ArraySize(lines); i++)
         FileWriteString(fh, lines[i] + "\n");
      // Write updated row
      FileWriteString(fh, StringFormat("%s,%d,%d,%.4f,%s\n",
                                       strategy,
                                       enabled ? 1 : 0,
                                       poorDayStreak,
                                       lastScore,
                                       TimeToString(lastUpdate, TIME_DATE)));
      FileClose(fh);
      return true;
   }

   bool LoadStrategyState(string strategy, bool &enabled, int &poorDayStreak,
                          double &lastScore, datetime &lastUpdate)
   {
      int fh = FileOpen(m_stratStateFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
      if(fh == INVALID_HANDLE) return false;
      if(!FileIsEnding(fh)) FileReadString(fh); // skip header
      while(!FileIsEnding(fh))
      {
         string s  = FileReadString(fh);
         bool   en = StringToInteger(FileReadString(fh)) == 1;
         int    ps = (int)StringToInteger(FileReadString(fh));
         double ls = StringToDouble(FileReadString(fh));
         datetime lu = StringToTime(FileReadString(fh));
         if(s == strategy)
         {
            enabled       = en;
            poorDayStreak = ps;
            lastScore     = ls;
            lastUpdate    = lu;
            FileClose(fh);
            return true;
         }
      }
      FileClose(fh);
      return false;
   }
};
