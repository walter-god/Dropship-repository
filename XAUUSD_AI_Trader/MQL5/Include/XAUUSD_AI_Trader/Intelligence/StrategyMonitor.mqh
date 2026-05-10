//+------------------------------------------------------------------+
//| StrategyMonitor.mqh — Health scoring and auto-disable logic      |
//|                                                                  |
//| Each strategy gets a daily score (win rate 40%, profit factor    |
//| 40%, max drawdown 20%). If score < threshold for N consecutive   |
//| days it is automatically disabled. Re-enabled when score recovers|
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Utils/Logger.mqh"
#include "../Database/DBManager.mqh"
#include "Backtester.mqh"

struct SStrategyHealth
{
   string   name;
   bool     enabled;
   double   latestScore;
   int      poorDayStreak;     // consecutive days below threshold
   datetime lastUpdateDate;
};

class CStrategyMonitor
{
private:
   SStrategyHealth m_health[4];
   CDBManager*     m_db;

   static string StrategyName(int i)
   {
      string names[4] = {"LiquiditySweep", "TrendContinuation", "Breakout", "Momentum"};
      return names[i];
   }

   void LoadState()
   {
      for(int i = 0; i < 4; i++)
      {
         bool en; int streak; double score; datetime upd;
         if(m_db.LoadStrategyState(m_health[i].name, en, streak, score, upd))
         {
            m_health[i].enabled       = en;
            m_health[i].poorDayStreak = streak;
            m_health[i].latestScore   = score;
            m_health[i].lastUpdateDate = upd;
         }
      }
   }

   void SaveState(int idx)
   {
      m_db.SaveStrategyState(m_health[idx].name,
                             m_health[idx].enabled,
                             m_health[idx].poorDayStreak,
                             m_health[idx].latestScore,
                             m_health[idx].lastUpdateDate);
   }

public:
   CStrategyMonitor() : m_db(NULL)
   {
      for(int i = 0; i < 4; i++)
      {
         m_health[i].name           = StrategyName(i);
         m_health[i].enabled        = true;
         m_health[i].latestScore    = 0.5;
         m_health[i].poorDayStreak  = 0;
         m_health[i].lastUpdateDate = 0;
      }
   }

   void Init(CDBManager* db)
   {
      m_db = db;
      LoadState();
      LogInfo("StrategyMonitor", "State loaded for all strategies.");
   }

   //--- Called once per day after backtesting
   //    results[] must match the fixed order: LS, TC, BO, MOM
   void UpdateFromBacktest(const SBacktestResult &results[], int count)
   {
      for(int i = 0; i < MathMin(count, 4); i++)
      {
         m_health[i].latestScore    = results[i].score;
         m_health[i].lastUpdateDate = TimeGMT();

         bool scorePoor = (results[i].score < OPT_SCORE_THRESHOLD);

         if(scorePoor)
         {
            m_health[i].poorDayStreak++;
            LogWarning("StrategyMonitor", StringFormat(
               "%s poor score=%.3f streak=%d",
               m_health[i].name, results[i].score, m_health[i].poorDayStreak));

            if(m_health[i].poorDayStreak >= OPT_DISABLE_STREAK && m_health[i].enabled)
            {
               m_health[i].enabled = false;
               LogWarning("StrategyMonitor", StringFormat(
                  "AUTO-DISABLED: %s after %d consecutive poor days",
                  m_health[i].name, OPT_DISABLE_STREAK));
            }
         }
         else
         {
            // Score recovered — reset streak and re-enable
            if(!m_health[i].enabled && results[i].score >= OPT_SCORE_THRESHOLD + 0.1)
            {
               m_health[i].enabled      = true;
               m_health[i].poorDayStreak = 0;
               LogInfo("StrategyMonitor", StringFormat(
                  "AUTO-ENABLED: %s score recovered to %.3f",
                  m_health[i].name, results[i].score));
            }
            else
            {
               m_health[i].poorDayStreak = 0;
            }
         }
         SaveState(i);
      }
   }

   //--- Query current enabled status
   bool IsEnabled(string strategyName)
   {
      for(int i = 0; i < 4; i++)
         if(m_health[i].name == strategyName)
            return m_health[i].enabled;
      return false;
   }

   double GetScore(string strategyName)
   {
      for(int i = 0; i < 4; i++)
         if(m_health[i].name == strategyName)
            return m_health[i].latestScore;
      return 0.0;
   }

   //--- Build a summary string for Telegram daily report
   string BuildSummary()
   {
      string s = "📊 *Strategy Health*\n";
      for(int i = 0; i < 4; i++)
      {
         string status = m_health[i].enabled ? "✅ ON" : "❌ OFF";
         s += StringFormat("  %s: %s | Score=%.3f | Streak=%d\n",
                           m_health[i].name,
                           status,
                           m_health[i].latestScore,
                           m_health[i].poorDayStreak);
      }
      return s;
   }

   //--- Sync enabled flags back into strategy objects via external call
   void GetAllHealth(SStrategyHealth &out[])
   {
      ArrayResize(out, 4);
      for(int i = 0; i < 4; i++) out[i] = m_health[i];
   }
};
