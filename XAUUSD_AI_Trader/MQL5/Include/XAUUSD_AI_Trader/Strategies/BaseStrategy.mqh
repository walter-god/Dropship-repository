//+------------------------------------------------------------------+
//| BaseStrategy.mqh — Abstract base for all SMC strategies          |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Data/DataFetcher.mqh"
#include "../Utils/Logger.mqh"

//--- Signal emitted by a strategy after analysis
struct STradeSignal
{
   bool     isValid;
   string   strategyName;
   bool     isBuy;            // true=BUY, false=SELL
   double   entryPrice;
   double   stopLoss;
   double   takeProfit;
   double   confidence;       // 0.0 – 1.0
   string   reason;           // human-readable rationale
   datetime signalTime;
};

//--- Helpers shared by all strategies
namespace SMCUtils
{
   //--- Find the highest high in bars[0..n-1] (series order: 0=most recent)
   int HighestBar(const SBar &bars[], int n)
   {
      int idx = 0;
      for(int i = 1; i < n; i++)
         if(bars[i].high > bars[idx].high) idx = i;
      return idx;
   }

   int LowestBar(const SBar &bars[], int n)
   {
      int idx = 0;
      for(int i = 1; i < n; i++)
         if(bars[i].low < bars[idx].low) idx = i;
      return idx;
   }

   //--- Swing high: bar i has a higher high than the lookback/2 bars on each side
   bool IsSwingHigh(const SBar &bars[], int i, int n, int wing = 3)
   {
      if(i < wing || i + wing >= n) return false;
      for(int k = 1; k <= wing; k++)
      {
         if(bars[i - k].high >= bars[i].high) return false;
         if(bars[i + k].high >= bars[i].high) return false;
      }
      return true;
   }

   bool IsSwingLow(const SBar &bars[], int i, int n, int wing = 3)
   {
      if(i < wing || i + wing >= n) return false;
      for(int k = 1; k <= wing; k++)
      {
         if(bars[i - k].low <= bars[i].low) return false;
         if(bars[i + k].low <= bars[i].low) return false;
      }
      return true;
   }

   //--- ATR computed inline over `period` bars from bars[]
   double ComputeATR(const SBar &bars[], int n, int period)
   {
      if(n < period + 1) return 0.0;
      double sum = 0.0;
      for(int i = 1; i <= period; i++)
      {
         double tr = MathMax(bars[i].high - bars[i].low,
                    MathMax(MathAbs(bars[i].high - bars[i + 1].close),
                            MathAbs(bars[i].low  - bars[i + 1].close)));
         sum += tr;
      }
      return sum / period;
   }

   //--- Detect a Fair Value Gap (FVG): gap between candle[i+2].high and candle[i].low (bullish)
   //    Returns the mid-point of the FVG or 0.0 if not found within lookback bars
   double FindBullishFVG(const SBar &bars[], int n, int lookback)
   {
      for(int i = 1; i < MathMin(lookback, n - 2); i++)
      {
         if(bars[i + 2].high < bars[i].low) // gap exists (series reversed, 0=newest)
            return (bars[i + 2].high + bars[i].low) / 2.0;
      }
      return 0.0;
   }

   double FindBearishFVG(const SBar &bars[], int n, int lookback)
   {
      for(int i = 1; i < MathMin(lookback, n - 2); i++)
      {
         if(bars[i + 2].low > bars[i].high)
            return (bars[i + 2].low + bars[i].high) / 2.0;
      }
      return 0.0;
   }

   //--- Determine higher-timeframe trend using last H4 bars
   //    Returns 1=bullish, -1=bearish, 0=ranging
   int GetHTFTrend(const SBar &h4Bars[], int n, int lookback = 20)
   {
      if(n < lookback) return 0;
      double highestHigh = h4Bars[SMCUtils::HighestBar(h4Bars, lookback)].high;
      double lowestLow   = h4Bars[SMCUtils::LowestBar(h4Bars, lookback)].low;
      double range       = highestHigh - lowestLow;
      double currentClose = h4Bars[0].close;
      double midpoint     = (highestHigh + lowestLow) / 2.0;

      // Simple structural bias: price above/below mid
      if(currentClose > midpoint + range * 0.1) return  1;
      if(currentClose < midpoint - range * 0.1) return -1;
      return 0;
   }

   //--- Compute confidence score from component scores (0–1 each)
   double ComputeConfidence(double structScore, double momentumScore,
                            double trendScore,  double rrScore)
   {
      return (structScore   * CONF_WEIGHT_STRUCTURE  +
              momentumScore * CONF_WEIGHT_MOMENTUM   +
              trendScore    * CONF_WEIGHT_HTF_TREND  +
              rrScore       * CONF_WEIGHT_RISK_REWARD);
   }
}

//--- Abstract strategy interface
class CBaseStrategy
{
protected:
   string          m_name;
   bool            m_enabled;
   CDataFetcher*   m_data;

   STradeSignal InvalidSignal()
   {
      STradeSignal sig;
      sig.isValid       = false;
      sig.strategyName  = m_name;
      sig.isBuy         = false;
      sig.entryPrice    = 0;
      sig.stopLoss      = 0;
      sig.takeProfit    = 0;
      sig.confidence    = 0;
      sig.reason        = "No signal";
      sig.signalTime    = TimeGMT();
      return sig;
   }

public:
   CBaseStrategy(string name) : m_name(name), m_enabled(true), m_data(NULL) {}

   void SetDataFetcher(CDataFetcher* df) { m_data = df; }
   void SetEnabled(bool v)               { m_enabled = v; }
   bool IsEnabled()                const { return m_enabled; }
   string GetName()                const { return m_name; }

   //--- Concrete strategies must implement this
   virtual STradeSignal Analyze() = 0;

   virtual ~CBaseStrategy() {}
};
