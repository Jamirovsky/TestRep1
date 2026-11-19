//+------------------------------------------------------------------+
//|                                                  AMS_BTCUSD.mq5  |
//|  Adaptive Memory Scalper - BTCUSD (Capital Point Trading, MT5)   |
//|                                                                  |
//|  Port of the Python research engine (scalper/engine.py).         |
//|  Signal : volatility-normalised impulse continuation on M15      |
//|  Filter : 7-day momentum state ("market memory")                 |
//|  Memory : shadow (paper) trades per cell (direction x momentum   |
//|           state); exponentially-weighted expectancy in R gates   |
//|           real trades.  Rebuilt from M1 history on start-up and  |
//|           saved to MQL5\Files\AMS_BTCUSD_<sleeve>.mem            |
//|  Exits  : ATR-scaled stop / target + time stop                   |
//|  Sizing : % risk of sleeve equity, broker minimum-lot rule for   |
//|           small accounts, margin check                           |
//|                                                                  |
//|  Attach to ANY chart of the BTCUSD symbol (timeframe irrelevant, |
//|  the EA reads M15 and M1 itself).  Use a HEDGING account.        |
//+------------------------------------------------------------------+
#property copyright "AMS research"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- general
input group "Account / risk"
input double InpRiskPerTrade   = 0.02;   // risk per trade (fraction of sleeve equity)
input double InpMinLotRiskCap  = 0.05;   // allow broker min lot if its risk <= this fraction of sleeve equity
input double InpMarginUse      = 0.80;   // max fraction of free margin to use
input double InpSlipUSD        = 5.0;    // assumed stop slippage, USD per BTC (sizing + memory)
input double InpMinStopSpread  = 2.0;    // stop distance must be >= this x current spread
input double InpModelSpreadUSD = 0.0;    // spread for memory replay (0 = current symbol spread)
input int    InpMemoryDays     = 60;     // days of M1 history replayed to rebuild memory
input bool   InpVerbose        = true;

input group "Sleeve A (plateau, no memory gate)"
input bool   A_Enabled  = true;
input double A_Weight   = 0.5;           // share of account equity
input int    A_ImpN     = 4;             // impulse length (M15 bars)
input double A_ImpThr   = 2.0;           // impulse threshold (z, ATR*sqrt(n) units)
input double A_SLk      = 3.5;           // stop  = SLk x ATR(14, M15)
input double A_TPk      = 6.5;           // target = TPk x ATR
input int    A_MaxHold  = 28;            // max holding time in M15 bars
input bool   A_MemGate  = false;         // gate trades with memory
input int    A_MemWarm  = 0;
input double A_MemThr   = -1e9;
input bool   A_MemByMom = false;         // memory cells also keyed by 7-day momentum state
input long   A_Magic    = 26111901;

input group "Sleeve B (memory gated)"
input bool   B_Enabled  = true;
input double B_Weight   = 0.5;
input int    B_ImpN     = 3;
input double B_ImpThr   = 2.2;
input double B_SLk      = 2.5;
input double B_TPk      = 5.0;
input int    B_MaxHold  = 48;
input bool   B_MemGate  = true;
input int    B_MemWarm  = 5;             // shadow results needed before a cell may trade
input double B_MemThr   = 0.0;           // cell EW expectancy (R) must exceed this
input bool   B_MemByMom = true;
input long   B_Magic    = 26111902;

input group "Common signal settings"
input int    InpAtrN       = 14;
input int    InpMomDays    = 7;          // momentum lookback (days) for the trend filter
input bool   InpTrendFilter = true;
input double InpMemAlpha   = 0.10;       // EW memory learning rate

//--- constants
#define TF_MIN   15
#define NCELL    4
#define HIST_M15 1200

struct Shadow
  {
   bool     active;
   int      dir;
   double   entry, sl, tp, stopd;
   datetime start;
  };

struct Sleeve
  {
   string   name;
   bool     enabled;
   double   weight;
   int      impN;
   double   impThr, slk, tpk;
   int      maxHold;
   bool     memGate;
   int      memWarm;
   double   memThr;
   bool     memByMom;
   long     magic;
   double   memR[NCELL];
   int      memN[NCELL];
   Shadow   sh[NCELL];
  };

Sleeve   S[2];
CTrade   trade;
datetime g_lastM15 = 0;
double   g_point;
int      g_digits;

//+------------------------------------------------------------------+
int CellOf(const int dir, const int bucket) { return bucket * 2 + (dir > 0 ? 1 : 0); }

//+------------------------------------------------------------------+
//| Wilder ATR on a chronological array (index 0 = oldest)           |
//+------------------------------------------------------------------+
void ComputeATR(const MqlRates &r[], const int n, double &atr[])
  {
   int cnt = ArraySize(r);
   ArrayResize(atr, cnt);
   double a = 1.0 / n;                       // ema(tr, 2n-1)  => alpha = 1/n
   for(int i = 0; i < cnt; i++)
     {
      double tr = r[i].high - r[i].low;
      if(i > 0)
         tr = MathMax(tr, MathMax(MathAbs(r[i].high - r[i - 1].close), MathAbs(r[i].low - r[i - 1].close)));
      atr[i] = (i == 0) ? tr : a * tr + (1.0 - a) * atr[i - 1];
     }
  }

//+------------------------------------------------------------------+
//| Signal on closed M15 bar k of chronological array r              |
//| returns dir (+1/-1/0); bucket = momentum state (1 up, 0 down)    |
//+------------------------------------------------------------------+
int SignalAt(const Sleeve &s, const MqlRates &r[], const double &atr[], const int k, int &bucket)
  {
   int momN = InpMomDays * 1440 / TF_MIN;
   int warm = (int)MathMax(MathMax(InpAtrN * 3, s.impN), momN) + 3;
   bucket = 0;
   if(k < warm || atr[k] <= 0 || atr[k - 1] <= 0)
      return 0;
   bool momUp = r[k].close > r[k - momN].close;
   bucket = (s.memByMom && momUp) ? 1 : 0;
   double sq = MathSqrt((double)s.impN);
   double z1 = (r[k].close - r[k - s.impN].close) / (atr[k] * sq);
   double z0 = (r[k - 1].close - r[k - 1 - s.impN].close) / (atr[k - 1] * sq);
   int dir = 0;
   if(z1 > s.impThr && z0 <= s.impThr)
      dir = 1;
   else
      if(z1 < -s.impThr && z0 >= -s.impThr)
         dir = -1;
   if(dir != 0 && InpTrendFilter && dir != (momUp ? 1 : -1))
      dir = 0;
   return dir;
  }

//+------------------------------------------------------------------+
void MemUpdate(Sleeve &s, const int cell, const double R)
  {
   if(s.memN[cell] == 0)
      s.memR[cell] = 0.5 * R;                 // shrink first observation
   else
      s.memR[cell] = (1.0 - InpMemAlpha) * s.memR[cell] + InpMemAlpha * R;
   s.memN[cell]++;
  }

//+------------------------------------------------------------------+
//| Open a shadow trade if the cell is free                          |
//+------------------------------------------------------------------+
void ShadowOpen(Sleeve &s, const int cell, const int dir, const double entry, const double stopd,
                const double tgtd, const datetime t)
  {
   if(s.sh[cell].active)
      return;
   s.sh[cell].active = true;
   s.sh[cell].dir    = dir;
   s.sh[cell].entry  = entry;
   s.sh[cell].stopd  = stopd;
   s.sh[cell].sl     = entry - dir * stopd;
   s.sh[cell].tp     = entry + dir * tgtd;
   s.sh[cell].start  = t;
  }

//+------------------------------------------------------------------+
//| Update shadows with a bar/tick range. bidLo/bidHi/bidOpen/bidCl   |
//| are BID prices; spread converts to ASK for shorts.                |
//+------------------------------------------------------------------+
void ShadowStep(Sleeve &s, const double bidOpen, const double bidHi, const double bidLo,
                const double bidCl, const double spread, const datetime now)
  {
   for(int c = 0; c < NCELL; c++)
     {
      if(!s.sh[c].active)
         continue;
      Shadow sh = s.sh[c];
      double xp = 0;
      bool done = false;
      if(sh.dir > 0)
        {
         if(bidLo <= sh.sl)          { xp = MathMin(sh.sl, bidOpen) - InpSlipUSD; done = true; }
         else if(bidHi >= sh.tp)     { xp = sh.tp; done = true; }
        }
      else
        {
         if(bidHi + spread >= sh.sl) { xp = MathMax(sh.sl, bidOpen + spread) + InpSlipUSD; done = true; }
         else if(bidLo + spread <= sh.tp) { xp = sh.tp; done = true; }
        }
      if(!done && now - sh.start >= (long)s.maxHold * TF_MIN * 60)
        {
         xp = (sh.dir > 0) ? bidCl : bidCl + spread;
         done = true;
        }
      if(done)
        {
         double R = (xp - sh.entry) * sh.dir / sh.stopd;
         MemUpdate(s, c, R);
         s.sh[c].active = false;
        }
     }
  }

//+------------------------------------------------------------------+
//| Rebuild memory: replay the last InpMemoryDays on M1 bars           |
//+------------------------------------------------------------------+
bool RebuildMemory(Sleeve &s, const double spread)
  {
   for(int c = 0; c < NCELL; c++) { s.memR[c] = 0; s.memN[c] = 0; s.sh[c].active = false; }
   int momN = InpMomDays * 1440 / TF_MIN;
   int needM15 = InpMemoryDays * 96 + momN + InpAtrN * 3 + 50;
   MqlRates m15[];
   ArraySetAsSeries(m15, false);
   int got15 = CopyRates(_Symbol, PERIOD_M15, 1, needM15, m15);
   if(got15 < momN + 100)
     {
      PrintFormat("%s: not enough M15 history (%d bars) - memory starts empty", s.name, got15);
      return false;
     }
   double atr[];
   ComputeATR(m15, InpAtrN, atr);
   datetime from = m15[got15 - 1].time - (datetime)InpMemoryDays * 86400;
   MqlRates m1[];
   ArraySetAsSeries(m1, false);
   int got1 = CopyRates(_Symbol, PERIOD_M1, from, TimeCurrent(), m1);
   if(got1 < 1440)
     {
      PrintFormat("%s: not enough M1 history (%d bars) - memory starts empty", s.name, got1);
      return false;
     }
   // index of M15 bar by open time
   int k = 0;
   for(int i = 0; i < got1; i++)
     {
      datetime t = m1[i].time;
      // M15 bar that closed just before this minute -> entry at this minute's open
      if(((long)t) % (TF_MIN * 60) == 0)
        {
         datetime prevOpen = t - TF_MIN * 60;
         while(k < got15 - 1 && m15[k].time < prevOpen)
            k++;
         if(m15[k].time == prevOpen)
           {
            int bucket;
            int dir = SignalAt(s, m15, atr, k, bucket);
            double stopd = s.slk * atr[k];
            if(dir != 0 && stopd >= InpMinStopSpread * spread)
              {
               double px = (dir > 0) ? m1[i].open + spread : m1[i].open;
               ShadowOpen(s, CellOf(dir, bucket), dir, px, stopd, s.tpk * atr[k], t);
              }
           }
        }
      ShadowStep(s, m1[i].open, m1[i].high, m1[i].low, m1[i].close, spread, t);
     }
   return true;
  }

//+------------------------------------------------------------------+
void SaveMemory(const Sleeve &s)
  {
   int h = FileOpen("AMS_BTCUSD_" + s.name + ".mem", FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
   if(h == INVALID_HANDLE)
      return;
   FileWrite(h, "cell", "dir", "momstate", "ewR", "n", "shadow_active", "shadow_dir", "entry", "sl", "tp", "stopd", "start");
   for(int c = 0; c < NCELL; c++)
      FileWrite(h, c, ((c % 2) == 1 ? "long" : "short"), ((c / 2) == 1 ? "up" : "down/none"),
                DoubleToString(s.memR[c], 4), s.memN[c], (int)s.sh[c].active, s.sh[c].dir,
                DoubleToString(s.sh[c].entry, 2), DoubleToString(s.sh[c].sl, 2), DoubleToString(s.sh[c].tp, 2),
                DoubleToString(s.sh[c].stopd, 2), (long)s.sh[c].start);
   FileClose(h);
  }

//+------------------------------------------------------------------+
bool LoadMemory(Sleeve &s)
  {
   int h = FileOpen("AMS_BTCUSD_" + s.name + ".mem", FILE_READ | FILE_CSV | FILE_ANSI, ';');
   if(h == INVALID_HANDLE)
      return false;
   for(int i = 0; i < 12; i++) FileReadString(h);                     // header
   for(int c = 0; c < NCELL && !FileIsEnding(h); c++)
     {
      int cell = (int)StringToInteger(FileReadString(h));
      FileReadString(h); FileReadString(h);
      s.memR[cell] = StringToDouble(FileReadString(h));
      s.memN[cell] = (int)StringToInteger(FileReadString(h));
      s.sh[cell].active = (StringToInteger(FileReadString(h)) == 1);
      s.sh[cell].dir    = (int)StringToInteger(FileReadString(h));
      s.sh[cell].entry  = StringToDouble(FileReadString(h));
      s.sh[cell].sl     = StringToDouble(FileReadString(h));
      s.sh[cell].tp     = StringToDouble(FileReadString(h));
      s.sh[cell].stopd  = StringToDouble(FileReadString(h));
      s.sh[cell].start  = (datetime)StringToInteger(FileReadString(h));
     }
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
int OpenPositions(const long magic)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == magic)
         n++;
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Time stop for real positions                                      |
//+------------------------------------------------------------------+
void ManageTimeStops(const Sleeve &s)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != s.magic)
         continue;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(TimeCurrent() - opened >= (long)s.maxHold * TF_MIN * 60)
        {
         trade.SetExpertMagicNumber(s.magic);
         if(trade.PositionClose(tk) && InpVerbose)
            PrintFormat("%s: time stop closed #%I64u", s.name, tk);
        }
     }
  }

//+------------------------------------------------------------------+
//| Lot size: risk-based, broker min-lot rule, margin check            |
//+------------------------------------------------------------------+
double LotsFor(const Sleeve &s, const int dir, const double price, const double stopd)
  {
   double eq    = AccountInfoDouble(ACCOUNT_EQUITY) * s.weight;
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   ENUM_ORDER_TYPE ot = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double lossPerLot = 0;
   double stopPx = price - dir * (stopd + InpSlipUSD);
   if(!OrderCalcProfit(ot, _Symbol, 1.0, price, stopPx, lossPerLot) || lossPerLot >= 0)
      return 0;
   lossPerLot = -lossPerLot;                                   // account currency per 1 lot
   double lots = eq * InpRiskPerTrade / lossPerLot;
   lots = MathFloor(lots / vstep + 1e-9) * vstep;
   if(lots < vmin)
     {
      if(vmin * lossPerLot <= InpMinLotRiskCap * eq)
         lots = vmin;                                          // small-account rule
      else
         return 0;
     }
   lots = MathMin(lots, vmax);
   double margin = 0;
   double free = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   while(lots >= vmin)
     {
      if(OrderCalcMargin(ot, _Symbol, lots, price, margin) && margin <= free * InpMarginUse)
         break;
      lots -= vstep;
     }
   if(lots < vmin - 1e-12)
      return 0;
   return NormalizeDouble(lots, 8);
  }

//+------------------------------------------------------------------+
void OnNewM15(Sleeve &s, const double spread)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(_Symbol, PERIOD_M15, 1, HIST_M15, r);   // closed bars only
   if(got < InpMomDays * 96 + 100)
      return;
   double atr[];
   ComputeATR(r, InpAtrN, atr);
   int k = got - 1;
   int bucket;
   int dir = SignalAt(s, r, atr, k, bucket);
   if(dir == 0)
      return;
   double stopd = s.slk * atr[k];
   double tgtd  = s.tpk * atr[k];
   if(stopd < InpMinStopSpread * spread)
     {
      if(InpVerbose) PrintFormat("%s: signal %d skipped, stop %.1f < %.1f x spread", s.name, dir, stopd, InpMinStopSpread);
      return;
     }
   MqlTick tk;
   SymbolInfoTick(_Symbol, tk);
   double px = (dir > 0) ? tk.ask : tk.bid;
   int cell = CellOf(dir, bucket);
   ShadowOpen(s, cell, dir, px, stopd, tgtd, TimeCurrent());
   bool allowed = !s.memGate || (s.memN[cell] >= s.memWarm && s.memR[cell] > s.memThr);
   if(InpVerbose)
      PrintFormat("%s: signal %s ATR=%.1f cell=%d memR=%.3f n=%d -> %s", s.name, dir > 0 ? "BUY" : "SELL",
                  atr[k], cell, s.memR[cell], s.memN[cell], allowed ? "TRADE" : "blocked by memory");
   if(!allowed || OpenPositions(s.magic) > 0)
      return;
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING && PositionSelect(_Symbol))
     {
      if(InpVerbose) PrintFormat("%s: netting account and a position exists - skipped", s.name);
      return;
     }
   double lots = LotsFor(s, dir, px, stopd);
   if(lots <= 0)
     {
      if(InpVerbose) PrintFormat("%s: lot size below broker minimum for the risk budget - skipped", s.name);
      return;
     }
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   double sl = NormalizeDouble(px - dir * MathMax(stopd, minDist), g_digits);
   double tp = NormalizeDouble(px + dir * MathMax(tgtd, minDist), g_digits);
   trade.SetExpertMagicNumber(s.magic);
   bool ok = (dir > 0) ? trade.Buy(lots, _Symbol, 0, sl, tp, "AMS " + s.name)
                       : trade.Sell(lots, _Symbol, 0, sl, tp, "AMS " + s.name);
   PrintFormat("%s: %s %.2f lots SL %.2f TP %.2f -> %s (%d)", s.name, dir > 0 ? "BUY" : "SELL", lots, sl, tp,
               ok ? "sent" : "FAILED", trade.ResultRetcode());
  }

//+------------------------------------------------------------------+
double CurrentSpreadUSD()
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * g_point;
   return tk.ask - tk.bid;
  }

//+------------------------------------------------------------------+
void InitSleeve(Sleeve &s, string name, bool en, double w, int n, double thr, double slk, double tpk, int mh,
                bool gate, int warm, double mthr, bool bymom, long magic)
  {
   s.name = name; s.enabled = en; s.weight = w; s.impN = n; s.impThr = thr; s.slk = slk; s.tpk = tpk;
   s.maxHold = mh; s.memGate = gate; s.memWarm = warm; s.memThr = mthr; s.memByMom = bymom; s.magic = magic;
   for(int c = 0; c < NCELL; c++) { s.memR[c] = 0; s.memN[c] = 0; s.sh[c].active = false; }
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(200);
   InitSleeve(S[0], "A", A_Enabled, A_Weight, A_ImpN, A_ImpThr, A_SLk, A_TPk, A_MaxHold, A_MemGate, A_MemWarm,
              A_MemThr, A_MemByMom, A_Magic);
   InitSleeve(S[1], "B", B_Enabled, B_Weight, B_ImpN, B_ImpThr, B_SLk, B_TPk, B_MaxHold, B_MemGate, B_MemWarm,
              B_MemThr, B_MemByMom, B_Magic);
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      Print("WARNING: account is not in hedging mode - the two sleeves cannot hold separate positions.");
   double spread = (InpModelSpreadUSD > 0) ? InpModelSpreadUSD : CurrentSpreadUSD();
   for(int i = 0; i < 2; i++)
     {
      if(!S[i].enabled) continue;
      if(!RebuildMemory(S[i], spread))
         if(LoadMemory(S[i]))
            PrintFormat("%s: memory loaded from file", S[i].name);
      SaveMemory(S[i]);
      for(int c = 0; c < NCELL; c++)
         if(S[i].memN[c] > 0)
            PrintFormat("%s memory cell %d (%s, mom %s): ewR=%.3f n=%d", S[i].name, c, ((c % 2) == 1) ? "long" : "short",
                        ((c / 2) == 1) ? "up" : "down/none", S[i].memR[c], S[i].memN[c]);
     }
   g_lastM15 = iTime(_Symbol, PERIOD_M15, 0);
   EventSetTimer(60);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int i = 0; i < 2; i++)
      if(S[i].enabled) SaveMemory(S[i]);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double spread = tk.ask - tk.bid;
   // 1) a new M15 bar closed -> evaluate signals (same order as the backtest engine:
   //    entries first, then shadow exits on the same price update)
   datetime t15 = iTime(_Symbol, PERIOD_M15, 0);
   if(t15 != g_lastM15 && t15 > 0)
     {
      g_lastM15 = t15;
      for(int i = 0; i < 2; i++)
         if(S[i].enabled) { OnNewM15(S[i], spread); SaveMemory(S[i]); }
     }
   // 2) shadows follow live prices; memory is updated when they close
   for(int i = 0; i < 2; i++)
     {
      if(!S[i].enabled) continue;
      int before = 0;
      for(int c = 0; c < NCELL; c++) before += S[i].memN[c];
      ShadowStep(S[i], tk.bid, tk.bid, tk.bid, tk.bid, spread, TimeCurrent());
      int after = 0;
      for(int c = 0; c < NCELL; c++) after += S[i].memN[c];
      if(after != before) SaveMemory(S[i]);
      ManageTimeStops(S[i]);
     }
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   // keeps time stops working during quiet periods with few ticks
   for(int i = 0; i < 2; i++)
      if(S[i].enabled) ManageTimeStops(S[i]);
  }
//+------------------------------------------------------------------+
