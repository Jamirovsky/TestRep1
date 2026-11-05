//+------------------------------------------------------------------+
//|                                        BTCUSD_Scalper_Lab.mq5    |
//|  EA de scalping BTCUSD para MetaTrader 5 (ICTrading).            |
//|  Implementa as 14 famílias de setups testadas no relatório.      |
//|  Todos os parâmetros (SL, TP, filtros, gestão) são editáveis     |
//|  nos "Inputs" do EA.                                             |
//|                                                                  |
//|  AVISO: resultados passados/backtests não garantem resultados    |
//|  futuros. Testar SEMPRE primeiro em conta demo.                  |
//+------------------------------------------------------------------+
#property copyright "Estudo BTCUSD scalping"
#property version   "1.00"

#include <Trade/Trade.mqh>

enum ENUM_SETUP
  {
   SETUP_BB_RSI_MR = 0,     // Bollinger + RSI (reversão à média)
   SETUP_RSI_EXTREME,       // RSI extremo
   SETUP_VWAP_REV,          // Desvio ao VWAP diário (reversão)
   SETUP_ZSCORE_MR,         // Z-score (reversão à média)
   SETUP_CONSEC_FADE,       // N velas seguidas na mesma direção (fade)
   SETUP_STOCH_X,           // Cruzamento do Estocástico em zona extrema
   SETUP_EMA_PULLBACK,      // Pullback à EMA rápida a favor da tendência
   SETUP_DONCHIAN_BO,       // Rompimento Donchian
   SETUP_DONCHIAN_FADE,     // Falso rompimento Donchian (fade)
   SETUP_MACD_X,            // Cruzamento MACD
   SETUP_KELTNER_REV,       // Reentrada no canal de Keltner
   SETUP_ORB_SESSION,       // Opening Range Breakout
   SETUP_PINBAR_BB,         // Pin bar fora das Bandas de Bollinger
   SETUP_INSIDE_BO,         // Inside bar breakout
   SETUP_UNGER_PDBO         // Andrea Unger: rompimento máx/mín do dia anterior + ADX
  };

enum ENUM_SLTP_MODE { SLTP_USD = 0,   // Distância fixa em USD
                      SLTP_ATR = 1 }; // Múltiplos do ATR(14)

enum ENUM_TREND { TREND_NONE = 0,     // Sem filtro
                  TREND_WITH = 1,     // Só a favor da EMA longa
                  TREND_AGAINST = 2 };// Só contra a EMA longa

enum ENUM_SESSION { SES_ALL = 0,      // 24h
                    SES_ASIA,         // 00-07 UTC
                    SES_EU,           // 07-13 UTC
                    SES_US,           // 13-21 UTC
                    SES_EU_US,        // 07-21 UTC
                    SES_NO_ASIA };    // 07-24 UTC

enum ENUM_GUARD { GUARD_OFF = 0,      // Desligado
                  GUARD_PAUSE = 1,    // Pausa X horas após N perdas seguidas
                  GUARD_SHADOW = 2 }; // Modo sombra: após N perdas, só trades virtuais até um virtual ganhar

//--- Setup
input group "=== Setup ==="
input ENUM_SETUP      InpSetup        = SETUP_RSI_EXTREME; // Estratégia A2 (recomendada)
input ENUM_TIMEFRAMES InpTF           = PERIOD_M15;   // Timeframe do sinal
input int             InpBBLen        = 20;           // Bollinger / Pinbar: período
input double          InpBBK          = 2.0;          // Bollinger: desvios
input int             InpRSILen       = 4;            // RSI: período
input double          InpRSILo        = 15;           // RSI: nível de sobrevenda (sobrecompra = 100-x)
input double          InpVWAPZ        = 2.0;          // VWAP: desvio em ATRs
input int             InpZLen         = 50;           // Z-score: período
input double          InpZTh          = 2.5;          // Z-score: limiar
input int             InpNBars        = 5;            // Consec fade: nº de velas
input int             InpStLen        = 14;           // Estocástico: período
input double          InpStLo         = 20;           // Estocástico: zona baixa (alta = 100-x)
input int             InpEMAFast      = 21;           // EMA pullback: rápida
input int             InpEMASlow      = 100;          // EMA pullback: lenta
input int             InpDCLen        = 20;           // Donchian: período
input int             InpMACDFast     = 12;           // MACD rápida
input int             InpMACDSlow     = 26;           // MACD lenta
input int             InpKCLen        = 20;           // Keltner: período EMA
input double          InpKCK          = 2.0;          // Keltner: múltiplo ATR
input int             InpORBHourUTC   = 13;           // ORB: hora de abertura (UTC)
input int             InpORBMinutes   = 30;           // ORB: duração do range (min)
input double          InpWick         = 0.6;          // Pinbar: sombra mínima (fração da vela)
input double          InpADXMin       = 30;           // Unger PDBO: ADX(14) mínimo

input group "=== Filtros ==="
input ENUM_TREND      InpTrend        = TREND_WITH;    // Filtro de tendência
input int             InpTrendLen     = 100;          // EMA da tendência
input ENUM_SESSION    InpSession      = SES_NO_ASIA;     // Sessão (horas UTC)
input bool            InpTradeWeekend = false;        // Operar ao fim de semana
input double          InpATRMin       = 0.5;          // ATR/ATR médio(100) mínimo (0 = off)
input double          InpMaxSpreadUSD = 60.0;         // Não entrar se spread > X USD
input int             InpGMTOffset    = -99;          // Offset do servidor vs UTC em horas (-99 = automático)

input group "=== Stop Loss / Take Profit (EDITÁVEIS) ==="
input ENUM_SLTP_MODE  InpSLTPMode     = SLTP_ATR;     // Modo SL/TP
input double          InpSL_USD       = 1100;         // SL em USD de preço (modo USD)
input double          InpTP_USD       = 65;           // TP em USD de preço (modo USD)
input double          InpSL_ATR       = 6.0;          // SL em ATRs (modo ATR)
input double          InpTP_ATR       = 0.35;         // TP em ATRs (modo ATR)
input int             InpMaxHoldMin   = 180;          // Fecho por tempo (minutos)
input double          InpBEFrac       = 0.8;          // Breakeven quando lucro >= X*TP (0 = off)

input group "=== Gestão de risco ==="
input double          InpLots         = 0.01;         // Lotes (0.01 = 0.01 BTC)
input ENUM_GUARD      InpGuard        = GUARD_SHADOW;   // Proteção de perdas consecutivas
input int             InpGuardLosses  = 2;            // N perdas seguidas
input int             InpGuardPauseH  = 12;           // Pausa (horas) no modo pausa
input double          InpMaxDDPct     = 20.0;         // Parar EA se drawdown da conta > X% (0 = off)
input long            InpMagic        = 26110201;

CTrade   trade;
datetime g_lastBar = 0;
int      g_consec = 0;
bool     g_shadow = false;
datetime g_pauseUntil = 0;
ulong    g_lastTicket = 0;
double   g_peakEquity = 0;
bool     g_stopped = false;
// posição virtual (modo sombra)
bool     v_open = false;
int      v_dir = 0;
double   v_entry = 0, v_sl = 0, v_tp = 0;
datetime v_time = 0;
// ORB: controlo diário
int      g_orbDay = -1;
bool     g_orbUpDone = false, g_orbDnDone = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(2000);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
// Servidores IC (ICTrading/IC Markets): GMT+2 no inverno, GMT+3 no horário de verão dos EUA
bool UsDst(datetime t)
  {
   MqlDateTime d; TimeToStruct(t, d);
   if(d.mon < 3 || d.mon > 11) return false;
   if(d.mon > 3 && d.mon < 11) return true;
   // 2º domingo de março / 1º domingo de novembro
   MqlDateTime f = d; f.day = 1; f.hour = 0; f.min = 0; f.sec = 0;
   datetime first = StructToTime(f); MqlDateTime fd; TimeToStruct(first, fd);
   int firstSun = 1 + (7 - fd.day_of_week) % 7;
   if(d.mon == 3) return d.day >= firstSun + 7;
   return d.day < firstSun;
  }

int GmtOffsetSec()
  {
   if(InpGMTOffset != -99) return InpGMTOffset * 3600;
   if(MQLInfoInteger(MQL_TESTER)) return (UsDst(TimeCurrent()) ? 3 : 2) * 3600;
   long d = (long)TimeTradeServer() - (long)TimeGMT();
   return (int)(MathRound(d / 3600.0) * 3600);
  }

datetime ToUTC(datetime server_t) { return server_t - GmtOffsetSec(); }

bool HourAllowed(int h)
  {
   switch(InpSession)
     {
      case SES_ASIA:    return h < 7;
      case SES_EU:      return h >= 7 && h < 13;
      case SES_US:      return h >= 13 && h < 21;
      case SES_EU_US:   return h >= 7 && h < 21;
      case SES_NO_ASIA: return h >= 7;
     }
   return true;
  }

//--- indicadores (séries em ordem cronológica: 0 = mais antiga) -----
void EMAArr(const double &src[], int n, int len, double &out[])
  {
   ArrayResize(out, n);
   double a = 2.0 / (len + 1.0);
   out[0] = src[0];
   for(int i = 1; i < n; i++) out[i] = a * src[i] + (1 - a) * out[i - 1];
  }

double SMAAt(const double &src[], int t, int len)
  {
   double s = 0; for(int i = t - len + 1; i <= t; i++) s += src[i];
   return s / len;
  }

double StdAt(const double &src[], int t, int len) // desvio padrão amostral (ddof=1)
  {
   double m = SMAAt(src, t, len), s = 0;
   for(int i = t - len + 1; i <= t; i++) s += (src[i] - m) * (src[i] - m);
   return MathSqrt(s / (len - 1));
  }

void RSIArr(const double &c[], int n, int len, double &out[])
  {
   ArrayResize(out, n);
   double a = 1.0 / len, up = 0, dn = 0;
   out[0] = 50;
   for(int i = 1; i < n; i++)
     {
      double d = c[i] - c[i - 1];
      double u = d > 0 ? d : 0, w = d < 0 ? -d : 0;
      if(i == 1) { up = u; dn = w; }
      else { up = a * u + (1 - a) * up; dn = a * w + (1 - a) * dn; }
      out[i] = (dn == 0) ? 50 : 100 - 100 / (1 + up / dn);
     }
  }

long UtcDay(datetime server_t) { return (long)ToUTC(server_t) / 86400; }

// ADX de Wilder (mesma formulação do backtest em Python)
void ADXArr(const MqlRates &r[], int n, int len, double &out[])
  {
   ArrayResize(out, n);
   double a = 1.0 / len, atr = r[0].high - r[0].low, pdm = 0, ndm = 0, adx = 0;
   out[0] = 0;
   for(int i = 1; i < n; i++)
     {
      double up = r[i].high - r[i - 1].high, dn = r[i - 1].low - r[i].low;
      double p = (up > dn && up > 0) ? up : 0, m = (dn > up && dn > 0) ? dn : 0;
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      atr = a * tr + (1 - a) * atr; pdm = a * p + (1 - a) * pdm; ndm = a * m + (1 - a) * ndm;
      double pdi = atr > 0 ? 100 * pdm / atr : 0, ndi = atr > 0 ? 100 * ndm / atr : 0;
      double dx = (pdi + ndi) > 0 ? 100 * MathAbs(pdi - ndi) / (pdi + ndi) : 0;
      adx = a * dx + (1 - a) * adx;
      out[i] = adx;
     }
  }

void ATRArr(const MqlRates &r[], int n, int len, double &out[])
  {
   ArrayResize(out, n);
   double a = 1.0 / len;
   out[0] = r[0].high - r[0].low;
   for(int i = 1; i < n; i++)
     {
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      out[i] = a * tr + (1 - a) * out[i - 1];
     }
  }

//+------------------------------------------------------------------+
//| Calcula sinal na última vela fechada: +1 compra, -1 venda, 0     |
//+------------------------------------------------------------------+
int ComputeSignal(double &atr_now)
  {
   int need = 3000;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, InpTF, 1, need, r);
   if(n < 500) return 0;
   int t = n - 1;
   double c[], h[], l[], o[];
   ArrayResize(c, n); ArrayResize(h, n); ArrayResize(l, n); ArrayResize(o, n);
   for(int i = 0; i < n; i++) { c[i] = r[i].close; h[i] = r[i].high; l[i] = r[i].low; o[i] = r[i].open; }
   double atr[]; ATRArr(r, n, 14, atr);
   atr_now = atr[t];

   datetime barUTC = ToUTC(r[t].time);
   MqlDateTime dt; TimeToStruct(barUTC, dt);
   if(!HourAllowed(dt.hour)) return 0;
   if(!InpTradeWeekend && (dt.day_of_week == 0 || dt.day_of_week == 6)) return 0;
   if(InpATRMin > 0)
     {
      double am = SMAAt(atr, t, 100);
      if(am <= 0 || atr[t] / am < InpATRMin) return 0;
     }

   bool lg = false, sh = false;
   switch(InpSetup)
     {
      case SETUP_BB_RSI_MR:
        {
         double m = SMAAt(c, t, InpBBLen), sd = StdAt(c, t, InpBBLen);
         double rs[]; RSIArr(c, n, InpRSILen, rs);
         lg = c[t] < m - InpBBK * sd && rs[t] < InpRSILo;
         sh = c[t] > m + InpBBK * sd && rs[t] > 100 - InpRSILo;
         break;
        }
      case SETUP_RSI_EXTREME:
        {
         double rs[]; RSIArr(c, n, InpRSILen, rs);
         lg = rs[t] < InpRSILo; sh = rs[t] > 100 - InpRSILo;
         break;
        }
      case SETUP_VWAP_REV:
        {
         // VWAP da sessão diária UTC (volume de ticks no MT5)
         MqlDateTime d0; TimeToStruct(barUTC, d0);
         double pv = 0, vv = 0;
         for(int i = t; i >= 0; i--)
           {
            MqlDateTime di; TimeToStruct(ToUTC(r[i].time), di);
            if(di.day != d0.day || di.mon != d0.mon) break;
            double tp = (r[i].high + r[i].low + r[i].close) / 3.0;
            pv += tp * (double)r[i].tick_volume; vv += (double)r[i].tick_volume;
           }
         double vw = vv > 0 ? pv / vv : c[t];
         double dev = (c[t] - vw) / atr[t];
         lg = dev < -InpVWAPZ; sh = dev > InpVWAPZ;
         break;
        }
      case SETUP_ZSCORE_MR:
        {
         double m = SMAAt(c, t, InpZLen), sd = StdAt(c, t, InpZLen);
         if(sd > 0) { double z = (c[t] - m) / sd; lg = z < -InpZTh; sh = z > InpZTh; }
         break;
        }
      case SETUP_CONSEC_FADE:
        {
         bool alld = true, allu = true;
         for(int k = 0; k < InpNBars; k++)
           {
            double d = c[t - k] - c[t - k - 1];
            if(!(d < 0)) alld = false;
            if(!(d > 0)) allu = false;
           }
         lg = alld; sh = allu;
         break;
        }
      case SETUP_STOCH_X:
        {
         double K[]; ArrayResize(K, n);
         for(int i = 0; i < n; i++)
           {
            if(i < InpStLen - 1) { K[i] = 50; continue; }
            double hh = h[i], ll = l[i];
            for(int j = i - InpStLen + 1; j <= i; j++) { hh = MathMax(hh, h[j]); ll = MathMin(ll, l[j]); }
            K[i] = (hh - ll) > 0 ? 100 * (c[i] - ll) / (hh - ll) : 50;
           }
         double d1 = SMAAt(K, t, 3), d0 = SMAAt(K, t - 1, 3);
         lg = K[t - 1] < d0 && K[t] > d1 && K[t - 1] < InpStLo;
         sh = K[t - 1] > d0 && K[t] < d1 && K[t - 1] > 100 - InpStLo;
         break;
        }
      case SETUP_EMA_PULLBACK:
        {
         double ef[], es[]; EMAArr(c, n, InpEMAFast, ef); EMAArr(c, n, InpEMASlow, es);
         lg = ef[t] > es[t] && l[t] <= ef[t] && c[t] > ef[t];
         sh = ef[t] < es[t] && h[t] >= ef[t] && c[t] < ef[t];
         break;
        }
      case SETUP_DONCHIAN_BO:
      case SETUP_DONCHIAN_FADE:
        {
         double hh = h[t - 1], ll = l[t - 1];
         for(int j = t - InpDCLen; j <= t - 1; j++) { hh = MathMax(hh, h[j]); ll = MathMin(ll, l[j]); }
         if(InpSetup == SETUP_DONCHIAN_BO) { lg = c[t] > hh; sh = c[t] < ll; }
         else { lg = l[t] < ll && c[t] > ll; sh = h[t] > hh && c[t] < hh; }
         break;
        }
      case SETUP_MACD_X:
        {
         double ef[], es[], m[], s[];
         EMAArr(c, n, InpMACDFast, ef); EMAArr(c, n, InpMACDSlow, es);
         ArrayResize(m, n); for(int i = 0; i < n; i++) m[i] = ef[i] - es[i];
         EMAArr(m, n, 9, s);
         lg = m[t - 1] < s[t - 1] && m[t] > s[t] && m[t] < 0;
         sh = m[t - 1] > s[t - 1] && m[t] < s[t] && m[t] > 0;
         break;
        }
      case SETUP_KELTNER_REV:
        {
         double e[]; EMAArr(c, n, InpKCLen, e);
         double lo = e[t] - InpKCK * atr[t], hi = e[t] + InpKCK * atr[t];
         lg = c[t - 1] < lo && c[t] > lo;
         sh = c[t - 1] > hi && c[t] < hi;
         break;
        }
      case SETUP_ORB_SESSION:
        {
         if(dt.day_of_year != g_orbDay) { g_orbDay = dt.day_of_year; g_orbUpDone = false; g_orbDnDone = false; }
         int mins = (dt.hour - InpORBHourUTC) * 60 + dt.min;
         if(mins >= InpORBMinutes && mins < InpORBMinutes + 180)
           {
            double hi = -1, lo = 1e18;
            for(int i = t; i >= 0; i--)
              {
               MqlDateTime di; TimeToStruct(ToUTC(r[i].time), di);
               if(di.day_of_year != dt.day_of_year) break;
               int mi = (di.hour - InpORBHourUTC) * 60 + di.min;
               if(mi >= 0 && mi < InpORBMinutes) { hi = MathMax(hi, h[i]); lo = MathMin(lo, l[i]); }
              }
            if(hi > 0)
              {
               if(c[t] > hi && !g_orbUpDone) { lg = true; g_orbUpDone = true; }
               if(c[t] < lo && !g_orbDnDone) { sh = true; g_orbDnDone = true; }
              }
           }
         break;
        }
      case SETUP_PINBAR_BB:
        {
         double m = SMAAt(c, t, InpBBLen), sd = StdAt(c, t, InpBBLen);
         double rg = MathMax(h[t] - l[t], 1e-9);
         double lw = (MathMin(o[t], c[t]) - l[t]) / rg, uw = (h[t] - MathMax(o[t], c[t])) / rg;
         lg = l[t] < m - InpBBK * sd && lw >= InpWick;
         sh = h[t] > m + InpBBK * sd && uw >= InpWick;
         break;
        }
      case SETUP_INSIDE_BO:
        {
         bool inside = h[t - 1] <= h[t - 2] && l[t - 1] >= l[t - 2];
         lg = inside && c[t] > h[t - 1]; sh = inside && c[t] < l[t - 1];
         break;
        }
      case SETUP_UNGER_PDBO:
        {
         // máxima/mínima do dia UTC anterior; só o PRIMEIRO cruzamento de cada dia conta
         long dT = UtcDay(r[t].time);
         int i0 = t;
         while(i0 > 0 && UtcDay(r[i0 - 1].time) == dT) i0--;
         int j = i0 - 1;
         if(j < 1) break;
         long dP = UtcDay(r[j].time);
         double pdh = -1, pdl = 1e18;
         while(j >= 0 && UtcDay(r[j].time) == dP) { pdh = MathMax(pdh, h[j]); pdl = MathMin(pdl, l[j]); j--; }
         if(j < 0) break;
         int firstUp = -1, firstDn = -1;
         for(int k = i0; k <= t; k++)
           {
            if(firstUp < 0 && c[k] > pdh && c[k - 1] <= pdh) firstUp = k;
            if(firstDn < 0 && c[k] < pdl && c[k - 1] >= pdl) firstDn = k;
           }
         double ad[]; ADXArr(r, n, 14, ad);
         bool adxOk = ad[t] >= InpADXMin;
         lg = firstUp == t && adxOk;
         sh = firstDn == t && adxOk;
         break;
        }
     }

   if(InpTrend != TREND_NONE)
     {
      double et[]; EMAArr(c, n, InpTrendLen, et);
      bool up = c[t] > et[t], dn = c[t] < et[t];
      if(InpTrend == TREND_WITH) { lg = lg && up; sh = sh && dn; }
      else { lg = lg && dn; sh = sh && up; }
     }
   if(lg) return 1;
   if(sh) return -1;
   return 0;
  }

//+------------------------------------------------------------------+
bool HasPosition(ulong &ticket)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(PositionSelectByTicket(tk) && PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == InpMagic) { ticket = tk; return true; }
     }
   return false;
  }

void RegisterResult(bool win)
  {
   if(win) { g_consec = 0; return; }
   g_consec++;
   if(InpGuard == GUARD_PAUSE && g_consec >= InpGuardLosses)
     { g_pauseUntil = TimeCurrent() + InpGuardPauseH * 3600; g_consec = 0; }
   if(InpGuard == GUARD_SHADOW && g_consec >= InpGuardLosses)
     { g_shadow = true; Print("Modo sombra ativado após ", g_consec, " perdas seguidas"); }
  }

void CheckClosedReal()
  {
   if(g_lastTicket == 0) return;
   ulong tk;
   if(HasPosition(tk)) return;
   if(HistorySelectByPosition(g_lastTicket))
     {
      double p = 0;
      for(int i = 0; i < HistoryDealsTotal(); i++)
        {
         ulong d = HistoryDealGetTicket(i);
         p += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_COMMISSION);
        }
      RegisterResult(p > 0);
     }
   g_lastTicket = 0;
  }

void ManageVirtual()
  {
   if(!v_open) return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double px = v_dir == 1 ? bid : ask;
   bool closed = false, win = false;
   if(v_dir == 1) { if(px <= v_sl) { closed = true; win = false; } else if(px >= v_tp) { closed = true; win = true; } }
   else           { if(px >= v_sl) { closed = true; win = false; } else if(px <= v_tp) { closed = true; win = true; } }
   if(!closed && TimeCurrent() - v_time >= InpMaxHoldMin * 60) { closed = true; win = (px - v_entry) * v_dir > 0; }
   if(closed)
     {
      v_open = false;
      Print("Trade virtual fechado: ", win ? "GANHO" : "PERDA");
      if(win) { g_shadow = false; g_consec = 0; Print("Modo sombra desativado - volta a operar real"); }
     }
  }

void ManageReal()
  {
   ulong tk;
   if(!HasPosition(tk)) return;
   if(!PositionSelectByTicket(tk)) return;
   datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
   long type = PositionGetInteger(POSITION_TYPE);
   double op = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
   if(TimeCurrent() - ot >= InpMaxHoldMin * 60) { trade.PositionClose(tk); return; }
   if(InpBEFrac > 0 && tp > 0)
     {
      double tpd = MathAbs(tp - op);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(type == POSITION_TYPE_BUY && bid - op >= InpBEFrac * tpd && sl < op)
         trade.PositionModify(tk, NormalizeDouble(op + 1.0, _Digits), tp);
      if(type == POSITION_TYPE_SELL && op - ask >= InpBEFrac * tpd && (sl > op || sl == 0))
         trade.PositionModify(tk, NormalizeDouble(op - 1.0, _Digits), tp);
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(g_stopped) return;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peakEquity = MathMax(g_peakEquity, eq);
   if(InpMaxDDPct > 0 && g_peakEquity > 0 && (g_peakEquity - eq) / g_peakEquity * 100 >= InpMaxDDPct)
     {
      ulong tk; if(HasPosition(tk)) trade.PositionClose(tk);
      g_stopped = true;
      Print("EA parado: drawdown máximo atingido");
      return;
     }
   CheckClosedReal();
   ManageReal();
   ManageVirtual();

   datetime bt = iTime(_Symbol, InpTF, 0);
   if(bt == g_lastBar) return;
   g_lastBar = bt;

   ulong tk;
   if(HasPosition(tk) || v_open) return;
   if(InpGuard == GUARD_PAUSE && TimeCurrent() < g_pauseUntil) return;

   double atr_now = 0;
   int sig = ComputeSignal(atr_now);
   if(sig == 0) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(ask - bid > InpMaxSpreadUSD) return;
   double sld, tpd;
   if(InpSLTPMode == SLTP_USD) { sld = InpSL_USD; tpd = InpTP_USD; }
   else { sld = MathMax(InpSL_ATR * atr_now, 30.0); tpd = MathMax(InpTP_ATR * atr_now, 20.0); }

   double ep = sig == 1 ? ask : bid;
   double slp = sig == 1 ? ep - sld : ep + sld;
   double tpp = sig == 1 ? ep + tpd : ep - tpd;

   if(InpGuard == GUARD_SHADOW && g_shadow)
     {
      v_open = true; v_dir = sig; v_entry = ep; v_sl = slp; v_tp = tpp; v_time = TimeCurrent();
      Print("Trade VIRTUAL aberto (modo sombra) dir=", sig);
      return;
     }
   bool ok = sig == 1 ? trade.Buy(InpLots, _Symbol, 0, NormalizeDouble(slp, _Digits), NormalizeDouble(tpp, _Digits), "scalp")
                      : trade.Sell(InpLots, _Symbol, 0, NormalizeDouble(slp, _Digits), NormalizeDouble(tpp, _Digits), "scalp");
   if(ok) { ulong t2; if(HasPosition(t2)) g_lastTicket = t2; }
  }
//+------------------------------------------------------------------+
