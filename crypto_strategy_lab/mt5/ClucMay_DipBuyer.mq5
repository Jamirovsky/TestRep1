//+------------------------------------------------------------------+
//|                                             ClucMay_DipBuyer.mq5 |
//|  Compra de quedas abaixo da banda de Bollinger                    |
//|  (origem: freqtrade ClucMay72018 / CombinedBinHAndCluc)           |
//|  Portado do motor de backtest em Python (crypto_strategy_lab).    |
//|                                                                  |
//|  Lógica (só LONG):                                                |
//|   Entrada: fecho < EMA(n)                                         |
//|            E fecho < k × banda inferior de Bollinger(20, 2)       |
//|            E volume < vm × média do volume das 30 velas anteriores|
//|            + filtros opcionais (SMA de tendência com tolerância,  |
//|              SMA diária, volatilidade mínima ATR14/preço)         |
//|   Saída:   fecho > banda média de Bollinger (SMA 20)              |
//|            ou TP / SL / trailing / nº máximo de velas             |
//|  Sinais avaliados no fecho de cada vela; ordens a mercado na      |
//|  abertura da vela seguinte (igual ao backtest).                   |
//|                                                                  |
//|  Valores por defeito = parâmetros da re-otimização WFO de         |
//|  jul/2026 (BTC M15). Re-otimize a cada 3 meses (ver README).      |
//+------------------------------------------------------------------+
#property copyright "crypto_strategy_lab"
#property version   "1.00"
#property description "ClucMay dip buyer (M15). Re-otimizar trimestralmente com critério Custom max."

#include <Trade/Trade.mqh>

enum ENUM_EXITMODE { EXIT_PCT = 0, EXIT_ATR = 1 };
enum ENUM_SIZING   { SIZE_FIXED_LOTS = 0, SIZE_EQUITY_PCT = 1 };

input group "=== Sinal ==="
input ENUM_TIMEFRAMES InpTF        = PERIOD_M15; // Timeframe dos sinais
input int             InpEMA       = 100;        // EMA lenta (fecho tem de estar abaixo)
input int             InpBBPeriod  = 20;         // Período de Bollinger
input double          InpBBDev     = 2.0;        // Desvios padrão de Bollinger
input double          InpBBFactor  = 1.00;       // k: fecho < k × banda inferior
input double          InpVolMult   = 2.0;        // vm: volume < vm × média de volume
input int             InpVolPeriod = 30;         // Velas da média de volume
input bool            InpRealVolume = false;     // Usar volume real (senão volume de ticks)

input group "=== Filtros ==="
input int    InpTrendSMA  = 0;    // SMA de tendência em velas (0 = desligado)
input double InpTrendTol  = 0.90; // Tolerância: fecho > SMA × tol
input int    InpDailySMA  = 0;    // SMA de tendência em dias (0 = desligado)
input double InpMinAtrPct = 0.70; // ATR(14)/preço mínimo em % (0 = desligado)

input group "=== Saídas ==="
input ENUM_EXITMODE InpExitMode  = EXIT_PCT; // Unidades de TP/SL/trailing: % ou múltiplos de ATR(14)
input double        InpTP        = 0.75;     // Take profit (0 = sem TP)
input double        InpSL        = 8.0;      // Stop loss
input double        InpTrailDist = 0.50;     // Distância do trailing (0 = desligado)
input double        InpTrailAct  = 1.00;     // Lucro necessário para ativar o trailing
input int           InpMaxBars   = 96;       // Fecha após N velas (0 = desligado)

input group "=== Gestão ==="
input ENUM_SIZING InpSizing    = SIZE_EQUITY_PCT; // Tamanho da posição
input double      InpLots      = 0.01;            // Lotes fixos (se SIZE_FIXED_LOTS)
input double      InpEquityPct = 100.0;           // Nocional em % do capital (backtest = 100)
input ulong       InpMagic     = 26101502;        // Magic number
input int         InpSlippage  = 50;              // Desvio máximo (pontos)

input group "=== Otimização (OnTester / Custom max) ==="
input int    InpMinTrades     = 40;    // Mínimo de trades (40 = ~100 por 5 anos numa janela de 24m)
input double InpMinWinRate    = 57;    // Win rate mínimo %
input double InpMinPF         = 1.05;  // Profit factor mínimo
input double InpMaxDD         = 20;    // Drawdown máximo % (capital)
input bool   InpRobustSelect  = false; // Pontuação = pior PF das duas metades (a ClucMay usou seleção por PF)
input bool   InpRecencyFilter = true;  // Exige PF >= 1 nos últimos 12 meses

CTrade   trade;
int      hEMA = INVALID_HANDLE, hTrend = INVALID_HANDLE, hDaily = INVALID_HANDLE;
datetime g_lastBar = 0;
double   g_entryAtrFrac = 0.0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   hEMA = iMA(_Symbol, InpTF, InpEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(hEMA == INVALID_HANDLE) { Print("Erro a criar EMA"); return INIT_FAILED; }
   if(InpTrendSMA > 0)
      hTrend = iMA(_Symbol, InpTF, InpTrendSMA, 0, MODE_SMA, PRICE_CLOSE);
   if(InpDailySMA > 0)
   {
      int bpd = (int)MathRound(86400.0 / PeriodSeconds(InpTF));
      hDaily = iMA(_Symbol, InpTF, InpDailySMA * bpd, 0, MODE_SMA, PRICE_CLOSE);
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hEMA   != INVALID_HANDLE) IndicatorRelease(hEMA);
   if(hTrend != INVALID_HANDLE) IndicatorRelease(hTrend);
   if(hDaily != INVALID_HANDLE) IndicatorRelease(hDaily);
}

//+------------------------------------------------------------------+
bool BufferValue(const int handle, double &value)
{
   double b[];
   if(CopyBuffer(handle, 0, 1, 1, b) != 1) return false;
   value = b[0];
   return (value != EMPTY_VALUE);
}

// ATR de Wilder (média exponencial alpha=1/n), como no backtest. r[] em ordem cronológica.
double WilderATR(const MqlRates &r[], const int n)
{
   int cnt = ArraySize(r);
   double atr = r[0].high - r[0].low;
   for(int i = 1; i < cnt; i++)
   {
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      atr += (tr - atr) / n;
   }
   return atr;
}

double Vol(const MqlRates &x)
{
   if(InpRealVolume && x.real_volume > 0) return (double)x.real_volume;
   return (double)x.tick_volume;
}

bool GetPosition(ulong &ticket)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
      { ticket = t; return true; }
   }
   return false;
}

double CalcLots(const double price)
{
   double lots = InpLots;
   if(InpSizing == SIZE_EQUITY_PCT)
   {
      double cs = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
      if(cs <= 0) cs = 1.0;
      lots = AccountInfoDouble(ACCOUNT_EQUITY) * InpEquityPct / 100.0 / (price * cs);
   }
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lots = MathFloor(lots / step) * step;
   lots = MathMax(vmin, MathMin(vmax, lots));
   return NormalizeDouble(lots, 8);
}

double ToFrac(const double v, const double atrFrac)
{
   return (InpExitMode == EXIT_PCT) ? v / 100.0 : v * atrFrac;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime t0 = iTime(_Symbol, InpTF, 0);
   if(t0 == 0 || t0 == g_lastBar) return;   // só na abertura de uma vela nova
   g_lastBar = t0;

   int need = MathMax(400, MathMax(InpBBPeriod, InpVolPeriod) + 5);
   MqlRates r[];
   ArraySetAsSeries(r, false);
   if(CopyRates(_Symbol, InpTF, 1, need, r) != need) return;   // r[need-1] = última vela fechada
   int last = need - 1;
   double close = r[last].close;

   // Bollinger (desvio padrão amostral, como pandas rolling.std)
   double sum = 0.0;
   for(int i = last - InpBBPeriod + 1; i <= last; i++) sum += r[i].close;
   double mid = sum / InpBBPeriod, ss = 0.0;
   for(int i = last - InpBBPeriod + 1; i <= last; i++) ss += (r[i].close - mid) * (r[i].close - mid);
   double lower = mid - InpBBDev * MathSqrt(ss / (InpBBPeriod - 1));

   double atrFrac = WilderATR(r, 14) / close;

   // ---------------- gestão da posição aberta
   ulong ticket;
   if(GetPosition(ticket))
   {
      double ep = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      int held  = iBarShift(_Symbol, InpTF, (datetime)PositionGetInteger(POSITION_TIME), false);

      if(close > mid || (InpMaxBars > 0 && held >= InpMaxBars))
      {
         trade.PositionClose(ticket);
      }
      else if(InpTrailDist > 0 && held >= 1)
      {
         double af   = (g_entryAtrFrac > 0) ? g_entryAtrFrac : atrFrac;
         double dist = ToFrac(InpTrailDist, af), act = ToFrac(InpTrailAct, af);
         double hh   = iHigh(_Symbol, InpTF, iHighest(_Symbol, InpTF, MODE_HIGH, held, 1));
         if(hh >= ep * (1.0 + act))
         {
            int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
            double ns = NormalizeDouble(hh * (1.0 - dist), digits);
            if(ns > sl && ns < SymbolInfoDouble(_Symbol, SYMBOL_BID)) trade.PositionModify(ticket, ns, tp);
         }
      }
   }
   if(GetPosition(ticket)) return;   // uma posição de cada vez

   // ---------------- sinal de entrada (vela fechada)
   double ema;
   if(!BufferValue(hEMA, ema)) return;
   double vsum = 0.0;
   for(int i = last - InpVolPeriod; i < last; i++) vsum += Vol(r[i]);   // média das 30 velas ANTERIORES
   double vmean = vsum / InpVolPeriod;

   bool entry = (close < ema) && (close < InpBBFactor * lower) && (Vol(r[last]) < InpVolMult * vmean);
   if(!entry) return;
   if(InpMinAtrPct > 0 && atrFrac * 100.0 < InpMinAtrPct) return;
   double m;
   if(InpTrendSMA > 0) { if(!BufferValue(hTrend, m)) return; if(close <= m * InpTrendTol) return; }
   if(InpDailySMA > 0) { if(!BufferValue(hDaily, m)) return; if(close <= m) return; }

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double slF = ToFrac(InpSL, atrFrac), tpF = ToFrac(InpTP, atrFrac);
   double sl = NormalizeDouble(price * (1.0 - slF), digits);
   double tp = (InpTP > 0) ? NormalizeDouble(price * (1.0 + tpF), digits) : 0.0;
   g_entryAtrFrac = atrFrac;
   if(!trade.Buy(CalcLots(price), _Symbol, 0.0, sl, tp, "ClucMay"))
      PrintFormat("Falha na ordem: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Critério de otimização "Custom max" = seleção usada no walk-forward |
//+------------------------------------------------------------------+
double PF(const double gp, const double gl) { return (gl > 0) ? gp / gl : 3.0; }

double OnTester()
{
   double trades = TesterStatistics(STAT_TRADES);
   if(trades < InpMinTrades) return -1.0;
   double wr = 100.0 * TesterStatistics(STAT_PROFIT_TRADES) / trades;
   double pf = PF(TesterStatistics(STAT_GROSS_PROFIT), -TesterStatistics(STAT_GROSS_LOSS));
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(wr < InpMinWinRate || pf < InpMinPF || dd >= InpMaxDD) return 0.0;

   if(!HistorySelect(0, TimeCurrent())) return 0.0;
   int nd = HistoryDealsTotal();
   long   pid[]; double net[]; datetime tout[];
   int np = 0;
   for(int i = 0; i < nd; i++)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0 || (ulong)HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic) continue;
      long p = HistoryDealGetInteger(d, DEAL_POSITION_ID);
      double v = HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_COMMISSION);
      int k = -1;
      for(int j = np - 1; j >= 0; j--) if(pid[j] == p) { k = j; break; }
      if(k < 0) { np++; ArrayResize(pid, np); ArrayResize(net, np); ArrayResize(tout, np); k = np - 1; pid[k] = p; net[k] = 0; tout[k] = 0; }
      net[k] += v;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_OUT) tout[k] = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
   }
   if(np == 0) return 0.0;
   datetime t1 = tout[0], t2 = tout[0];
   for(int k = 0; k < np; k++) { if(tout[k] > 0 && tout[k] < t1) t1 = tout[k]; if(tout[k] > t2) t2 = tout[k]; }

   if(InpRecencyFilter)
   {
      double g = 0, l = 0; int n = 0;
      for(int k = 0; k < np; k++) if(tout[k] >= t2 - 365 * 86400) { n++; if(net[k] > 0) g += net[k]; else l -= net[k]; }
      if(n >= 5 && PF(g, l) < 1.0) return 0.0;
   }
   double score = (MathMin(pf, 3.0) - 1.0) * MathLog(trades);
   if(InpRobustSelect)
   {
      datetime midT = t1 + (t2 - t1) / 2;
      double g1 = 0, l1 = 0, g2 = 0, l2 = 0; int n1 = 0, n2 = 0;
      for(int k = 0; k < np; k++)
      {
         if(tout[k] < midT) { n1++; if(net[k] > 0) g1 += net[k]; else l1 -= net[k]; }
         else               { n2++; if(net[k] > 0) g2 += net[k]; else l2 -= net[k]; }
      }
      if(n1 < 5 || n2 < 5) return 0.0;
      score = (MathMin(MathMin(PF(g1, l1), PF(g2, l2)), 3.0) - 1.0) * MathLog(trades);
   }
   return score;
}
//+------------------------------------------------------------------+
