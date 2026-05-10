//+------------------------------------------------------------------+
//| TrendContinuation.mqh — SMC Trend Continuation strategy         |
//|                                                                  |
//| Logic:                                                           |
//|  1. Identify H4/D1 trend direction (Higher Highs/Higher Lows or |
//|     Lower Highs/Lower Lows)                                      |
//|  2. Wait for M15 price to pull back into a valid Order Block or  |
//|     demand/supply zone in the direction of the HTF trend         |
//|  3. Enter when M15 closes back inside the zone + momentum conf   |
//+------------------------------------------------------------------+
#pragma once
#include "BaseStrategy.mqh"

class CTrendContinuation : public CBaseStrategy
{
private:
   int    m_obLookback;
   double m_slMulti;
   double m_tpMulti;
   int    m_pullbackBars;  // maximum bars the pullback can last

   //--- Find a valid demand Order Block for bullish trend:
   //    The last bearish (down-close) candle before a strong up impulse
   //    that has NOT been violated by subsequent price action
   bool FindDemandOB(const SBar &h4[], int h4n, double &obTop, double &obBot)
   {
      for(int i = 3; i < MathMin(m_obLookback, h4n - 2); i++)
      {
         bool isBearish = h4[i].close < h4[i].open;
         // Next candle must be a strong bullish impulse
         bool strongBull = (h4[i - 1].close > h4[i].high) &&
                           ((h4[i - 1].close - h4[i - 1].open) >
                            (h4[i].open - h4[i].close) * 1.5);
         if(!isBearish || !strongBull) continue;

         // Zone: body of the OB candle
         obTop = h4[i].open;
         obBot = h4[i].close;

         // Verify the zone hasn't been broken (current H4 close should be above obBot)
         if(h4[0].close < obBot) continue;

         return true;
      }
      return false;
   }

   bool FindSupplyOB(const SBar &h4[], int h4n, double &obTop, double &obBot)
   {
      for(int i = 3; i < MathMin(m_obLookback, h4n - 2); i++)
      {
         bool isBullish = h4[i].close > h4[i].open;
         bool strongBear = (h4[i - 1].close < h4[i].low) &&
                           ((h4[i - 1].open  - h4[i - 1].close) >
                            (h4[i].close - h4[i].open) * 1.5);
         if(!isBullish || !strongBear) continue;

         obTop = h4[i].close;
         obBot = h4[i].open;

         if(h4[0].close > obTop) continue;

         return true;
      }
      return false;
   }

   //--- Check if M15 price has recently pulled back into a zone
   bool PulledBackInto(const SBar &m15[], int n, double zoneTop, double zoneBot, int maxBars)
   {
      for(int i = 0; i < MathMin(maxBars, n); i++)
      {
         if(m15[i].low <= zoneTop && m15[i].high >= zoneBot)
            return true;
      }
      return false;
   }

   //--- Confirm M15 rejection from zone (close back outside)
   bool ConfirmedRejectionBullish(const SBar &m15[], double zoneTop)
   {
      // Current bar closed above zone top (re-entered momentum)
      return (m15[0].close > zoneTop && m15[1].close <= zoneTop);
   }

   bool ConfirmedRejectionBearish(const SBar &m15[], double zoneBot)
   {
      return (m15[0].close < zoneBot && m15[1].close >= zoneBot);
   }

public:
   CTrendContinuation()
      : CBaseStrategy("TrendContinuation"),
        m_obLookback(TC_OB_Lookback),
        m_slMulti(TC_SL_ATR_Multi),
        m_tpMulti(TC_TP_ATR_Multi),
        m_pullbackBars(TC_PullbackBars) {}

   void SetParams(int obLookback, double slMulti, double tpMulti, int pullbackBars)
   {
      m_obLookback   = obLookback;
      m_slMulti      = slMulti;
      m_tpMulti      = tpMulti;
      m_pullbackBars = pullbackBars;
   }

   STradeSignal Analyze() override
   {
      if(!m_enabled || m_data == NULL || !m_data.IsReady())
         return InvalidSignal();

      const SMarketData* md = m_data.GetData();
      int m15n = md.m15Count;
      int h4n  = md.h4Count;
      if(m15n < 10 || h4n < m_obLookback) return InvalidSignal();

      const SBar* m15  = md.m15;
      const SBar* h4   = md.h4;
      double atr = md.atrM15;
      if(atr <= 0) return InvalidSignal();

      int htf = SMCUtils::GetHTFTrend(h4, h4n);

      STradeSignal sig;
      sig.isValid      = false;
      sig.strategyName = m_name;
      sig.signalTime   = TimeGMT();

      // --- Bullish trend: find demand OB, wait for pullback and rejection ---
      if(htf == 1)
      {
         double obTop, obBot;
         if(FindDemandOB(h4, h4n, obTop, obBot))
         {
            if(PulledBackInto(m15, m15n, obTop, obBot, m_pullbackBars) &&
               ConfirmedRejectionBullish(m15, obTop))
            {
               double entry  = m15[0].close;
               double sl     = obBot - atr * m_slMulti;
               double tp     = entry + (entry - sl) * m_tpMulti;
               double rr     = (entry - sl > 0) ? (tp - entry) / (entry - sl) : 0;

               // FVG as additional confluence
               double fvg = SMCUtils::FindBullishFVG(m15, m15n, 10);

               double structScore   = 1.0;
               double momentumScore = (fvg > 0) ? 0.85 : 0.60;
               double trendScore    = 1.0;   // perfectly aligned
               double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

               sig.isValid    = true;
               sig.isBuy      = true;
               sig.entryPrice = entry;
               sig.stopLoss   = sl;
               sig.takeProfit = tp;
               sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                             trendScore, rrScore);
               sig.reason = StringFormat(
                  "Bullish TC: HTF=UP, OB=[%.3f-%.3f], FVG=%s",
                  obBot, obTop, (fvg > 0 ? "yes" : "no"));
            }
         }
      }
      // --- Bearish trend: find supply OB, wait for pullback and rejection ---
      else if(htf == -1)
      {
         double obTop, obBot;
         if(FindSupplyOB(h4, h4n, obTop, obBot))
         {
            if(PulledBackInto(m15, m15n, obTop, obBot, m_pullbackBars) &&
               ConfirmedRejectionBearish(m15, obBot))
            {
               double entry  = m15[0].close;
               double sl     = obTop + atr * m_slMulti;
               double tp     = entry - (sl - entry) * m_tpMulti;
               double rr     = (sl - entry > 0) ? (entry - tp) / (sl - entry) : 0;

               double fvg = SMCUtils::FindBearishFVG(m15, m15n, 10);

               double structScore   = 1.0;
               double momentumScore = (fvg > 0) ? 0.85 : 0.60;
               double trendScore    = 1.0;
               double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

               sig.isValid    = true;
               sig.isBuy      = false;
               sig.entryPrice = entry;
               sig.stopLoss   = sl;
               sig.takeProfit = tp;
               sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                             trendScore, rrScore);
               sig.reason = StringFormat(
                  "Bearish TC: HTF=DOWN, OB=[%.3f-%.3f], FVG=%s",
                  obBot, obTop, (fvg > 0 ? "yes" : "no"));
            }
         }
      }

      if(sig.isValid)
         LogInfo("TrendContinuation", StringFormat(
            "%s signal | Entry=%.3f SL=%.3f TP=%.3f Conf=%.0f%% | %s",
            sig.isBuy ? "BUY" : "SELL",
            sig.entryPrice, sig.stopLoss, sig.takeProfit,
            sig.confidence * 100.0, sig.reason));

      return sig;
   }
};
