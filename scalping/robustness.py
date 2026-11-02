"""Testes de robustez para um setup: Monte Carlo, atraso de execução, vizinhança de parâmetros."""
import numpy as np
from .backtest import run, ACCOUNT
from .strategies import FAMILIES, COMMON


def monte_carlo(pnl_eur, n_trades=100, n_sims=20000, start=100.0, seed=0):
    """Reamostra (bootstrap) os trades e mede a probabilidade de violar os pressupostos
    nos próximos n_trades."""
    rng = np.random.default_rng(seed)
    pnl = np.asarray(pnl_eur)
    sims = rng.choice(pnl, size=(n_sims, n_trades), replace=True)
    eq = start + np.cumsum(sims, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.full((n_sims, 1), start), eq], axis=1), axis=1)[:, 1:]
    dd = ((peak - eq) / peak).max(axis=1) * 100
    loss = sims <= 0
    # maior sequência de perdas por simulação
    mcl = np.zeros(n_sims, int)
    cur = np.zeros(n_sims, int)
    for j in range(n_trades):
        cur = np.where(loss[:, j], cur + 1, 0)
        mcl = np.maximum(mcl, cur)
    wr = (~loss).mean(axis=1)
    gp = np.where(sims > 0, sims, 0).sum(axis=1)
    gl = -np.where(sims <= 0, sims, 0).sum(axis=1)
    pf = np.where(gl > 0, gp / np.maximum(gl, 1e-9), 99)
    final = eq[:, -1]
    return {
        'p_lucro': float((final > start).mean()),
        'lucro_mediano_eur': float(np.median(final - start)),
        'lucro_p5_eur': float(np.percentile(final - start, 5)),
        'lucro_p95_eur': float(np.percentile(final - start, 95)),
        'p_dd_maior_20': float((dd > 20).mean()),
        'dd_mediano': float(np.median(dd)),
        'dd_p95': float(np.percentile(dd, 95)),
        'p_3_perdas_seguidas': float((mcl >= 3).mean()),
        'p_wr_acima_57': float((wr > 0.57).mean()),
        'p_pf_acima_101': float((pf > 1.01).mean()),
        'p_todos_pressupostos': float(((final > start) & (dd <= 20) & (mcl < 3) & (wr > 0.57) & (pf > 1.01)).mean()),
    }


def neighbours(p):
    """Todos os setups que diferem de p num único parâmetro, um passo na grelha."""
    space = {**FAMILIES[p['family']][1], **COMMON}
    out = []
    for k, vals in space.items():
        if k in ('sl_mode', 'side') or k not in p or p[k] not in vals or len(vals) < 2:
            continue
        i = vals.index(p[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals) and vals[j] != p[k]:
                q = dict(p)
                q[k] = vals[j]
                if q.get('trend') != 'none':
                    q.setdefault('trend_len', 200)
                if q.get('guard_mode') == 1:
                    q.setdefault('guard_pause_h', 12)
                out.append((k, vals[j], q))
    return out


def neighbourhood_report(p):
    rows = []
    for k, v, q in neighbours(p):
        r = run(q)
        rows.append({'parametro': k, 'valor': v,
                     'bt_ret': round(r['backtest']['ret_pct'], 1), 'bt_pf': round(r['backtest']['profit_factor'], 2),
                     'bt_wr': round(r['backtest']['win_rate'] * 100, 1),
                     'fw_ret': round(r['forward']['ret_pct'], 1), 'fw_pf': round(r['forward']['profit_factor'], 2),
                     'fw_wr': round(r['forward']['win_rate'] * 100, 1),
                     'fw_mcl': r['forward']['max_consec_losses']})
    return rows
