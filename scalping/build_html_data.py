"""Gera report/html_data.json com os dados para a página HTML do relatório."""
import json, os
import pandas as pd
import numpy as np
OUT = os.path.join(os.path.dirname(__file__), '..', 'report')
s = pd.read_csv(os.path.join(OUT, 'resumo_familias.csv'))
det = json.load(open(os.path.join(OUT, 'detalhes.json')))
NAMES = {'RSI_EXTREME': 'RSI extremo (contra tendência)', 'MACD_X': 'MACD cruzamento', 'ZSCORE_MR': 'Z-score reversão',
         'PINBAR_BB': 'Pin bar + Bollinger', 'DONCHIAN_FADE': 'Donchian fade', 'STOCH_X': 'Estocástico cruzamento',
         'EMA_PULLBACK': 'EMA pullback', 'BB_RSI_MR': 'Bollinger + RSI', 'DONCHIAN_BO': 'Donchian breakout',
         'KELTNER_REV': 'Keltner reentrada', 'CONSEC_FADE': 'N velas seguidas (fade)', 'VWAP_REV': 'VWAP reversão',
         'ORB_SESSION': 'Opening Range Breakout', 'INSIDE_BO': 'Inside bar breakout'}
def curve(path, n=160):
    t = pd.read_csv(path, parse_dates=['entrada_utc', 'saida_utc'])
    t = t[t.real]
    eq = 100 + t.lucro_eur.cumsum().values
    ts = t.saida_utc.astype('int64').values // 10**9 if t.saida_utc.dtype.kind == 'M' else pd.to_datetime(t.saida_utc).astype('int64').values // 10**9
    idx = np.unique(np.linspace(0, len(eq) - 1, min(n, len(eq))).astype(int)) if len(eq) else []
    return [[int(ts[i]), round(float(eq[i]), 2)] for i in idx]
fams = []
for _, r in s.iterrows():
    f = r['familia']
    fams.append({'id': f, 'nome': NAMES[f], 'tf': int(r['tf']),
                 'bt': {k.split(':')[1]: r[k] for k in r.index if k.startswith('backtest:')},
                 'fw': {k.split(':')[1]: r[k] for k in r.index if k.startswith('forward:')},
                 'curve': curve(os.path.join(OUT, f'trades_{f}.csv')), 'params': det[f]['params']})
A = json.load(open(os.path.join(OUT, 'A_RSI_TENDENCIA.json')))
cands = {}
for n in ('A_RSI_TENDENCIA', 'B_MACD_ASIA', 'C_PINBAR_1M', 'REGRA_PRE_DECLARADA'):
    d = json.load(open(os.path.join(OUT, f'{n}.json')))
    cands[n] = {'metrics': d['metrics'], 'estrito': d['estrito'], 'mc': d['monte_carlo_100_trades'], 'params': d['params']}
data = {'familias': fams, 'A': {'curve': curve(os.path.join(OUT, 'trades_A_RSI_TENDENCIA.csv'), 400), 'metrics': A['metrics'],
        'mensal': A['mensal'], 'spread': A['spread'], 'latencia': A['latencia'], 'lotes': A['lotes'],
        'saidas': A['saidas'], 'mc': A['monte_carlo_100_trades'], 'mc_fw': A['monte_carlo_100_trades_so_forward'],
        'chunks': A['chunks'], 'estrito': A['estrito']},
        'candidatos': cands, 'forward_inicio': int(pd.Timestamp('2026-05-01').timestamp())}
json.dump(data, open(os.path.join(OUT, 'html_data.json'), 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print('ok', len(json.dumps(data, default=str)))
