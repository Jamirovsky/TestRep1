"""Execução de um setup completo + divisão backtest / validação / forward test."""
import numpy as np
import pandas as pd
from .engine import simulate, metrics
from .strategies import build_signals, load_m1

# ----------------------------------------------------------------- pressupostos da conta
ACCOUNT = dict(
    balance_eur=100.0,
    eurusd=1.16,          # conversão EUR->USD (editável)
    lots=0.01,            # 0.01 lote = 0.01 BTC no BTCUSD da ICTrading (1 lote = 1 BTC)
)
COSTS = dict(
    spread=25.0,          # spread médio BTCUSD em USD (editável; verificar no MT5 da ICTrading)
    slip=5.0,             # slippage extra em ordens stop (USD)
    swap_long_day=50.0,   # custo de swap por noite por 1 BTC (USD) ~ 20%/ano a 90k$
    swap_short_day=20.0,
    rollover_hour=22,     # hora UTC do rollover (00:00 servidor GMT+2)
)

# Backtest (in-sample, usado para otimizar) e forward test (out-of-sample, nunca usado
# na seleção). O backtest é ainda dividido em 4 blocos para medir consistência.
SEGMENTS = {
    'backtest': ('2025-01-07', '2026-05-01'),
    'forward': ('2026-05-01', '2026-11-03'),
}
CHUNKS = [('2025-01-07', '2025-05-01'), ('2025-05-01', '2025-09-01'),
          ('2025-09-01', '2026-01-01'), ('2026-01-01', '2026-05-01')]


def _ts(s):
    return int(pd.Timestamp(s, tz='UTC').timestamp())


def run(p, costs=None, account=None, return_trades=False):
    costs = {**COSTS, **(costs or {})}
    account = {**ACCOUNT, **(account or {})}
    m = load_m1()
    idx, d, sl, tp = build_signals(p)
    if p.get('entry_delay', 0):
        idx = idx + int(p['entry_delay'])  # teste de latência: entrar N minutos mais tarde
    gm = p.get('guard_mode', 0)
    res = simulate(m['o'], m['h'], m['l'], m['c'], m['ts'],
                   idx, d, sl, tp,
                   costs['spread'], costs['slip'], int(p['max_hold']),
                   float(p.get('be_frac', 0.0)),
                   2, int(gm), int(p.get('guard_pause_h', 12)) * 3600,
                   costs['swap_long_day'], costs['swap_short_day'], costs['rollover_hour'])
    ei, xi, dr, ep, xp, pnl, reason, real = res
    lots = account['lots']
    start_usd = account['balance_eur'] * account['eurusd']
    pnl_usd = pnl * lots
    t_entry = m['ts'][ei]
    out = {}
    for name, (a, b) in SEGMENTS.items():
        sel = (t_entry >= _ts(a)) & (t_entry < _ts(b)) & real
        out[name] = metrics(pnl_usd[sel], start_usd)
        days = (_ts(b) - _ts(a)) / 86400
        out[name]['trades_per_day'] = out[name]['trades'] / days
    out['chunks'] = []
    for a, b in CHUNKS:
        sel = (t_entry >= _ts(a)) & (t_entry < _ts(b)) & real
        mt = metrics(pnl_usd[sel], start_usd)
        out['chunks'].append({k: mt[k] for k in ('trades', 'win_rate', 'profit_factor', 'ret_pct', 'max_consec_losses', 'max_dd_pct')})
    sel = real
    out['total'] = metrics(pnl_usd[sel], start_usd)
    out['total']['virtual_trades'] = int((~real).sum())
    if return_trades:
        tr = pd.DataFrame({
            'entrada_utc': pd.to_datetime(m['ts'][ei], unit='s'),
            'saida_utc': pd.to_datetime(m['ts'][xi], unit='s'),
            'direcao': np.where(dr == 1, 'BUY', 'SELL'),
            'preco_entrada': ep, 'preco_saida': xp,
            'sl_usd': sl[np.searchsorted(idx, ei)] if len(ei) else [],
            'tp_usd': tp[np.searchsorted(idx, ei)] if len(ei) else [],
            'pontos': pnl, 'lucro_usd': pnl_usd, 'lucro_eur': pnl_usd / account['eurusd'],
            'saida': pd.Categorical.from_codes(reason, ['TP', 'SL', 'TEMPO', 'BREAKEVEN']),
            'real': real,
        })
        return out, tr
    return out


def score(r, min_trades=100):
    """Pontuação robusta: retorno médio + pior bloco do backtest, menos penalizações
    por cada pressuposto do cliente não cumprido (sobre o backtest completo)."""
    mt = r['backtest']
    ch = [c['ret_pct'] for c in r['chunks']]
    base = 0.5 * np.mean(ch) + 1.0 * min(ch)
    # blocos com perda ou PF<1 penalizados
    pen = sum(5.0 for c in r['chunks'] if c['ret_pct'] <= 0)
    if mt['trades'] < min_trades:
        pen += (min_trades - mt['trades']) * 1.0
    if mt['win_rate'] < 0.57:
        pen += (0.57 - mt['win_rate']) * 500
    pf = min(mt['profit_factor'], 5.0)
    if pf < 1.05:
        pen += (1.05 - pf) * 200
    if mt['max_dd_pct'] > 20:
        pen += (mt['max_dd_pct'] - 20) * 5
    if mt['max_consec_losses'] > 2:
        pen += (mt['max_consec_losses'] - 2) * 15
    return base - pen


def passes(mt, min_trades=100):
    return (mt['trades'] > min_trades and mt['win_rate'] > 0.57 and mt['profit_factor'] > 1.01
            and mt['max_dd_pct'] <= 20 and mt['max_consec_losses'] < 3)
