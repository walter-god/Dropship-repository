//+------------------------------------------------------------------+
//| Breakout.mqh — SMC Breakout strategy                            |
//|                                                                  |
//| Logic:                                                           |
//|  1. Detect a consolidation range: N bars with ATR < threshold   |
//|  2. Identify the range High and Low                              |
//|  3. On a bar that closes strongly outside the range with         |
//|     above-average volume, emit a breakout signal                 |
//|  4. Enter on the breakout bar or first retest of the broken level|
//+------------------------------------------------------------------+
#pragma once
#include "BaseStrategy.mqh"

class CBreakout : public CBaseStrategy
{
private:
   int    m_consolidBars;
   double m_atrConsolThr;   // ATR as fraction of its own value to declare consolidation
   double m_slMulti;
   double m_tpMulti;
   int    m_volLookback;

   //--- Returns true if the last N bars were in a low-ATR consolidation
   //    Also fills rangeHigh / rangeLow
   bool IsConsolidating(const SBar &bars[], int n, double atr,
                        double &rangeHigh, double &rangeLow)
   {
      if(n < m_consolidBars + 2) return false;

      // Inline ATR over consolidation range
      double rangeATR = SMCUtils::ComputeATR(bars, m_consolidBars + 1, m_consolidBars);
      if(rangeATR <= 0) return false;

      // Consolidation if recent ATR is below threshold fraction of overall ATR
      if(rangeATR > atr * m_atrConsolThr) return false;

      rangeHigh = bars[SMCUtils::HighestBar(bars, m_consolidBars)].high;
      rangeLow  = bars[SMCUtils::LowestBar(bars,  m_consolidBars)].low;
      return true;
   }

   //--- Average tick volume over last N bars (skip bar[0])
   double AvgVolume(const SBar &bars[], int n)
   {
      double sum = 0;
      int    cnt = MathMin(m_volLookback, n - 1);
      for(int i = 1; i <= cnt; i++) sum += (double)bars[i].volume;
      return (cnt > 0) ? sum / cnt : 0.0;
   }

public:
   CBreakout()
      : CBaseStrategy("Breakout"),
        m_consolidBars(BO_ConsolidationBars),
        m_atrConsolThr(BO_ATR_ConsolThr),
        m_slMulti(BO_SL_ATR_Multi),
        m_tpMulti(BO_TP_ATR_Multi),
        m_volLookback(BO_VolumeLookback) {}

   void SetParams(int consolidBars, double atrThr, double slMulti,
                  double tpMulti, int volLookback)
   {
      m_consolidBars  = consolidBars;
      m_atrConsolThr  = atrThr;
      m_slMulti       = slMulti;
      m_tpMulti       = tpMulti;
      m_volLookback   = volLookback;
   }

   STradeSignal Analyze() override
   {
      if(!m_enabled || m_data == NULL || !m_data.IsReady())
         return InvalidSignal();

      const SMarketData* md = m_data.GetData();
      int n = md.m15Count;
      if(n < m_consolidBars + m_volLookback + 5) return InvalidSignal();

      const SBar* bars = md.m15;
      double atr  = md.atrM15;
      if(atr <= 0) return InvalidSignal();

      double rangeHigh, rangeLow;
      if(!IsConsolidating(bars, n, atr, rangeHigh, rangeLow))
         return InvalidSignal();

      SBar breakBar = bars[1];   // most recently completed bar
      double avgVol = AvgVolume(bars, n);
      bool   volConf = (avgVol > 0) && ((double)breakBar.volume >= avgVol * 1.5);

      int htf = SMCUtils::GetHTFTrend(md.h4, md.h4Count);

      STradeSignal sig;
      sig.isValid      = false;
      sig.strategyName = m_name;
      sig.signalTime   = TimeGMT();

      // --- Bullish breakout ---
      if(breakBar.close > rangeHigh &&
         breakBar.close > breakBar.open &&    // bullish close
         (volConf || htf == 1))               // volume OR HTF alignment
      {
         double entry = bars[0].close;       // enter on current bar open / close
         double sl    = rangeLow - atr * m_slMulti;
         double tp    = entry + (entry - sl) * m_tpMulti;
         double rr    = (entry - sl > 0) ? (tp - entry) / (entry - sl) : 0;

         double structScore   = 1.0;
         double momentumScore = volConf ? 1.0 : 0.65;
         double trendScore    = (htf == 1) ? 1.0 : (htf == 0 ? 0.6 : 0.3);
         double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

         sig.isValid    = true;
         sig.isBuy      = true;
         sig.entryPrice = entry;
         sig.stopLoss   = sl;
         sig.takeProfit = tp;
         sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                       trendScore, rrScore);
         sig.reason = StringFormat(
            "Bull BO: range=[%.3f-%.3f] break=%.3f vol=%s HTF=%d",
            rangeLow, rangeHigh, breakBar.close,
            volConf ? "strong" : "weak", htf);
      }
      // --- Bearish breakout ---
      else if(breakBar.close < rangeLow &&
              breakBar.close < breakBar.open &&
              (volConf || htf == -1))
      {
         double entry = bars[0].close;
         double sl    = rangeHigh + atr * m_slMulti;
         double tp    = entry - (sl - entry) * m_tpMulti;
         double rr    = (sl - entry > 0) ? (entry - tp) / (sl - entry) : 0;

         double structScore   = 1.0;
         double momentumScore = volConf ? 1.0 : 0.65;
         double trendScore    = (htf == -1) ? 1.0 : (htf == 0 ? 0.6 : 0.3);
         double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

         sig.isValid    = true;
         sig.isBuy      = false;
         sig.entryPrice = entry;
         sig.stopLoss   = sl;
         sig.takeProfit = tp;
         sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                       trendScore, rrScore);
         sig.reason = StringFormat(
            "Bear BO: range=[%.3f-%.3f] break=%.3f vol=%s HTF=%d",
            rangeLow, rangeHigh, breakBar.close,
            volConf ? "strong" : "weak", htf);
      }

      if(sig.isValid)
         LogInfo("Breakout", StringFormat(
            "%s signal | Entry=%.3f SL=%.3f TP=%.3f Conf=%.0f%% | %s",
            sig.isBuy ? "BUY" : "SELL",
            sig.entryPrice, sig.stopLoss, sig.takeProfit,
            sig.confidence * 100.0, sig.reason));

      return sig;
   }
};
