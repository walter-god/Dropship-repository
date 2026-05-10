//+------------------------------------------------------------------+
//| TelegramBot.mqh — HTTP-based Telegram message sender            |
//|                                                                  |
//| Uses MT5's WebRequest() to POST to the Telegram Bot API.        |
//| IMPORTANT: Add "https://api.telegram.org" to MT5's              |
//|   Tools → Options → Expert Advisors → Allowed URLs list.        |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"
#include "../Strategies/BaseStrategy.mqh"
#include "../Utils/Logger.mqh"
#include "../Risk/RiskManager.mqh"

class CTelegramBot
{
private:
   string m_token;
   string m_chatId;
   string m_baseUrl;

   //--- URL-encode a string (minimal: spaces and special chars)
   string UrlEncode(string s)
   {
      string result = "";
      int len = StringLen(s);
      for(int i = 0; i < len; i++)
      {
         ushort c = StringGetCharacter(s, i);
         if((c >= 'A' && c <= 'Z') ||
            (c >= 'a' && c <= 'z') ||
            (c >= '0' && c <= '9') ||
            c == '-' || c == '_' || c == '.' || c == '~')
         {
            result += ShortToString(c);
         }
         else if(c == ' ')  result += "+";
         else               result += StringFormat("%%%02X", c);
      }
      return result;
   }

   //--- Core send function
   bool SendMessage(string text)
   {
      if(m_token == "" || m_chatId == "")
      {
         LogWarning("Telegram", "Token or ChatID not configured.");
         return false;
      }

      string url = m_baseUrl + "sendMessage";
      string postData = "chat_id=" + UrlEncode(m_chatId) +
                        "&text="   + UrlEncode(text)     +
                        "&parse_mode=Markdown";

      char   postArr[];
      char   result[];
      string headers = "Content-Type: application/x-www-form-urlencoded\r\n";

      StringToCharArray(postData, postArr, 0, StringLen(postData));
      ArrayResize(postArr, ArraySize(postArr) - 1);  // remove null terminator

      string responseHeaders;
      int timeout = 5000;
      int httpCode = WebRequest("POST", url, headers, timeout, postArr, result, responseHeaders);

      if(httpCode == 200)
      {
         LogDebug("Telegram", "Message sent OK");
         return true;
      }
      else
      {
         string resp = CharArrayToString(result);
         LogError("Telegram", StringFormat("Failed httpCode=%d resp=%s", httpCode, resp));
         return false;
      }
   }

public:
   CTelegramBot() : m_token(""), m_chatId(""), m_baseUrl("") {}

   void Init(string token, string chatId)
   {
      m_token   = token;
      m_chatId  = chatId;
      m_baseUrl = "https://api.telegram.org/bot" + token + "/";
      LogInfo("Telegram", "Initialized. ChatID=" + chatId);
   }

   //--- Signal alert (sent on every new trade signal)
   void SendSignalAlert(const STradeSignal &sig, double lots)
   {
      string dir   = sig.isBuy ? "🟢 BUY" : "🔴 SELL";
      string text  = StringFormat(
         "*%s — %s*\n"
         "────────────────\n"
         "📌 Strategy : %s\n"
         "🕐 Time     : %s UTC\n"
         "💹 Entry    : `%.3f`\n"
         "🛑 Stop Loss: `%.3f`\n"
         "🎯 Take Profit: `%.3f`\n"
         "📦 Lot Size : `%.2f`\n"
         "📊 Confidence: `%.0f%%`\n"
         "────────────────\n"
         "_%s_",
         "XAUUSD AI Trader", dir,
         sig.strategyName,
         TimeToString(TimeGMT(), TIME_DATE | TIME_MINUTES),
         sig.entryPrice,
         sig.stopLoss,
         sig.takeProfit,
         lots,
         sig.confidence * 100.0,
         sig.reason);

      SendMessage(text);
   }

   //--- Trade result notification
   void SendTradeResult(string strategy, bool isBuy, double entryPrice,
                         double exitPrice, double pnl, bool isWin)
   {
      string emoji = isWin ? "✅ WIN" : "❌ LOSS";
      string text  = StringFormat(
         "*Trade Closed — %s*\n"
         "Strategy : %s\n"
         "Direction: %s\n"
         "Entry    : `%.3f` → Exit: `%.3f`\n"
         "PnL      : `%+.2f USD`",
         emoji,
         strategy,
         isBuy ? "BUY" : "SELL",
         entryPrice, exitPrice, pnl);

      SendMessage(text);
   }

   //--- Daily summary at 23:00 UTC
   void SendDailySummary(int totalTrades, int wins, double pnl,
                          double dailyLossPct, string strategyHealth)
   {
      double wr   = (totalTrades > 0) ? (double)wins / totalTrades * 100.0 : 0.0;
      string text = StringFormat(
         "*📅 XAUUSD AI — Daily Report*\n"
         "────────────────\n"
         "Trades    : %d (Wins: %d | Losses: %d)\n"
         "Win Rate  : `%.1f%%`\n"
         "Daily PnL : `%+.2f USD` (%.2f%% of balance)\n"
         "────────────────\n"
         "%s",
         totalTrades, wins, totalTrades - wins,
         wr, pnl, dailyLossPct,
         strategyHealth);

      SendMessage(text);
   }

   //--- Circuit breaker / risk alert
   void SendRiskAlert(string alertType, string detail)
   {
      string text = StringFormat(
         "⚠️ *RISK ALERT — %s*\n%s\n_Time: %s UTC_",
         alertType, detail,
         TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS));
      SendMessage(text);
   }

   //--- EA startup notification
   void SendStartupMessage()
   {
      string text = StringFormat(
         "🚀 *XAUUSD AI Trader — ONLINE*\n"
         "Account : `%s`\n"
         "Balance : `%.2f %s`\n"
         "Server  : `%s`\n"
         "Started : `%s UTC`",
         AccountInfoString(ACCOUNT_LOGIN),
         AccountInfoDouble(ACCOUNT_BALANCE),
         AccountInfoString(ACCOUNT_CURRENCY),
         AccountInfoString(ACCOUNT_SERVER),
         TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS));
      SendMessage(text);
   }

   //--- EA shutdown notification
   void SendShutdownMessage(string reason)
   {
      SendMessage("🔴 *XAUUSD AI Trader — OFFLINE*\nReason: " + reason);
   }

   bool IsConfigured() { return (m_token != "" && m_chatId != ""); }
};
