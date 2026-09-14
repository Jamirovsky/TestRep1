//+------------------------------------------------------------------+
//|  ScalperXG.mq5                                                   |
//|  Session-filtered intraday scalper for XAUUSD and EURUSD.        |
//|                                                                   |
//|  This is a direct port of src/scalping/strategy.py. The entry     |
//|  logic, the Efficiency-Ratio gate, the ATR stop and the trade     |
//|  management are the same code path expressed twice, so a result   |
//|  from the Python backtester and a result from the MT5 Strategy    |
//|  Tester should agree to within fill modelling.                    |
//|                                                                   |
//|  BEFORE RUNNING THIS ON A LIVE ACCOUNT - READ docs/RESULTS.md     |
//|  The defaults below are the XAUUSD parameters from                |
//|  config/XAUUSD_momentum_base.json. They were fitted on SYNTHETIC  |
//|  data, because the machine this was built on could not reach any  |
//|  market-data provider, and even on that data they reached a       |
//|  profit factor of only 1.10 out of sample (win rate 50.8% over    |
//|  1195 trades, t = 1.47 - not statistically significant), and the  |
//|  edge disappears at 1.4x the modelled transaction costs.          |
//|                                                                   |
//|  For EURUSD the research found NO edge that survives costs at all |
//|  (out-of-sample profit factor 0.86, t = -3.01). Do not simply     |
//|  point this EA at EURUSD.                                         |
//|                                                                   |
//|  Re-run the optimiser on your own broker's history (see           |
//|  data/README.md), paste the resulting parameters in, and test in  |
//|  the Strategy Tester on "Every tick based on real ticks" before   |
//|  risking money.                                                   |
//+------------------------------------------------------------------+
#property copyright "ScalperXG"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- strategy modes, matching strategy.py
enum ENUM_SCALP_MODE
  {
   MODE_BREAKOUT = 0,   // Donchian break + trend + volatility expansion
   MODE_MOMENTUM = 1,   // net move over N bars, ER-gated
   MODE_PULLBACK = 2,   // trend continuation after a retracement
   MODE_FADE     = 3    // mean reversion to session VWAP
  };

input group           "=== Strategy ==="
input ENUM_SCALP_MODE InpMode            = MODE_MOMENTUM;
input ENUM_TIMEFRAMES InpSignalTF        = PERIOD_M15; // signal timeframe
input int             InpSessionStartUTC = 12;         // inclusive, UTC hour
input int             InpSessionEndUTC   = 18;         // exclusive, UTC hour (NY session)

input group           "=== Regime filters ==="
input int             InpAtrPeriod       = 14;
input int             InpAtrRankLookback = 288;        // bars for the vol-regime rank
input double          InpAtrRankMin      = 0.10;
input double          InpAtrRankMax      = 0.99;
input int             InpErPeriod        = 24;         // Efficiency Ratio window
input double          InpErMin           = 0.30;       // 0 disables
input double          InpErMax           = 1.00;       // <1 demands chop (fade)

input group           "=== Entry (breakout) ==="
input int             InpDonPeriod       = 24;
input int             InpEmaFast         = 12;
input int             InpEmaSlow         = 48;
input int             InpAdxPeriod       = 14;
input double          InpAdxMin          = 18.0;
input double          InpExpansionMult   = 1.10;
input int             InpAtrAvgPeriod    = 48;

input group           "=== Entry (momentum) ==="
input int             InpMomPeriod       = 12;
input double          InpMomMinAtr       = 1.0;
input bool            InpMomConfirm      = true;

input group           "=== Entry (pullback) ==="
input int             InpPbSlopePeriod   = 30;
input int             InpRsiPeriod       = 7;
input double          InpPbRsiLo         = 40.0;
input double          InpPbRsiHi         = 60.0;
input double          InpPbDepthAtr      = 0.5;
input int             InpPbLookback      = 6;

input group           "=== Entry (fade) ==="
input double          InpBandK           = 2.0;
input double          InpRsiLo           = 25.0;
input double          InpRsiHi           = 75.0;
input double          InpAdxMax          = 25.0;
input int             InpConfirmMode     = 2;   // 0 none 1 rejection 2 turn 3 strong turn

input group           "=== Risk and exits ==="
input double          InpRiskPct         = 0.005;  // fraction of equity per trade
input double          InpSlAtr           = 2.0;    // stop = InpSlAtr * ATR
input double          InpMinSlPoints     = 750;    // stop floor in POINTS (gold: USD 7.50)
input double          InpTpR             = 1.2;    // target = InpTpR * stop
input double          InpBeTriggerR      = 0.0;    // 0 disables breakeven
input double          InpBeOffsetR       = 0.05;
input double          InpPartialR        = 0.0;    // 0 disables partial close
input double          InpPartialFrac     = 0.5;
input double          InpTrailStartR     = 1.2;    // 0 disables trailing
input double          InpTrailDistR      = 1.0;
input int             InpMaxHoldMinutes  = 120;
input int             InpCooldownMinutes = 20;
input int             InpMaxTradesPerDay = 8;
input double          InpDailyLossLimitR = 3.0;    // stop for the day below -this
input int             InpForceExitHour   = 20;     // UTC
input int             InpForceExitMin    = 45;

input group           "=== Execution ==="
input double          InpMaxSpreadPoints = 90;     // skip entries above this (gold: USD 0.90)
input int             InpSlippagePoints  = 10;
input long            InpMagic           = 20260914;
input string          InpComment         = "ScalperXG";

//--- globals
CTrade   g_trade;
int      h_atr = INVALID_HANDLE, h_rsi = INVALID_HANDLE;
int      h_adx = INVALID_HANDLE, h_ema_f = INVALID_HANDLE, h_ema_s = INVALID_HANDLE;
datetime g_last_bar_time = 0;
datetime g_cooldown_until = 0;
int      g_trades_today = 0;
double   g_day_r = 0.0;
int      g_current_day = -1;
bool     g_day_blocked = false;
double   g_entry_sl_dist = 0.0;   // 1R for the open position, in price
bool     g_partial_done = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   h_atr   = iATR(_Symbol, InpSignalTF, InpAtrPeriod);
   h_rsi   = iRSI(_Symbol, InpSignalTF, InpRsiPeriod, PRICE_CLOSE);
   h_adx   = iADX(_Symbol, InpSignalTF, InpAdxPeriod);
   h_ema_f = iMA(_Symbol, InpSignalTF, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   h_ema_s = iMA(_Symbol, InpSignalTF, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   if(h_atr == INVALID_HANDLE || h_rsi == INVALID_HANDLE || h_adx == INVALID_HANDLE
      || h_ema_f == INVALID_HANDLE || h_ema_s == INVALID_HANDLE)
     {
      Print("indicator handle creation failed: ", GetLastError());
      return(INIT_FAILED);
     }
   PrintFormat("ScalperXG on %s  mode=%d  risk=%.2f%%  stop floor=%.0f points",
               _Symbol, (int)InpMode, InpRiskPct * 100.0, InpMinSlPoints);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(h_atr);   IndicatorRelease(h_rsi);
   IndicatorRelease(h_adx);   IndicatorRelease(h_ema_f);
   IndicatorRelease(h_ema_s);
  }

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
double ValuePerPoint()
  {
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0.0)
      return(0.0);
   return(tv * (_Point / ts));
  }

double NormaliseLots(double lots)
  {
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0.0)
      st = 0.01;
   lots = MathFloor(lots / st + 1e-9) * st;
   if(lots < mn)
      lots = mn;
   if(lots > mx)
      lots = mx;
   return(NormalizeDouble(lots, 2));
  }

int UtcHour(datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return(s.hour);
  }

//--- The terminal's server clock is usually UTC+2/+3. Every session filter here
//--- is stated in UTC, so convert once rather than in each comparison.
datetime ServerToUtc(datetime server_time)
  {
   return(server_time - (TimeCurrent() - TimeGMT()));
  }

bool InSession(datetime utc)
  {
   int h = UtcHour(utc);
   if(h == 21)               // daily rollover: spreads blow out, never trade it
      return(false);
   if(InpSessionStartUTC <= InpSessionEndUTC)
      return(h >= InpSessionStartUTC && h < InpSessionEndUTC);
   return(h >= InpSessionStartUTC || h < InpSessionEndUTC);   // wraps midnight
  }

bool PastForceExit(datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return(s.hour > InpForceExitHour
          || (s.hour == InpForceExitHour && s.min >= InpForceExitMin));
  }

//--- Kaufman Efficiency Ratio over `period` closes (index 0 = most recent).
double EfficiencyRatio(const double &close[], int period)
  {
   if(ArraySize(close) < period + 1)
      return(0.0);
   double path = 0.0;
   for(int i = 0; i < period; i++)
      path += MathAbs(close[i] - close[i + 1]);
   if(path <= 0.0)
      return(0.0);
   return(MathAbs(close[0] - close[period]) / path);
  }

//--- fraction of the lookback window that the latest ATR exceeds
double AtrRank(const double &atr[], int lookback)
  {
   int n = MathMin(lookback, ArraySize(atr));
   if(n < 5)
      return(0.5);
   int below = 0;
   for(int i = 1; i < n; i++)
      if(atr[i] < atr[0])
         below++;
   return((double)below / (double)(n - 1));
  }

double ArrayMean(const double &a[], int count)
  {
   int n = MathMin(count, ArraySize(a));
   if(n <= 0)
      return(0.0);
   double s = 0.0;
   for(int i = 0; i < n; i++)
      s += a[i];
   return(s / n);
  }

//--- VWAP of the current UTC day, built from signal-timeframe bars
bool SessionVwap(double &vwap, double &sigma)
  {
   vwap = 0.0;
   sigma = 0.0;
   datetime now_utc = ServerToUtc(TimeCurrent());
   MqlDateTime s;
   TimeToStruct(now_utc, s);
   s.hour = 0; s.min = 0; s.sec = 0;
   datetime day_start_utc = StructToTime(s);
   datetime day_start_srv = day_start_utc + (TimeCurrent() - TimeGMT());

   MqlRates r[];
   ArraySetAsSeries(r, true);
   int got = CopyRates(_Symbol, InpSignalTF, day_start_srv, TimeCurrent(), r);
   if(got <= 2)
      return(false);

   double pv = 0.0, vv = 0.0, pv2 = 0.0;
   for(int i = 0; i < got; i++)
     {
      double tp = (r[i].high + r[i].low + r[i].close) / 3.0;
      double v  = (double)r[i].tick_volume;
      if(v <= 0.0)
         v = 1.0;
      pv  += tp * v;
      vv  += v;
      pv2 += tp * tp * v;
     }
   if(vv <= 0.0)
      return(false);
   vwap = pv / vv;
   double var = pv2 / vv - vwap * vwap;
   sigma = (var > 0.0) ? MathSqrt(var) : 0.0;
   return(sigma > 0.0);
  }

//+------------------------------------------------------------------+
//| signal                                                           |
//| Returns +1 long, -1 short, 0 nothing. Uses only CLOSED bars:      |
//| index 0 of every series below is the last completed bar.          |
//+------------------------------------------------------------------+
int Signal(double &atr_out)
  {
   int need = MathMax(InpAtrRankLookback + 5,
              MathMax(InpErPeriod + 5,
              MathMax(InpDonPeriod + 5, MathMax(InpMomPeriod + 5, InpEmaSlow + 5))));

   double close[], high[], low[], open[], atr[], rsi[], adx[], emaf[], emas[];
   ArraySetAsSeries(close, true); ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);   ArraySetAsSeries(open, true);
   ArraySetAsSeries(atr, true);   ArraySetAsSeries(rsi, true);
   ArraySetAsSeries(adx, true);   ArraySetAsSeries(emaf, true);
   ArraySetAsSeries(emas, true);

   // shift 1 => skip the bar still forming
   if(CopyClose(_Symbol, InpSignalTF, 1, need, close) < need) return(0);
   if(CopyHigh(_Symbol, InpSignalTF, 1, need, high)   < need) return(0);
   if(CopyLow(_Symbol, InpSignalTF, 1, need, low)     < need) return(0);
   if(CopyOpen(_Symbol, InpSignalTF, 1, need, open)   < need) return(0);
   if(CopyBuffer(h_atr, 0, 1, need, atr)              < need) return(0);
   if(CopyBuffer(h_rsi, 0, 1, need, rsi)              < need) return(0);
   if(CopyBuffer(h_adx, 0, 1, need, adx)              < need) return(0);
   if(CopyBuffer(h_ema_f, 0, 1, need, emaf)           < need) return(0);
   if(CopyBuffer(h_ema_s, 0, 1, need, emas)           < need) return(0);

   atr_out = atr[0];
   if(atr_out <= 0.0)
      return(0);

   // --- shared regime gates --------------------------------------
   double rank = AtrRank(atr, InpAtrRankLookback);
   if(rank < InpAtrRankMin || rank > InpAtrRankMax)
      return(0);

   if(InpErMin > 0.0 || InpErMax < 1.0)
     {
      double er = EfficiencyRatio(close, InpErPeriod);
      if(er < InpErMin || er > InpErMax)
         return(0);
     }

   // --- per-mode entry -------------------------------------------
   if(InpMode == MODE_BREAKOUT)
     {
      double prior_hi = high[1], prior_lo = low[1];
      for(int i = 1; i <= InpDonPeriod; i++)
        {
         if(high[i] > prior_hi) prior_hi = high[i];
         if(low[i]  < prior_lo) prior_lo = low[i];
        }
      double atr_avg = ArrayMean(atr, InpAtrAvgPeriod);
      bool expanding = (atr_avg > 0.0 && atr[0] / atr_avg >= InpExpansionMult);
      bool trending  = (adx[0] >= InpAdxMin);
      if(!expanding || !trending)
         return(0);
      if(close[0] > prior_hi && emaf[0] > emas[0]) return(+1);
      if(close[0] < prior_lo && emaf[0] < emas[0]) return(-1);
      return(0);
     }

   if(InpMode == MODE_MOMENTUM)
     {
      double net = close[0] - close[InpMomPeriod];
      if(MathAbs(net) < InpMomMinAtr * atr[0])
         return(0);
      bool up_ok = (!InpMomConfirm || close[0] > high[1]);
      bool dn_ok = (!InpMomConfirm || close[0] < low[1]);
      if(net > 0 && up_ok) return(+1);
      if(net < 0 && dn_ok) return(-1);
      return(0);
     }

   if(InpMode == MODE_PULLBACK)
     {
      if(adx[0] < InpAdxMin)
         return(0);
      // slope of the slow EMA over InpPbSlopePeriod bars
      double slope = emas[0] - emas[InpPbSlopePeriod];
      double swing_lo = low[0], swing_hi = high[0];
      for(int i = 0; i < InpPbLookback; i++)
        {
         if(low[i]  < swing_lo) swing_lo = low[i];
         if(high[i] > swing_hi) swing_hi = high[i];
        }
      bool up = (emaf[0] > emas[0] && slope > 0.0);
      bool dn = (emaf[0] < emas[0] && slope < 0.0);
      if(up && (emaf[0] - swing_lo) >= InpPbDepthAtr * atr[0]
         && rsi[1] <= InpPbRsiLo && close[0] > high[1])
         return(+1);
      if(dn && (swing_hi - emaf[0]) >= InpPbDepthAtr * atr[0]
         && rsi[1] >= InpPbRsiHi && close[0] < low[1])
         return(-1);
      return(0);
     }

   if(InpMode == MODE_FADE)
     {
      double vwap, sigma;
      if(!SessionVwap(vwap, sigma))
         return(0);
      if(adx[0] > InpAdxMax)
         return(0);
      double z0 = (close[0] - vwap) / sigma;
      double z1 = (close[1] - vwap) / sigma;
      bool stretched_dn_now  = (z0 <= -InpBandK && rsi[0] <= InpRsiLo);
      bool stretched_up_now  = (z0 >=  InpBandK && rsi[0] >= InpRsiHi);
      bool stretched_dn_prev = (z1 <= -InpBandK && rsi[1] <= InpRsiLo);
      bool stretched_up_prev = (z1 >=  InpBandK && rsi[1] >= InpRsiHi);
      double rng = MathMax(high[0] - low[0], _Point);

      if(InpConfirmMode == 0)
        {
         if(stretched_dn_now) return(+1);
         if(stretched_up_now) return(-1);
        }
      else if(InpConfirmMode == 1)
        {
         if(stretched_dn_now && close[0] >= low[0] + 0.5 * rng)  return(+1);
         if(stretched_up_now && close[0] <= high[0] - 0.5 * rng) return(-1);
        }
      else if(InpConfirmMode == 2)
        {
         if(stretched_dn_prev && close[0] > close[1]) return(+1);
         if(stretched_up_prev && close[0] < close[1]) return(-1);
        }
      else
        {
         if(stretched_dn_prev && close[0] > high[1]) return(+1);
         if(stretched_up_prev && close[0] < low[1])  return(-1);
        }
      return(0);
     }

   return(0);
  }

//+------------------------------------------------------------------+
//| position management                                              |
//+------------------------------------------------------------------+
void ManageOpenPosition()
  {
   if(!PositionSelect(_Symbol))
      return;
   if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
      return;

   long   type   = PositionGetInteger(POSITION_TYPE);
   double open   = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl     = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);
   double vol    = PositionGetDouble(POSITION_VOLUME);
   ulong  ticket = PositionGetInteger(POSITION_TICKET);
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);

   int dir = (type == POSITION_TYPE_BUY) ? +1 : -1;
   double price = (dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                            : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(g_entry_sl_dist <= 0.0)
      g_entry_sl_dist = MathAbs(open - sl);
   if(g_entry_sl_dist <= 0.0)
      return;

   double run_r = dir * (price - open) / g_entry_sl_dist;

   // --- time stop ------------------------------------------------
   if(InpMaxHoldMinutes > 0
      && (TimeCurrent() - opened) >= InpMaxHoldMinutes * 60)
     {
      g_trade.PositionClose(ticket);
      return;
     }
   // --- session close --------------------------------------------
   if(PastForceExit(ServerToUtc(TimeCurrent())))
     {
      g_trade.PositionClose(ticket);
      return;
     }

   // --- partial take-profit --------------------------------------
   if(InpPartialR > 0.0 && !g_partial_done && run_r >= InpPartialR)
     {
      double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      double part = MathFloor(vol * InpPartialFrac / step + 1e-9) * step;
      double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      if(part >= mn && part < vol)
        {
         if(g_trade.PositionClosePartial(ticket, part))
           {
            g_partial_done = true;
            double be = open + dir * InpBeOffsetR * g_entry_sl_dist;
            if((dir > 0 && be > sl) || (dir < 0 && be < sl))
               g_trade.PositionModify(ticket, NormalizeDouble(be, _Digits), tp);
           }
        }
      return;
     }

   // --- breakeven -------------------------------------------------
   double new_sl = sl;
   if(InpBeTriggerR > 0.0 && run_r >= InpBeTriggerR)
     {
      double be = open + dir * InpBeOffsetR * g_entry_sl_dist;
      if((dir > 0 && be > new_sl) || (dir < 0 && be < new_sl))
         new_sl = be;
     }
   // --- trailing stop ---------------------------------------------
   if(InpTrailStartR > 0.0 && run_r >= InpTrailStartR)
     {
      double trail = price - dir * InpTrailDistR * g_entry_sl_dist;
      if((dir > 0 && trail > new_sl) || (dir < 0 && trail < new_sl))
         new_sl = trail;
     }
   if(MathAbs(new_sl - sl) > _Point * 0.5)
      g_trade.PositionModify(ticket, NormalizeDouble(new_sl, _Digits), tp);
  }

//+------------------------------------------------------------------+
void TryEntry()
  {
   datetime utc = ServerToUtc(TimeCurrent());
   if(!InSession(utc) || PastForceExit(utc))
      return;
   if(g_day_blocked || g_trades_today >= InpMaxTradesPerDay)
      return;
   if(TimeCurrent() < g_cooldown_until)
      return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
      return;

   double atr = 0.0;
   int dir = Signal(atr);
   if(dir == 0)
      return;

   double sl_dist = MathMax(InpSlAtr * atr, InpMinSlPoints * _Point);
   double vpp = ValuePerPoint();
   if(vpp <= 0.0 || sl_dist <= 0.0)
      return;

   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct;
   double lots = NormaliseLots(risk_money / ((sl_dist / _Point) * vpp));

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = (dir > 0) ? ask : bid;
   double sl = (dir > 0) ? entry - sl_dist : entry + sl_dist;
   double tp = (InpTpR > 0.0)
               ? ((dir > 0) ? entry + InpTpR * sl_dist : entry - InpTpR * sl_dist)
               : 0.0;

   // respect the broker's minimum stop distance
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   if(stops_level > 0 && sl_dist < stops_level * _Point)
      return;

   sl = NormalizeDouble(sl, _Digits);
   tp = NormalizeDouble(tp, _Digits);

   bool ok = (dir > 0)
             ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, InpComment)
             : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, InpComment);
   if(ok)
     {
      g_trades_today++;
      g_entry_sl_dist = sl_dist;
      g_partial_done = false;
     }
   else
      PrintFormat("entry rejected: %d %s", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
void ResetDailyCounters()
  {
   // the FX day rolls at 21:00 UTC, matching the backtester
   datetime utc = ServerToUtc(TimeCurrent());
   int day = (int)((utc + 3 * 3600) / 86400);
   if(day != g_current_day)
     {
      g_current_day = day;
      g_trades_today = 0;
      g_day_r = 0.0;
      g_day_blocked = false;
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ResetDailyCounters();
   ManageOpenPosition();

   // act once per closed signal bar, never intrabar
   datetime bt = (datetime)SeriesInfoInteger(_Symbol, InpSignalTF, SERIES_LASTBAR_DATE);
   if(bt == g_last_bar_time)
      return;
   g_last_bar_time = bt;

   if(PositionSelect(_Symbol) && PositionGetInteger(POSITION_MAGIC) == InpMagic)
      return;                      // one position at a time

   TryEntry();
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
      return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct;
   if(risk_money > 0.0)
      g_day_r += profit / risk_money;

   if(InpDailyLossLimitR > 0.0 && g_day_r <= -InpDailyLossLimitR)
     {
      g_day_blocked = true;
      PrintFormat("daily loss limit hit (%.2fR) - no more entries today", g_day_r);
     }
   g_cooldown_until = TimeCurrent() + InpCooldownMinutes * 60;
   g_entry_sl_dist = 0.0;
   g_partial_done = false;
  }
//+------------------------------------------------------------------+
