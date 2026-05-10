//+------------------------------------------------------------------+
//| Momentum.mqh — RSI + MACD + FVG Momentum strategy               |
//|                                                                  |
//| Logic:                                                           |
//|  1. Compute RSI and MACD on M15                                  |
//|  2. Check HTF bias (H4 trend direction)                          |
//|  3. Require momentum alignment: RSI direction + MACD crossover   |
//|  4. Confirm with a nearby Fair Value Gap                         |
//|  5. Enter in the direction of momentum aligned with HTF bias     |
//+------------------------------------------------------------------+
#pragma once
#include "BaseStrategy.mqh"

class CMomentum : public CBaseStrategy
{
private:
   int    m_rsiPeriod;
   double m_rsiOB;
   double m_rsiOS;
   int    m_macdFast;
   int    m_macdSlow;
   int    m_macdSignal;
   double m_slMulti;
   double m_tpMulti;
   int    m_fvgLookback;

   // Indicator handles
   int    m_rsiHandle;
   int    m_macdHandle;

   bool GetRSI(double &rsi)
   {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(m_rsiHandle, 0, 0, 3, buf) < 3) return false;
      rsi = buf[1];  // use confirmed bar
      return true;
   }

   bool GetMACD(double &macdLine, double &signalLine)
   {
      double macdBuf[], sigBuf[];
      ArraySetAsSeries(macdBuf,  true);
      ArraySetAsSeries(sigBuf,   true);
      if(CopyBuffer(m_macdHandle, 0, 0, 3, macdBuf) < 3) return false;
      if(CopyBuffer(m_macdHandle, 1, 0, 3, sigBuf)  < 3) return false;
      macdLine   = macdBuf[1];
      signalLine = sigBuf[1];
      return true;
   }

   //--- MACD bullish crossover on last confirmed bar
   bool MACDBullCross()
   {
      double m0, s0, m1, s1;
      double macdBuf[], sigBuf[];
      ArraySetAsSeries(macdBuf, true);
      ArraySetAsSeries(sigBuf,  true);
      if(CopyBuffer(m_macdHandle, 0, 0, 4, macdBuf) < 4) return false;
      if(CopyBuffer(m_macdHandle, 1, 0, 4, sigBuf)  < 4) return false;
      m0 = macdBuf[1]; s0 = sigBuf[1];  // bar[1] = confirmed
      m1 = macdBuf[2]; s1 = sigBuf[2];  // bar[2] = prior
      return (m0 > s0 && m1 <= s1);
   }

   bool MACDBearCross()
   {
      double macdBuf[], sigBuf[];
      ArraySetAsSeries(macdBuf, true);
      ArraySetAsSeries(sigBuf,  true);
      if(CopyBuffer(m_macdHandle, 0, 0, 4, macdBuf) < 4) return false;
      if(CopyBuffer(m_macdHandle, 1, 0, 4, sigBuf)  < 4) return false;
      double m0 = macdBuf[1], s0 = sigBuf[1];
      double m1 = macdBuf[2], s1 = sigBuf[2];
      return (m0 < s0 && m1 >= s1);
   }

public:
   CMomentum()
      : CBaseStrategy("Momentum"),
        m_rsiPeriod(MOM_RSI_Period),
        m_rsiOB(MOM_RSI_OB),
        m_rsiOS(MOM_RSI_OS),
        m_macdFast(MOM_MACD_Fast),
        m_macdSlow(MOM_MACD_Slow),
        m_macdSignal(MOM_MACD_Signal),
        m_slMulti(MOM_SL_ATR_Multi),
        m_tpMulti(MOM_TP_ATR_Multi),
        m_fvgLookback(MOM_FVG_Lookback),
        m_rsiHandle(INVALID_HANDLE),
        m_macdHandle(INVALID_HANDLE) {}

   bool Init()
   {
      m_rsiHandle  = iRSI(EA_SYMBOL, TF_ENTRY, m_rsiPeriod, PRICE_CLOSE);
      m_macdHandle = iMACD(EA_SYMBOL, TF_ENTRY,
                           m_macdFast, m_macdSlow, m_macdSignal, PRICE_CLOSE);
      if(m_rsiHandle == INVALID_HANDLE || m_macdHandle == INVALID_HANDLE)
      {
         LogError("Momentum", "Failed to create RSI/MACD handles");
         return false;
      }
      LogInfo("Momentum", "RSI and MACD handles created.");
      return true;
   }

   void SetParams(int rsiPeriod, double rsiOB, double rsiOS,
                  double slMulti, double tpMulti, int fvgLookback)
   {
      m_rsiPeriod   = rsiPeriod;
      m_rsiOB       = rsiOB;
      m_rsiOS       = rsiOS;
      m_slMulti     = slMulti;
      m_tpMulti     = tpMulti;
      m_fvgLookback = fvgLookback;
   }

   STradeSignal Analyze() override
   {
      if(!m_enabled || m_data == NULL || !m_data.IsReady())
         return InvalidSignal();

      const SMarketData* md = m_data.GetData();
      int n = md.m15Count;
      if(n < 30) return InvalidSignal();

      const SBar* m15 = md.m15;
      double atr = md.atrM15;
      if(atr <= 0) return InvalidSignal();

      double rsi, macdLine, signalLine;
      if(!GetRSI(rsi)) return InvalidSignal();
      if(!GetMACD(macdLine, signalLine)) return InvalidSignal();

      int htf = SMCUtils::GetHTFTrend(md.h4, md.h4Count);

      STradeSignal sig;
      sig.isValid      = false;
      sig.strategyName = m_name;
      sig.signalTime   = TimeGMT();

      // --- Bullish Momentum ---
      // RSI coming from oversold + MACD bullish cross + HTF bias UP + FVG nearby
      if(rsi < 50 && rsi > m_rsiOS &&     // came from OS, now recovering
         MACDBullCross() &&
         (htf >= 0))                        // at least neutral or bullish
      {
         double fvg = SMCUtils::FindBullishFVG(m15, n, m_fvgLookback);

         if(fvg > 0)
         {
            double entry  = m15[0].close;
            double sl     = SMCUtils::LowestBar(m15, 10) >= 0
                            ? m15[SMCUtils::LowestBar(m15, 10)].low - atr * m_slMulti
                            : entry - atr * (m_slMulti + 1);
            double tp     = entry + (entry - sl) * m_tpMulti;
            double rr     = (entry - sl > 0) ? (tp - entry) / (entry - sl) : 0;

            double structScore   = (fvg > 0) ? 0.9 : 0.5;
            double momentumScore = 1.0 - (rsi - m_rsiOS) / (50.0 - m_rsiOS) * 0.3;
            double trendScore    = (htf == 1) ? 1.0 : 0.65;
            double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

            sig.isValid    = true;
            sig.isBuy      = true;
            sig.entryPrice = entry;
            sig.stopLoss   = sl;
            sig.takeProfit = tp;
            sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                          trendScore, rrScore);
            sig.reason = StringFormat(
               "Bull MOM: RSI=%.1f MACD_cross FVG=%.3f HTF=%d",
               rsi, fvg, htf);
         }
      }
      // --- Bearish Momentum ---
      else if(rsi > 50 && rsi < m_rsiOB &&
              MACDBearCross() &&
              (htf <= 0))
      {
         double fvg = SMCUtils::FindBearishFVG(m15, n, m_fvgLookback);

         if(fvg > 0)
         {
            double entry  = m15[0].close;
            double sl     = m15[SMCUtils::HighestBar(m15, 10)].high + atr * m_slMulti;
            double tp     = entry - (sl - entry) * m_tpMulti;
            double rr     = (sl - entry > 0) ? (entry - tp) / (sl - entry) : 0;

            double structScore   = (fvg > 0) ? 0.9 : 0.5;
            double momentumScore = 1.0 - (m_rsiOB - rsi) / (m_rsiOB - 50.0) * 0.3;
            double trendScore    = (htf == -1) ? 1.0 : 0.65;
            double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

            sig.isValid    = true;
            sig.isBuy      = false;
            sig.entryPrice = entry;
            sig.stopLoss   = sl;
            sig.takeProfit = tp;
            sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                          trendScore, rrScore);
            sig.reason = StringFormat(
               "Bear MOM: RSI=%.1f MACD_cross FVG=%.3f HTF=%d",
               rsi, fvg, htf);
         }
      }

      if(sig.isValid)
         LogInfo("Momentum", StringFormat(
            "%s signal | Entry=%.3f SL=%.3f TP=%.3f Conf=%.0f%% | %s",
            sig.isBuy ? "BUY" : "SELL",
            sig.entryPrice, sig.stopLoss, sig.takeProfit,
            sig.confidence * 100.0, sig.reason));

      return sig;
   }

   void Deinit()
   {
      if(m_rsiHandle  != INVALID_HANDLE) IndicatorRelease(m_rsiHandle);
      if(m_macdHandle != INVALID_HANDLE) IndicatorRelease(m_macdHandle);
   }

   ~CMomentum() { Deinit(); }
};
