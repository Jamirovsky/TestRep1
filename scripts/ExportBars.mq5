//+------------------------------------------------------------------+
//|  ExportBars.mq5                                                  |
//|  Writes M1 bars (plus the broker's real spread) to a CSV that     |
//|  this repository's loader reads without configuration.            |
//|                                                                   |
//|  Output: MQL5/Files/<SYMBOL>_M1.csv                               |
//|  Copy that file into data/raw/<SYMBOL>/ .                         |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input int    InpYearsBack   = 7;             // how much history to export
input ENUM_TIMEFRAMES InpTF = PERIOD_M1;     // leave at M1 unless you know why
input bool   InpUseUTC      = true;          // convert server time to UTC

//+------------------------------------------------------------------+
int OnStart()
  {
   string symbol = _Symbol;
   datetime to   = TimeCurrent();
   datetime from = to - (datetime)InpYearsBack * 365 * 24 * 60 * 60;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, InpTF, from, to, rates);
   if(copied <= 0)
     {
      PrintFormat("CopyRates failed (%d). Open the chart, press F2 and "
                  "download history first; set Max bars in chart to Unlimited.",
                  GetLastError());
      return(1);
     }

   // Server time is usually UTC+2/+3. Getting this wrong shifts every session
   // filter, so we resolve the offset once and subtract it.
   int offset_sec = 0;
   if(InpUseUTC)
      offset_sec = (int)(TimeCurrent() - TimeGMT());

   string fname = symbol + "_M1.csv";
   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("FileOpen failed (%d)", GetLastError());
      return(1);
     }

   FileWrite(fh, "datetime", "open", "high", "low", "close", "volume", "spread");

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   for(int i = 0; i < copied; i++)
     {
      datetime t = rates[i].time - offset_sec;
      FileWrite(fh,
                TimeToString(t, TIME_DATE | TIME_SECONDS),
                DoubleToString(rates[i].open,  digits),
                DoubleToString(rates[i].high,  digits),
                DoubleToString(rates[i].low,   digits),
                DoubleToString(rates[i].close, digits),
                (long)rates[i].tick_volume,
                (int)rates[i].spread);
     }
   FileClose(fh);

   PrintFormat("Exported %d bars of %s to MQL5/Files/%s (UTC offset %d s). "
               "Copy it into data/raw/%s/",
               copied, symbol, fname, offset_sec, symbol);
   return(0);
  }
//+------------------------------------------------------------------+
