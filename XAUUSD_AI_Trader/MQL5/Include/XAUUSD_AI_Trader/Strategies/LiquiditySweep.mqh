//+------------------------------------------------------------------+
//| LiquiditySweep.mqh — SMC Liquidity Sweep strategy               |
//|                                                                  |
//| Logic:                                                           |
//|  1. Identify equal highs / equal lows (liquidity pools)         |
//|  2. Detect a sweep above/below those levels on the current bar  |
//|  3. Confirm reversal with an Order Block or FVG                  |
//|  4. Enter in the direction opposite to the sweep                 |
//+------------------------------------------------------------------+
#pragma once
#include "BaseStrategy.mqh"

class CLiquiditySweep : public CBaseStrategy
{
private:
   int    m_lookback;
   double m_equalTol;      // pip tolerance for "equal" levels
   double m_slMulti;
   double m_tpMulti;
   double m_pipSize;

   //--- Collect all swing highs in bars[1..lookback]
   //    Returns count written into levels[]
   int CollectLiquidityHighs(const SBar &bars[], int n, double levels[], int maxLevels)
   {
      int count = 0;
      for(int i = 1; i < n && count < maxLevels; i++)
      {
         if(SMCUtils::IsSwingHigh(bars, i, n, 3))
            levels[count++] = bars[i].high;
      }
      return count;
   }

   int CollectLiquidityLows(const SBar &bars[], int n, double levels[], int maxLevels)
   {
      int count = 0;
      for(int i = 1; i < n && count < maxLevels; i++)
      {
         if(SMCUtils::IsSwingLow(bars, i, n, 3))
            levels[count++] = bars[i].low;
      }
      return count;
   }

   //--- Find a pair of equal levels (within tolerance) — returns the level price or 0
   double FindEqualLevel(const double levels[], int count)
   {
      for(int i = 0; i < count - 1; i++)
         for(int j = i + 1; j < count; j++)
            if(MathAbs(levels[i] - levels[j]) <= m_equalTol)
               return (levels[i] + levels[j]) / 2.0;
      return 0.0;
   }

   //--- Check if the current bar wicked through the level (sweep)
   bool SweptAbove(const SBar &bar, double level) { return bar.high > level && bar.close < level; }
   bool SweptBelow(const SBar &bar, double level) { return bar.low  < level && bar.close > level; }

   //--- Find nearest Order Block below current price (for bullish entry after bearish sweep)
   //    An OB is the last down-close candle before a strong up move
   double FindBullishOB(const SBar &bars[], int n, double maxPrice)
   {
      for(int i = 2; i < MathMin(n, 30); i++)
      {
         bool isDownCandle = bars[i].close < bars[i].open;
         bool nextStrongUp = (i >= 2) &&
                             (bars[i - 1].close > bars[i].high) &&
                             (bars[i - 1].close - bars[i - 1].open >
                              bars[i].open - bars[i].close);
         if(isDownCandle && nextStrongUp && bars[i].high < maxPrice)
            return (bars[i].open + bars[i].close) / 2.0;
      }
      return 0.0;
   }

   double FindBearishOB(const SBar &bars[], int n, double minPrice)
   {
      for(int i = 2; i < MathMin(n, 30); i++)
      {
         bool isUpCandle   = bars[i].close > bars[i].open;
         bool nextStrongDn = (i >= 2) &&
                             (bars[i - 1].close < bars[i].low) &&
                             (bars[i - 1].open  - bars[i - 1].close >
                              bars[i].close - bars[i].open);
         if(isUpCandle && nextStrongDn && bars[i].low > minPrice)
            return (bars[i].open + bars[i].close) / 2.0;
      }
      return 0.0;
   }

public:
   CLiquiditySweep()
      : CBaseStrategy("LiquiditySweep"),
        m_lookback(LS_LiquidityLookback),
        m_equalTol(0.0),
        m_slMulti(LS_SL_ATR_Multi),
        m_tpMulti(LS_TP_ATR_Multi),
        m_pipSize(0.0) {}

   void Init()
   {
      double point  = SymbolInfoDouble(EA_SYMBOL, SYMBOL_POINT);
      int    digits = (int)SymbolInfoInteger(EA_SYMBOL, SYMBOL_DIGITS);
      m_pipSize     = (digits == 3 || digits == 5) ? point * 10 : point;
      m_equalTol    = LS_EqualLevelTol * m_pipSize;
   }

   //--- Override parameters from optimizer
   void SetParams(int lookback, double equalTol, double slMulti, double tpMulti)
   {
      m_lookback  = lookback;
      m_equalTol  = equalTol * m_pipSize;
      m_slMulti   = slMulti;
      m_tpMulti   = tpMulti;
   }

   STradeSignal Analyze() override
   {
      if(!m_enabled || m_data == NULL || !m_data.IsReady())
         return InvalidSignal();

      const SMarketData* md = m_data.GetData();
      int n = md.m15Count;
      if(n < m_lookback + 5) return InvalidSignal();

      const SBar* bars = md.m15;
      double atr = md.atrM15;
      if(atr <= 0) return InvalidSignal();

      // Collect liquidity pools
      double highLevels[50], lowLevels[50];
      int    hCount = CollectLiquidityHighs(bars, n, highLevels, 50);
      int    lCount = CollectLiquidityLows(bars,  n, lowLevels,  50);

      double eqHigh = FindEqualLevel(highLevels, hCount);
      double eqLow  = FindEqualLevel(lowLevels,  lCount);

      SBar currentBar = bars[0];
      SBar prevBar    = bars[1];

      STradeSignal sig;
      sig.isValid      = false;
      sig.strategyName = m_name;
      sig.signalTime   = TimeGMT();

      // --- Bullish setup: sweep of equal lows → look for long ---
      if(eqLow > 0 && SweptBelow(prevBar, eqLow))
      {
         // Confirm with FVG or OB
         double fvgLevel = SMCUtils::FindBullishFVG(bars, n, MOM_FVG_Lookback);
         double obLevel  = FindBullishOB(bars, n, eqLow);
         double confLevel = (fvgLevel > 0) ? fvgLevel : obLevel;

         if(confLevel > 0 && currentBar.close > confLevel)
         {
            double entry = currentBar.close;
            double sl    = prevBar.low - atr * m_slMulti;
            double tp    = entry + (entry - sl) * m_tpMulti;
            int    htf   = SMCUtils::GetHTFTrend(md.h4, md.h4Count);

            double structScore   = 1.0;
            double momentumScore = (htf == 1) ? 0.9 : (htf == 0 ? 0.5 : 0.2);
            double trendScore    = (htf >= 0)  ? 0.8 : 0.3;
            double rr            = (entry - sl > 0) ? (tp - entry) / (entry - sl) : 0;
            double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

            sig.isValid    = true;
            sig.isBuy      = true;
            sig.entryPrice = entry;
            sig.stopLoss   = sl;
            sig.takeProfit = tp;
            sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                         trendScore, rrScore);
            sig.reason = StringFormat(
               "Bullish LS: swept EQ_LOW=%.3f, conf via %s=%.3f, HTF=%d",
               eqLow, (fvgLevel > 0 ? "FVG" : "OB"), confLevel, htf);
         }
      }
      // --- Bearish setup: sweep of equal highs → look for short ---
      else if(eqHigh > 0 && SweptAbove(prevBar, eqHigh))
      {
         double fvgLevel  = SMCUtils::FindBearishFVG(bars, n, MOM_FVG_Lookback);
         double obLevel   = FindBearishOB(bars, n, eqHigh);
         double confLevel = (fvgLevel > 0) ? fvgLevel : obLevel;

         if(confLevel > 0 && currentBar.close < confLevel)
         {
            double entry = currentBar.close;
            double sl    = prevBar.high + atr * m_slMulti;
            double tp    = entry - (sl - entry) * m_tpMulti;
            int    htf   = SMCUtils::GetHTFTrend(md.h4, md.h4Count);

            double structScore   = 1.0;
            double momentumScore = (htf == -1) ? 0.9 : (htf == 0 ? 0.5 : 0.2);
            double trendScore    = (htf <= 0)   ? 0.8 : 0.3;
            double rr            = (sl - entry > 0) ? (entry - tp) / (sl - entry) : 0;
            double rrScore       = (rr >= MIN_RR_RATIO) ? 1.0 : rr / MIN_RR_RATIO;

            sig.isValid    = true;
            sig.isBuy      = false;
            sig.entryPrice = entry;
            sig.stopLoss   = sl;
            sig.takeProfit = tp;
            sig.confidence = SMCUtils::ComputeConfidence(structScore, momentumScore,
                                                         trendScore, rrScore);
            sig.reason = StringFormat(
               "Bearish LS: swept EQ_HIGH=%.3f, conf via %s=%.3f, HTF=%d",
               eqHigh, (fvgLevel > 0 ? "FVG" : "OB"), confLevel, htf);
         }
      }

      if(sig.isValid)
         LogInfo("LiquiditySweep", StringFormat(
            "%s signal | Entry=%.3f SL=%.3f TP=%.3f Conf=%.0f%% | %s",
            sig.isBuy ? "BUY" : "SELL",
            sig.entryPrice, sig.stopLoss, sig.takeProfit,
            sig.confidence * 100.0, sig.reason));

      return sig;
   }
};
