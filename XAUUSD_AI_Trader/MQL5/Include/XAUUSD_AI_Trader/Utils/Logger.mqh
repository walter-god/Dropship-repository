//+------------------------------------------------------------------+
//| Logger.mqh — Centralized file + Print logging                    |
//+------------------------------------------------------------------+
#pragma once
#include "../Config.mqh"

enum ENUM_LOG_LEVEL
{
   LOG_DEBUG   = 0,
   LOG_INFO    = 1,
   LOG_WARNING = 2,
   LOG_ERROR   = 3
};

class CLogger
{
private:
   int            m_fileHandle;
   ENUM_LOG_LEVEL m_minLevel;
   string         m_filePath;

   string LevelStr(ENUM_LOG_LEVEL level)
   {
      switch(level)
      {
         case LOG_DEBUG:   return "DEBUG";
         case LOG_INFO:    return "INFO";
         case LOG_WARNING: return "WARNING";
         case LOG_ERROR:   return "ERROR";
      }
      return "UNKNOWN";
   }

   void EnsureDirectories()
   {
      // MT5 creates subdirs automatically on FileOpen with FILE_COMMON=false
   }

public:
   CLogger() : m_fileHandle(INVALID_HANDLE), m_minLevel(LOG_INFO), m_filePath(LOG_FILE) {}

   bool Init(string filePath = LOG_FILE, ENUM_LOG_LEVEL minLevel = LOG_INFO)
   {
      m_filePath = filePath;
      m_minLevel = minLevel;
      m_fileHandle = FileOpen(m_filePath,
                              FILE_WRITE | FILE_READ | FILE_CSV | FILE_ANSI | FILE_SHARE_READ,
                              ',');
      if(m_fileHandle == INVALID_HANDLE)
      {
         // Attempt to create the file fresh
         m_fileHandle = FileOpen(m_filePath, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
         if(m_fileHandle == INVALID_HANDLE)
         {
            Print("Logger: failed to open log file: ", m_filePath, " error=", GetLastError());
            return false;
         }
         // Write CSV header
         FileWrite(m_fileHandle, "Timestamp", "Level", "Module", "Message");
      }
      else
      {
         // Seek to end to append
         FileSeek(m_fileHandle, 0, SEEK_END);
      }
      return true;
   }

   void Log(ENUM_LOG_LEVEL level, string module, string message)
   {
      if(level < m_minLevel) return;

      string ts   = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS);
      string lvl  = LevelStr(level);
      string line = StringFormat("[%s] [%s] [%s] %s", ts, lvl, module, message);

      Print(line);

      if(m_fileHandle != INVALID_HANDLE)
         FileWrite(m_fileHandle, ts, lvl, module, message);
   }

   void Debug(string module, string message)   { Log(LOG_DEBUG,   module, message); }
   void Info(string module, string message)    { Log(LOG_INFO,    module, message); }
   void Warning(string module, string message) { Log(LOG_WARNING, module, message); }
   void Error(string module, string message)   { Log(LOG_ERROR,   module, message); }

   void Deinit()
   {
      if(m_fileHandle != INVALID_HANDLE)
      {
         FileClose(m_fileHandle);
         m_fileHandle = INVALID_HANDLE;
      }
   }

   ~CLogger() { Deinit(); }
};

// Global logger instance — included once in main EA, referenced elsewhere
CLogger* g_Logger = NULL;

void LogDebug(string module, string msg)   { if(g_Logger) g_Logger.Debug(module, msg); }
void LogInfo(string module, string msg)    { if(g_Logger) g_Logger.Info(module, msg); }
void LogWarning(string module, string msg) { if(g_Logger) g_Logger.Warning(module, msg); }
void LogError(string module, string msg)   { if(g_Logger) g_Logger.Error(module, msg); }
