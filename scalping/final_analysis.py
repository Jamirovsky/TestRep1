"""
Análise final: pega nos resultados do loop de pesquisa, escolhe o melhor setup de cada
família (APENAS pelo score do backtest), corre forward test, testes de sensibilidade de
custos e gera tabelas/gráficos para o relatório.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scalping.backtest import run, passes, score, ACCOUNT  # noqa

OUT = os.path.join(os.path.dirname(__file__), '..', 'report')


def load(paths):
    rows = []
    for p in paths:
        if os.path.exists(p):
            with open(p) as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def best_per_family(rows, k=1):
    fam = {}
    for r in rows:
        fam.setdefault(r['params']['family'], []).append(r)
    out = {}
    for f, rs in fam.items():
        rs.sort(key=lambda r: -r['score_bt'])
        out[f] = rs[:k]
    return out


def equity_plot(tr, title, path, eurusd):
    tr = tr[tr.real]
    eq = 100 + tr['lucro_eur'].cumsum()
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.plot(tr['saida_utc'], eq, lw=1.4, color='#2563eb')
    ax.axvline(pd.Timestamp('2026-05-01'), color='#dc2626', ls='--', lw=1)
    ax.text(pd.Timestamp('2026-05-04'), ax.get_ylim()[1], ' forward test →', va='top', color='#dc2626', fontsize=9)
    ax.axhline(100, color='#9ca3af', lw=0.8)
    ax.set_title(title, fontsize=10)
    ax.set_ylabel('Saldo (€)')
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fmt(mt):
    return {
        'Trades': mt['trades'],
        'Win rate %': round(mt['win_rate'] * 100, 1),
        'Profit factor': round(mt['profit_factor'], 2) if np.isfinite(mt['profit_factor']) else 99,
        'Lucro €': round(mt['net'] / ACCOUNT['eurusd'], 2),
        'Retorno %': round(mt['ret_pct'], 1),
        'Max DD %': round(mt['max_dd_pct'], 1),
        'Perdas seguidas máx': mt['max_consec_losses'],
    }


def main(paths):
    os.makedirs(OUT, exist_ok=True)
    if paths[0].endswith('robust_rank.json'):
        R = json.load(open(paths[0]))
        bpf = {}
        for r in R:  # já ordenado por score robusto
            r = {**r, 'score_bt': r['score_robusto']}
            bpf.setdefault(r['params']['family'], [r])
        rows = R
    else:
        rows = load(paths)
        bpf = best_per_family(rows, k=1)
    print('resultados carregados:', len(rows))
    summary = []
    details = {}
    for fam, rs in sorted(bpf.items(), key=lambda kv: -kv[1][0]['score_bt']):
        p = rs[0]['params']
        r, tr = run(p, return_trades=True)
        tag = fam
        equity_plot(tr, f'{fam} — saldo da conta de 100€ (0.01 lote)', os.path.join(OUT, f'equity_{tag}.png'), ACCOUNT['eurusd'])
        tr.to_csv(os.path.join(OUT, f'trades_{tag}.csv'), index=False)
        sens = {}
        for sp in (15, 25, 35, 50):
            rr = run(p, costs={'spread': float(sp)})
            sens[sp] = {'bt_pf': round(rr['backtest']['profit_factor'], 2), 'fw_pf': round(rr['forward']['profit_factor'], 2),
                        'bt_ret': round(rr['backtest']['ret_pct'], 1), 'fw_ret': round(rr['forward']['ret_pct'], 1)}
        row = {'familia': fam, 'tf': p['tf'], 'score_bt': round(rs[0]['score_bt'], 1),
               'cumpre_bt': passes(r['backtest']), 'cumpre_fw': passes(r['forward'], min_trades=0),
               'cumpre_total': passes(r['total'])}
        for seg in ('backtest', 'forward', 'total'):
            for k, v in fmt(r[seg]).items():
                row[f'{seg}:{k}'] = v
        summary.append(row)
        details[fam] = {'params': p, 'metrics': {s: fmt(r[s]) for s in ('backtest', 'forward', 'total')},
                        'chunks': r['chunks'], 'sensibilidade_spread': sens,
                        'virtual_trades': r['total'].get('virtual_trades', 0)}
        # tabela mensal
        t = tr[tr.real].copy()
        t['mes'] = t['entrada_utc'].dt.to_period('M').astype(str)
        g = t.groupby('mes').agg(trades=('lucro_eur', 'size'), lucro_eur=('lucro_eur', 'sum'),
                                 win_rate=('lucro_eur', lambda x: (x > 0).mean() * 100))
        details[fam]['mensal'] = g.round(2).reset_index().to_dict(orient='records')
        print(fam, row['backtest:Retorno %'], row['forward:Retorno %'])
    pd.DataFrame(summary).to_csv(os.path.join(OUT, 'resumo_familias.csv'), index=False)
    with open(os.path.join(OUT, 'detalhes.json'), 'w') as f:
        json.dump(details, f, indent=1, default=str)
    # estatísticas do loop
    st = {'setups_registados': len(rows)}
    with open(os.path.join(OUT, 'loop_stats.json'), 'w') as f:
        json.dump(st, f)


if __name__ == '__main__':
    main(sys.argv[1:] or ['results/search_main.jsonl'])


def champion_analysis(p, name='campeao'):
    """Análise aprofundada de um setup escolhido."""
    from scalping.robustness import monte_carlo, neighbourhood_report
    os.makedirs(OUT, exist_ok=True)
    r, tr = run(p, return_trades=True)
    tr.to_csv(os.path.join(OUT, f'trades_{name}.csv'), index=False)
    equity_plot(tr, f'Estratégia final — saldo da conta de 100€ ({ACCOUNT["lots"]} lote)', os.path.join(OUT, f'equity_{name}.png'), ACCOUNT['eurusd'])
    real = tr[tr.real]
    fw = real[real.entrada_utc >= '2026-05-01']
    bt = real[real.entrada_utc < '2026-05-01']
    res = {'params': p, 'metrics': {s: fmt(r[s]) for s in ('backtest', 'forward', 'total')}, 'chunks': r['chunks']}
    # win rate estrito: breakeven conta como perda
    def strict(df):
        x = df.copy()
        win = (x.saida == 'TP') | ((x.saida == 'TEMPO') & (x.lucro_eur > 0))
        mcl = cur = 0
        for w in win:
            cur = 0 if w else cur + 1
            mcl = max(mcl, cur)
        return {'win_rate_estrito': round(win.mean() * 100, 1), 'perdas_seguidas_estrito': mcl}
    res['estrito'] = {'backtest': strict(bt), 'forward': strict(fw), 'total': strict(real)}
    res['saidas'] = real.groupby('saida', observed=True).lucro_eur.agg(['count', 'mean', 'sum']).round(3).reset_index().to_dict(orient='records')
    res['duracao_min'] = ((real.saida_utc - real.entrada_utc).dt.total_seconds() / 60).describe().round(1).to_dict()
    res['sl_tp_medios_usd'] = {'sl_mediano': round(real.sl_usd.median(), 1), 'tp_mediano': round(real.tp_usd.median(), 1),
                               'sl_min': round(real.sl_usd.min(), 1), 'sl_max': round(real.sl_usd.max(), 1),
                               'tp_min': round(real.tp_usd.min(), 1), 'tp_max': round(real.tp_usd.max(), 1)}
    res['compras_vendas'] = real.groupby('direcao').lucro_eur.agg(['count', 'sum', lambda x: (x > 0).mean() * 100]).round(2).reset_index().values.tolist()
    t = real.copy()
    t['mes'] = t['entrada_utc'].dt.to_period('M').astype(str)
    res['mensal'] = t.groupby('mes').agg(trades=('lucro_eur', 'size'), lucro_eur=('lucro_eur', 'sum'),
                                         win_rate=('lucro_eur', lambda x: (x > 0).mean() * 100)).round(2).reset_index().to_dict(orient='records')
    t['hora'] = t['entrada_utc'].dt.hour
    res['por_hora'] = t.groupby('hora').agg(trades=('lucro_eur', 'size'), lucro_eur=('lucro_eur', 'sum')).round(2).reset_index().to_dict(orient='records')
    res['spread'] = {}
    for sp in (10, 15, 25, 35, 50, 75):
        rr = run(p, costs={'spread': float(sp)})
        res['spread'][sp] = {'backtest': fmt(rr['backtest']), 'forward': fmt(rr['forward'])}
    res['latencia'] = {}
    for d in (1, 2, 5):
        rr = run({**p, 'entry_delay': d})
        res['latencia'][d] = {'backtest': fmt(rr['backtest']), 'forward': fmt(rr['forward'])}
    res['lotes'] = {}
    for lots in (0.01, 0.02, 0.03):
        rr = run(p, account={'lots': lots})
        res['lotes'][lots] = {'backtest': fmt(rr['backtest']), 'forward': fmt(rr['forward']), 'total': fmt(rr['total'])}
    res['monte_carlo_100_trades'] = monte_carlo(real.lucro_eur.values, 100)
    res['monte_carlo_100_trades_so_forward'] = monte_carlo(fw.lucro_eur.values, 100) if len(fw) > 10 else None
    res['vizinhanca'] = neighbourhood_report(p)
    with open(os.path.join(OUT, f'{name}.json'), 'w') as f:
        json.dump(res, f, indent=1, default=str)
    return res
