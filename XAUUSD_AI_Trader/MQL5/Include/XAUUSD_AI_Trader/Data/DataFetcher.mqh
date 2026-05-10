//+------------------------------------------------------------------+
//| DataFetcher.mqh — OHLCV data manager (M15 + H4 + D1 caches)     |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Utils/Logger.mqh"

struct SBar
{
   datetime time;
   double   open;
   double   high;
   double   low;
   double   close;
   long     volume;       // tick volume
};

struct SMarketData
{
   // M15 bars  (entry timeframe)
   SBar     m15[];
   int      m15Count;
   // H4 bars   (higher-timeframe trend)
   SBar     h4[];
   int      h4Count;
   // D1 bars   (daily bias)
   SBar     d1[];
   int      d1Count;
   // Current tick info
   double   bid;
   double   ask;
   double   spread;
   // ATR values (pre-computed on M15 and H4)
   double   atrM15;
   double   atrH4;
   // Timestamp of last successful refresh
   datetime lastRefresh;
   // True if data is fresh enough for trading
   bool     isReady;
};

class CDataFetcher
{
private:
   string         m_symbol;
   SMarketData    m_data;
   int            m_atrHandleM15;
   int            m_atrHandleH4;

   bool CopyBarsToStruct(ENUM_TIMEFRAMES tf, int count, SBar &bars[])
   {
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(m_symbol, tf, 0, count, rates);
      if(copied <= 0)
      {
         LogError("DataFetcher", StringFormat("CopyRates failed tf=%d err=%d", tf, GetLastError()));
         return false;
      }
      ArrayResize(bars, copied);
      for(int i = 0; i < copied; i++)
      {
         bars[i].time   = rates[i].time;
         bars[i].open   = rates[i].open;
         bars[i].high   = rates[i].high;
         bars[i].low    = rates[i].low;
         bars[i].close  = rates[i].close;
         bars[i].volume = rates[i].tick_volume;
      }
      return true;
   }

   double GetATR(int handle)
   {
      double buf[];
      ArraySetAsSeries(buf, true);
      if(CopyBuffer(handle, 0, 0, 1, buf) <= 0) return 0.0;
      return buf[0];
   }

public:
   CDataFetcher() : m_symbol(EA_SYMBOL), m_atrHandleM15(INVALID_HANDLE),
                    m_atrHandleH4(INVALID_HANDLE)
   {
      m_data.m15Count   = 0;
      m_data.h4Count    = 0;
      m_data.d1Count    = 0;
      m_data.isReady    = false;
      m_data.lastRefresh = 0;
   }

   bool Init()
   {
      m_atrHandleM15 = iATR(m_symbol, TF_ENTRY,    ATR_PERIOD);
      m_atrHandleH4  = iATR(m_symbol, TF_HTF_TREND, ATR_PERIOD);
      if(m_atrHandleM15 == INVALID_HANDLE || m_atrHandleH4 == INVALID_HANDLE)
      {
         LogError("DataFetcher", "Failed to create ATR handles");
         return false;
      }
      LogInfo("DataFetcher", "Initialized ATR handles for " + m_symbol);
      return Refresh();
   }

   //--- Called every 15 minutes from OnTimer
   bool Refresh()
   {
      bool ok = true;
      ok &= CopyBarsToStruct(TF_ENTRY,    LOOKBACK_BARS, m_data.m15);
      ok &= CopyBarsToStruct(TF_HTF_TREND, LOOKBACK_BARS, m_data.h4);
      ok &= CopyBarsToStruct(TF_DAILY,     60,            m_data.d1);

      if(!ok)
      {
         m_data.isReady = false;
         LogWarning("DataFetcher", "Partial data refresh failure");
         return false;
      }

      m_data.m15Count = ArraySize(m_data.m15);
      m_data.h4Count  = ArraySize(m_data.h4);
      m_data.d1Count  = ArraySize(m_data.d1);

      MqlTick lastTick;
      if(SymbolInfoTick(m_symbol, lastTick))
      {
         m_data.bid    = lastTick.bid;
         m_data.ask    = lastTick.ask;
         m_data.spread = (lastTick.ask - lastTick.bid) /
                         SymbolInfoDouble(m_symbol, SYMBOL_POINT);
      }

      m_data.atrM15    = GetATR(m_atrHandleM15);
      m_data.atrH4     = GetATR(m_atrHandleH4);
      m_data.lastRefresh = TimeGMT();
      m_data.isReady   = (m_data.m15Count >= 50);

      LogInfo("DataFetcher", StringFormat(
         "Refreshed — M15=%d H4=%d D1=%d Bid=%.3f ATR_M15=%.3f",
         m_data.m15Count, m_data.h4Count, m_data.d1Count,
         m_data.bid, m_data.atrM15));
      return true;
   }

   const SMarketData* GetData() const { return &m_data; }

   bool IsReady()         const { return m_data.isReady; }
   double GetBid()        const { return m_data.bid; }
   double GetAsk()        const { return m_data.ask; }
   double GetATRM15()     const { return m_data.atrM15; }
   double GetATRH4()      const { return m_data.atrH4; }
   datetime GetLastRefresh() const { return m_data.lastRefresh; }

   //--- Copy a window of M15 bars (0 = most recent)
   int GetM15Bars(SBar &dst[], int count)
   {
      int n = MathMin(count, m_data.m15Count);
      ArrayResize(dst, n);
      for(int i = 0; i < n; i++) dst[i] = m_data.m15[i];
      return n;
   }

   int GetH4Bars(SBar &dst[], int count)
   {
      int n = MathMin(count, m_data.h4Count);
      ArrayResize(dst, n);
      for(int i = 0; i < n; i++) dst[i] = m_data.h4[i];
      return n;
   }

   int GetD1Bars(SBar &dst[], int count)
   {
      int n = MathMin(count, m_data.d1Count);
      ArrayResize(dst, n);
      for(int i = 0; i < n; i++) dst[i] = m_data.d1[i];
      return n;
   }

   void Deinit()
   {
      if(m_atrHandleM15 != INVALID_HANDLE) IndicatorRelease(m_atrHandleM15);
      if(m_atrHandleH4  != INVALID_HANDLE) IndicatorRelease(m_atrHandleH4);
   }

   ~CDataFetcher() { Deinit(); }
};
