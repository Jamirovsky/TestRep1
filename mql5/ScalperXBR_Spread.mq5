//+------------------------------------------------------------------+
//|  ScalperXBR_Spread.mq5
//|  Brent-WTI spread mean reversion (XBRUSD vs XTIUSD) - pairs EA.
//|
//|  The one idea from the oil-trading research (practitioner + academic
//|  sources, see docs/RESULTS_XBRUSD_V2.md) that showed a net edge on real
//|  OANDA data 2019-2026:
//|    s = ln(Brent) - ln(WTI) on closed M30 bars, z = rolling z-score
//|    over 15.0 days; |z| >= 2.75 -> bet on reversion with equal USD
//|    notional per leg (z>0: sell Brent / buy WTI); exit at |z| <= 1.00,
//|    at |z| >= 99.0 (spread stop) or after 72.0 h.
//|  Backtest 2019-01..2026-10 (Python replica, costs 7 bp/leg + swap):
//|    111 trades  WR 58.6%  PF 1.56  max DD 9.0% (notional 1.50x per leg)
//|    2025-01..2026-10: 28 trades  WR 50.0%  PF 1.76
//|  WARNING: most of the profit comes from two dislocations (Mar-2020 and
//|  2026); in ordinary years it is roughly flat to slightly negative.
//|  Average holding time ~86 h: this is spread arbitrage, not scalping.
//|
//|  Attach to ANY chart. Both symbols must exist (edit names below).
//|  Strategy Tester: "Every tick based on real ticks", multi-symbol.
//+------------------------------------------------------------------+
#property copyright "ScalperXBR_Spread"
#property version   "1.00"
#property description "Brent-WTI spread mean reversion (pairs)"

#include <Trade/Trade.mqh>

input group  "=== Symbols ==="
input string          InpBrent           = "XBRUSD";
input string          InpWti             = "XTIUSD";
input group  "=== Spread model ==="
input ENUM_TIMEFRAMES InpTF              = PERIOD_M30;
input double          InpLookbackDays    = 15.0;     // rolling window for mean / std
input double          InpEntryZ          = 2.75;
input double          InpExitZ           = 1.00;
input double          InpStopZ           = 99.0;     // 99 = no spread stop
input double          InpMaxHoldHours    = 72.0;
input group  "=== Size / execution ==="
input double          InpNotionalPerLeg  = 1.50;    // USD notional per leg as a multiple of equity
input double          InpMaxSpreadBp     = 15.0;       // skip entries if either leg's spread is wider
input int             InpSlippagePoints  = 30;
input long            InpMagic           = 20261130;
input string          InpComment         = "XBR-WTI spread";

CTrade   g_trade;
datetime g_last_bar = 0;

int OnInit()
  {
   if(!SymbolSelect(InpBrent, true) || !SymbolSelect(InpWti, true))
     {
      PrintFormat("symbols %s / %s not available - edit InpBrent / InpWti", InpBrent, InpWti);
      return(INIT_PARAMETERS_INCORRECT);
     }
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   EventSetTimer(5);
   return(INIT_SUCCEEDED);
  }
void OnDeinit(const int reason) { EventKillTimer(); }

//--- z-score of ln(Brent/WTI) on the last CLOSED bar; false if not enough aligned data
bool SpreadZ(double &z)
  {
   int n = (int)MathRound(InpLookbackDays * 86400.0 / PeriodSeconds(InpTF));
   int need = n + 300;
   MqlRates b[], w[];
   ArraySetAsSeries(b, false); ArraySetAsSeries(w, false);
   int nb = CopyRates(InpBrent, InpTF, 1, need, b);
   int nw = CopyRates(InpWti, InpTF, 1, need, w);
   if(nb < n || nw < n)
      return(false);
   // align on identical bar times (both series ascending)
   double s[];
   ArrayResize(s, 0, need);
   int i = 0, j = 0;
   datetime last_t = 0;
   while(i < nb && j < nw)
     {
      if(b[i].time == w[j].time)
        {
         if(b[i].close > 5.0 && w[j].close > 5.0)
           {
            int k = ArraySize(s);
            ArrayResize(s, k + 1, need);
            s[k] = MathLog(b[i].close) - MathLog(w[j].close);
            last_t = b[i].time;
           }
         i++; j++;
        }
      else if(b[i].time < w[j].time) i++;
      else j++;
     }
   int m = ArraySize(s);
   if(m < n || last_t != b[nb - 1].time)       // the latest Brent bar must have a WTI twin
      return(false);
   double mean = 0.0, sq = 0.0;
   for(int k = m - n; k < m; k++) mean += s[k];
   mean /= n;
   for(int k = m - n; k < m; k++) sq += (s[k] - mean) * (s[k] - mean);
   double sd = MathSqrt(sq / (n - 1));          // sample std, as pandas
   if(sd <= 0.0)
      return(false);
   z = (s[m - 1] - mean) / sd;
   return(true);
  }

bool LegOpen(string sym, ulong &ticket, long &type, datetime &opened)
  {
   for(int k = PositionsTotal() - 1; k >= 0; k--)
     {
      ulong t = PositionGetTicket(k);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == InpMagic)
        {
         ticket = t;
         type = PositionGetInteger(POSITION_TYPE);
         opened = (datetime)PositionGetInteger(POSITION_TIME);
         return(true);
        }
     }
   return(false);
  }

double LotsForNotional(string sym, double usd)
  {
   double px = SymbolInfoDouble(sym, SYMBOL_ASK);
   double cs = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   double st = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double mn = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(px <= 0.0 || cs <= 0.0 || st <= 0.0)
      return(0.0);
   double lots = MathFloor(usd / (px * cs) / st + 1e-9) * st;
   if(lots < mn) return(0.0);
   if(lots > mx) lots = mx;
   return(NormalizeDouble(lots, (int)MathMax(0, MathCeil(-MathLog10(st) - 1e-9))));
  }

double SpreadBp(string sym)
  {
   double a = SymbolInfoDouble(sym, SYMBOL_ASK), b = SymbolInfoDouble(sym, SYMBOL_BID);
   return(b > 0.0 ? (a - b) / b * 1e4 : 1e9);
  }

void CloseAll()
  {
   ulong t; long ty; datetime op;
   if(LegOpen(InpBrent, t, ty, op)) g_trade.PositionClose(t);
   if(LegOpen(InpWti, t, ty, op))   g_trade.PositionClose(t);
  }

void Step()
  {
   datetime bt = iTime(InpBrent, InpTF, 0);
   if(bt == 0 || bt == g_last_bar)
      return;                                   // act once per closed bar
   double z;
   if(!SpreadZ(z))
      return;
   g_last_bar = bt;

   ulong tb, tw; long yb, yw; datetime ob, ow;
   bool hb = LegOpen(InpBrent, tb, yb, ob);
   bool hw = LegOpen(InpWti, tw, yw, ow);
   if(hb != hw)                                  // orphan leg: flatten
     {
      CloseAll();
      return;
     }
   if(hb)
     {
      double held_h = (double)(TimeCurrent() - ob) / 3600.0;
      if(MathAbs(z) <= InpExitZ || MathAbs(z) >= InpStopZ || held_h >= InpMaxHoldHours)
         CloseAll();
      return;
     }
   if(MathAbs(z) < InpEntryZ)
      return;
   if(SpreadBp(InpBrent) > InpMaxSpreadBp || SpreadBp(InpWti) > InpMaxSpreadBp)
      return;
   double usd = AccountInfoDouble(ACCOUNT_EQUITY) * InpNotionalPerLeg;
   double lb = LotsForNotional(InpBrent, usd), lw = LotsForNotional(InpWti, usd);
   if(lb <= 0.0 || lw <= 0.0)
      return;
   bool longBrent = (z < 0.0);
   g_trade.SetTypeFillingBySymbol(InpBrent);
   bool ok1 = longBrent ? g_trade.Buy(lb, InpBrent, 0.0, 0.0, 0.0, InpComment)
                        : g_trade.Sell(lb, InpBrent, 0.0, 0.0, 0.0, InpComment);
   if(!ok1)
      return;
   g_trade.SetTypeFillingBySymbol(InpWti);
   bool ok2 = longBrent ? g_trade.Sell(lw, InpWti, 0.0, 0.0, 0.0, InpComment)
                        : g_trade.Buy(lw, InpWti, 0.0, 0.0, 0.0, InpComment);
   if(!ok2)
      CloseAll();                                // never keep a naked leg
  }

void OnTimer() { Step(); }
void OnTick()  { Step(); }
//+------------------------------------------------------------------+
