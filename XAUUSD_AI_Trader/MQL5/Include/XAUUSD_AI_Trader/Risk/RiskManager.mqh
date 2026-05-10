//+------------------------------------------------------------------+
//| RiskManager.mqh — Position sizing, daily limits, circuit breaker |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Utils/Logger.mqh"

enum ENUM_TRADE_BLOCK_REASON
{
   BLOCK_NONE            = 0,
   BLOCK_DAILY_LOSS      = 1,
   BLOCK_CIRCUIT_BREAKER = 2,
   BLOCK_MAX_TRADES      = 3
};

class CRiskManager
{
private:
   double   m_accountBalance;
   double   m_dailyStartBalance;
   double   m_dailyLossAccum;         // running daily loss (negative = loss)
   int      m_consecutiveLosses;
   int      m_openTradeCount;
   datetime m_circuitBreakerUntil;    // epoch; 0 = no pause
   datetime m_dailyResetTime;         // midnight of current trading day

   void ResetDailyCounters()
   {
      m_dailyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      m_dailyLossAccum    = 0.0;
      m_dailyResetTime    = GetTodayMidnight();
      LogInfo("RiskManager", StringFormat("Daily counters reset. Balance=%.2f", m_dailyStartBalance));
   }

   datetime GetTodayMidnight()
   {
      MqlDateTime dt;
      TimeToStruct(TimeGMT(), dt);
      dt.hour = 0; dt.min = 0; dt.sec = 0;
      return StructToTime(dt);
   }

public:
   CRiskManager()
      : m_accountBalance(0),
        m_dailyStartBalance(0),
        m_dailyLossAccum(0),
        m_consecutiveLosses(0),
        m_openTradeCount(0),
        m_circuitBreakerUntil(0),
        m_dailyResetTime(0) {}

   void Init()
   {
      m_accountBalance    = AccountInfoDouble(ACCOUNT_BALANCE);
      m_dailyStartBalance = m_accountBalance;
      m_dailyResetTime    = GetTodayMidnight();
      LogInfo("RiskManager", StringFormat("Init. Balance=%.2f MaxRisk=%.1f%% DailyLimit=%.1f%%",
              m_accountBalance, RISK_PERCENT_PER_TRADE, DAILY_LOSS_LIMIT_PCT));
   }

   //--- Call on every OnTick / timer to check day roll-over
   void Update()
   {
      datetime nowMidnight = GetTodayMidnight();
      if(nowMidnight > m_dailyResetTime)
         ResetDailyCounters();

      m_accountBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   }

   //--- Compute lot size based on 1% account risk given SL in price points
   double CalcLotSize(double entryPrice, double slPrice)
   {
      double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
      double riskAmt  = balance * RISK_PERCENT_PER_TRADE / 100.0;
      double slPoints = MathAbs(entryPrice - slPrice);

      double tickVal  = SymbolInfoDouble(EA_SYMBOL, SYMBOL_TRADE_TICK_VALUE);
      double tickSize = SymbolInfoDouble(EA_SYMBOL, SYMBOL_TRADE_TICK_SIZE);
      if(tickSize == 0 || tickVal == 0 || slPoints == 0) return 0.0;

      double valuePerLotPerPoint = tickVal / tickSize;
      double lots = riskAmt / (slPoints * valuePerLotPerPoint);

      double minLot  = SymbolInfoDouble(EA_SYMBOL, SYMBOL_VOLUME_MIN);
      double maxLot  = SymbolInfoDouble(EA_SYMBOL, SYMBOL_VOLUME_MAX);
      double lotStep = SymbolInfoDouble(EA_SYMBOL, SYMBOL_VOLUME_STEP);

      lots = MathFloor(lots / lotStep) * lotStep;
      lots = MathMax(minLot, MathMin(maxLot, lots));

      LogInfo("RiskManager", StringFormat("LotSize=%.2f (SL=%.5f Risk=$%.2f)",
              lots, slPoints, riskAmt));
      return lots;
   }

   //--- Validate that a trade can be placed; returns the block reason
   ENUM_TRADE_BLOCK_REASON CanOpenTrade()
   {
      // Check max open trades
      if(m_openTradeCount >= MAX_OPEN_TRADES)
         return BLOCK_MAX_TRADES;

      // Check daily loss limit
      double dailyLossPct = (m_dailyStartBalance > 0)
                            ? (m_dailyLossAccum / m_dailyStartBalance) * 100.0
                            : 0.0;
      if(dailyLossPct <= -DAILY_LOSS_LIMIT_PCT)
      {
         LogWarning("RiskManager", StringFormat("Daily loss limit hit: %.2f%%", dailyLossPct));
         return BLOCK_DAILY_LOSS;
      }

      // Check circuit breaker
      if(m_circuitBreakerUntil > TimeGMT())
      {
         int minsLeft = (int)((m_circuitBreakerUntil - TimeGMT()) / 60);
         LogWarning("RiskManager", StringFormat("Circuit breaker active. %d min remaining.", minsLeft));
         return BLOCK_CIRCUIT_BREAKER;
      }

      return BLOCK_NONE;
   }

   //--- Validate Risk:Reward before placing trade
   bool ValidateRR(double entryPrice, double slPrice, double tpPrice)
   {
      double risk   = MathAbs(entryPrice - slPrice);
      double reward = MathAbs(tpPrice - entryPrice);
      if(risk == 0) return false;
      double rr = reward / risk;
      if(rr < MIN_RR_RATIO)
      {
         LogWarning("RiskManager", StringFormat("RR=%.2f below minimum %.2f", rr, MIN_RR_RATIO));
         return false;
      }
      return true;
   }

   //--- Called when a new trade is opened
   void OnTradeOpened()
   {
      m_openTradeCount++;
      LogInfo("RiskManager", StringFormat("Trade opened. Open count=%d", m_openTradeCount));
   }

   //--- Called when a trade is closed
   void OnTradeClosed(double pnl)
   {
      m_openTradeCount = MathMax(0, m_openTradeCount - 1);
      m_dailyLossAccum += pnl;

      if(pnl < 0)
      {
         m_consecutiveLosses++;
         LogWarning("RiskManager", StringFormat(
            "Losing trade. Consecutive=%d PnL=%.2f DailyAccum=%.2f",
            m_consecutiveLosses, pnl, m_dailyLossAccum));

         if(m_consecutiveLosses >= CIRCUIT_BREAKER_LOSSES)
         {
            m_circuitBreakerUntil = TimeGMT() + CIRCUIT_BREAKER_PAUSE_MIN * 60;
            LogWarning("RiskManager", StringFormat(
               "CIRCUIT BREAKER triggered! Pausing %d minutes until %s",
               CIRCUIT_BREAKER_PAUSE_MIN,
               TimeToString(m_circuitBreakerUntil, TIME_DATE | TIME_SECONDS)));
         }
      }
      else
      {
         m_consecutiveLosses = 0;
      }
   }

   //--- Getters for dashboard / Telegram reports
   int      GetOpenTradeCount()      const { return m_openTradeCount; }
   int      GetConsecLosses()        const { return m_consecutiveLosses; }
   double   GetDailyLossAccum()      const { return m_dailyLossAccum; }
   double   GetDailyStartBalance()   const { return m_dailyStartBalance; }
   double   GetDailyLossPct()        const
   {
      if(m_dailyStartBalance <= 0) return 0.0;
      return (m_dailyLossAccum / m_dailyStartBalance) * 100.0;
   }
   bool     IsCircuitBreakerActive() const { return m_circuitBreakerUntil > TimeGMT(); }
   datetime GetCircuitBreakerUntil() const { return m_circuitBreakerUntil; }
   bool     IsDailyLimitHit()        const { return GetDailyLossPct() <= -DAILY_LOSS_LIMIT_PCT; }

   //--- Manual reset (e.g., after alert acknowledged)
   void ResetCircuitBreaker()
   {
      m_circuitBreakerUntil = 0;
      m_consecutiveLosses   = 0;
      LogInfo("RiskManager", "Circuit breaker manually reset.");
   }
};
