//+------------------------------------------------------------------+
//| TradeExecutor.mqh — CTrade-based MT5 order execution            |
//+------------------------------------------------------------------+
#pragma once
#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include "../Config.mqh"
#include "../Utils/Logger.mqh"
#include "../Risk/RiskManager.mqh"
#include "../Strategies/BaseStrategy.mqh"
#include "../Database/DBManager.mqh"

class CTradeExecutor
{
private:
   CTrade          m_trade;
   CPositionInfo   m_pos;
   CRiskManager*   m_risk;
   CDBManager*     m_db;

   int m_slippage;   // max slippage in points

   //--- Normalize price to broker's tick size
   double NormalizePrice(double price)
   {
      double tickSize = SymbolInfoDouble(EA_SYMBOL, SYMBOL_TRADE_TICK_SIZE);
      if(tickSize <= 0) return price;
      return MathRound(price / tickSize) * tickSize;
   }

   //--- Count EA's open positions on XAUUSD
   int CountOpenPositions()
   {
      int cnt = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(m_pos.SelectByIndex(i) &&
            m_pos.Symbol() == EA_SYMBOL &&
            m_pos.Magic()  == EA_MAGIC)
            cnt++;
      }
      return cnt;
   }

   //--- Check if we already have an open position from the same strategy
   bool HasOpenPosition(string strategyName)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(m_pos.SelectByIndex(i) &&
            m_pos.Symbol()  == EA_SYMBOL &&
            m_pos.Magic()   == EA_MAGIC &&
            m_pos.Comment() == strategyName)
            return true;
      }
      return false;
   }

public:
   CTradeExecutor() : m_risk(NULL), m_db(NULL), m_slippage(30) {}

   void Init(CRiskManager* risk, CDBManager* db)
   {
      m_risk = risk;
      m_db   = db;
      m_trade.SetExpertMagicNumber(EA_MAGIC);
      m_trade.SetDeviationInPoints(m_slippage);
      m_trade.SetTypeFilling(ORDER_FILLING_FOK);
      LogInfo("TradeExecutor", "Initialized.");
   }

   //--- Main entry point: attempt to execute a signal
   bool Execute(const STradeSignal &sig)
   {
      if(!sig.isValid)    return false;
      if(!m_risk || !m_db) return false;

      // Risk gate
      ENUM_TRADE_BLOCK_REASON block = m_risk.CanOpenTrade();
      if(block != BLOCK_NONE)
      {
         LogWarning("TradeExecutor", StringFormat(
            "Trade blocked by risk manager: reason=%d strategy=%s",
            block, sig.strategyName));
         return false;
      }

      // Prevent duplicate strategy positions
      if(HasOpenPosition(sig.strategyName))
      {
         LogInfo("TradeExecutor", sig.strategyName + " already has an open position.");
         return false;
      }

      // Validate R:R
      if(!m_risk.ValidateRR(sig.entryPrice, sig.stopLoss, sig.takeProfit))
         return false;

      double lots = m_risk.CalcLotSize(sig.entryPrice, sig.stopLoss);
      if(lots <= 0)
      {
         LogError("TradeExecutor", "Lot size calculation returned 0");
         return false;
      }

      double sl = NormalizePrice(sig.stopLoss);
      double tp = NormalizePrice(sig.takeProfit);

      bool ok;
      if(sig.isBuy)
         ok = m_trade.Buy(lots, EA_SYMBOL, 0, sl, tp, sig.strategyName);
      else
         ok = m_trade.Sell(lots, EA_SYMBOL, 0, sl, tp, sig.strategyName);

      if(!ok)
      {
         LogError("TradeExecutor", StringFormat(
            "Order failed: %s retcode=%d err=%d",
            sig.isBuy ? "BUY" : "SELL",
            m_trade.ResultRetcode(),
            GetLastError()));
         return false;
      }

      m_risk.OnTradeOpened();
      LogInfo("TradeExecutor", StringFormat(
         "OPENED %s %s %.2f lots @ %.3f SL=%.3f TP=%.3f Conf=%.0f%%",
         sig.strategyName, sig.isBuy ? "BUY" : "SELL",
         lots, sig.entryPrice, sl, tp, sig.confidence * 100.0));

      return true;
   }

   //--- Called from OnTradeTransaction to log closed trades
   void OnPositionClosed(ulong ticket, string strategy,
                         double entryPrice, double exitPrice,
                         double sl, double tp, double lots,
                         bool isBuy, datetime openTime)
   {
      double pointVal = SymbolInfoDouble(EA_SYMBOL, SYMBOL_TRADE_TICK_VALUE) /
                        SymbolInfoDouble(EA_SYMBOL, SYMBOL_TRADE_TICK_SIZE);
      double pnl      = (isBuy ? (exitPrice - entryPrice) : (entryPrice - exitPrice))
                        * lots * pointVal;
      bool   isWin    = (pnl > 0);

      m_risk.OnTradeClosed(pnl);

      STradeRecord rec;
      rec.strategy   = strategy;
      rec.direction  = isBuy ? "BUY" : "SELL";
      rec.entryPrice = entryPrice;
      rec.exitPrice  = exitPrice;
      rec.stopLoss   = sl;
      rec.takeProfit = tp;
      rec.lotSize    = lots;
      rec.pnl        = pnl;
      rec.confidence = 0;   // filled by caller if available
      rec.openTime   = openTime;
      rec.closeTime  = TimeGMT();
      rec.isWin      = isWin;
      m_db.LogTrade(rec);

      LogInfo("TradeExecutor", StringFormat(
         "CLOSED %s %s #%I64u PnL=%.2f %s",
         strategy, isBuy ? "BUY" : "SELL", ticket, pnl, isWin ? "WIN" : "LOSS"));
   }

   //--- Emergency close all positions (triggered by daily loss limit)
   void CloseAllPositions(string reason)
   {
      LogWarning("TradeExecutor", "CLOSE ALL: " + reason);
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(m_pos.SelectByIndex(i) &&
            m_pos.Symbol() == EA_SYMBOL &&
            m_pos.Magic()  == EA_MAGIC)
         {
            m_trade.PositionClose(m_pos.Ticket());
         }
      }
   }

   int GetOpenPositionCount() { return CountOpenPositions(); }
};
