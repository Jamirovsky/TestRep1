import json, html
from engine import S
from strategies import PCT_TP, PCT_SL

D = {(x['strat'], x['tf'], x.get('meta')): x for x in json.load(open(f'{S}/final_pick.json'))}
L = json.load(open(f'{S}/final_pick.json'))
get = lambda s, tf, i=0: [x for x in L if x['strat'] == s and x['tf'] == tf][i]

NAMES = {
 'swing': ('SwingHighToSky CCI+RSI', 'freqtrade-strategies · SwingHighToSky'),
 'stpull': ('Supertrend Pullback', 'Supertrend (freqtrade) + pullback RSI de Connors'),
 'connors': ('Connors RSI(2) Reversion', 'Larry Connors · "Short-Term Trading Strategies That Work"'),
 'willr': ('Williams %R Extremes', 'Larry Williams · %R'),
 'cluc': ('ClucMay Dip Buyer', 'freqtrade-strategies · ClucMay72018 / CombinedBinHAndCluc'),
 'downbars': ('Consecutive Bars Reversal', 'padrão clássico de N velas consecutivas'),
 'bbrsi': ('Bollinger + RSI Reversion', 'freqtrade-strategies · BbandRsi'),
 'binh': ('BinHV45 Crash Catcher', 'freqtrade-strategies · BinHV45'),
 'ibs': ('IBS Short Fade', 'Internal Bar Strength (literatura de mean-reversion)'),
 'stoch': ('Stochastic Cross Reversion', 'freqtrade-strategies · Strategy005 / SmoothScalp (estocástico)'),
}
RULES = {
 'swing': 'Entrada quando CCI(n) < −X e RSI(m) < Y (long; espelhado para short). Saída quando CCI > X2 e RSI > Y2, ou por TP/SL/tempo.',
 'stpull': 'Só compra com Supertrend(20, 2.0) em alta e filtro de tendência diária (preço acima da SMA de 50 dias). Entra quando o RSI(2) cai abaixo de 10 (pullback). Sai quando o Supertrend inverte, com TP de 1×ATR, SL de 6×ATR, trailing stop e máximo de 24 velas.',
 'connors': 'Compra quando o RSI(2–4) fica abaixo de um nível extremo e o preço está acima da SMA de tendência. Sai quando o fecho fica acima da SMA curta (5–10). Short espelhado.',
 'willr': 'Entra quando o Williams %R(n) atinge um extremo (≤ −98 ou ≥ −2), a favor do filtro de tendência. Sai quando o %R regressa ao meio ou por TP/SL/trailing.',
 'cluc': 'Compra quando o fecho fica abaixo da EMA lenta e abaixo de k × banda inferior de Bollinger(20,2), com o volume abaixo de vm × a média de 30 velas. Sai quando o preço regressa à banda média ou por TP/SL.',
 'downbars': 'Compra após N fechos consecutivos em queda (short espelhado), com TP/SL em ATR e trailing.',
 'bbrsi': 'Compra quando o RSI fica abaixo do nível e o fecho abaixo da banda inferior de Bollinger. Sai quando o RSI passa acima do nível de saída, quando o preço volta à banda média, ou por TP/SL.',
 'binh': 'Vela de queda forte (|Δfecho| > b·preço) que fecha abaixo da banda inferior de BB(40,2), com bandas largas (> a·preço) e pouca sombra inferior (< t·largura). Sai na média de BB ou por TP/SL.',
 'ibs': 'Short quando o IBS = (fecho−mínimo)/(máximo−mínimo) > 0.9, o preço sobe face a 3 velas atrás e está abaixo da SMA(100) e da SMA de 20 dias. TP de 0.75×ATR, SL de 1.5×ATR, só com ATR ≥ 8× o custo.',
 'stoch': 'O %K cruza o %D numa zona extrema (≤ lv ou ≥ 100−lv). Sai quando o %K atravessa o nível de saída, ou por TP/SL/trailing.',
}


def fmt_params(p):
    if not p: return ''
    pc = p.get('xmode') == 'pct'
    out = []
    side = p.get('side', 1)
    out.append('LONG' if side == 1 else 'SHORT')
    skip = {'xmode', 'tp_k', 'sl_k', 'trail', 'maxbars', 'dtrend', 'minvol', 'side'}
    for k, v in p.items():
        if k in skip: continue
        out.append(f'{k}={v}')
    if pc:
        out.append(f"TP {PCT_TP[p['tp_k']]*100:.2f}%" if p['tp_k'] else 'sem TP fixo')
        out.append(f"SL {PCT_SL[p['sl_k']]*100:.1f}%")
    else:
        out.append(f"TP {p['tp_k']}×ATR" if p['tp_k'] else 'sem TP fixo'); out.append(f"SL {p['sl_k']}×ATR")
    if p.get('trail'): out.append('trailing on')
    if p.get('maxbars'): out.append(f"máx {p['maxbars']} velas")
    if p.get('dtrend'): out.append(f"SMA {p['dtrend']}d")
    if p.get('minvol'): out.append(f"ATR ≥ {p['minvol']}× custo")
    return ''.join(f'<span class="chip">{html.escape(str(o))}</span>' for o in out)


def chip(ok, label_ok='Passa', label_no='Falha', partial=None):
    if partial: return f'<span class="st st-warn"><span aria-hidden="true">◐</span> {partial}</span>'
    return f'<span class="st st-good"><span aria-hidden="true">✓</span> {label_ok}</span>' if ok else f'<span class="st st-bad"><span aria-hidden="true">✕</span> {label_no}</span>'


def num(v, d=1, suf='', inf=False):
    if v is None: return '—'
    if inf and v >= 99: return '∞'
    return f'{v:.{d}f}{suf}'


def cell(m, crit=True):
    n, wr, pf, dd = m['trades'], m['winrate'], m['pf'], m['maxdd']
    c = lambda ok: 'ok' if ok else 'no'
    return (f'<td class="{c(n > 100) if crit else ""}">{int(n)}</td><td class="{c(wr >= 57)}">{num(wr)}%</td>'
            f'<td class="{c(pf >= 1.05)}">{num(pf, 2, inf=True)}</td><td class="{c(dd < 20)}">{num(dd)}%</td>')


# ---------------------------------------------------------------- ranking final
TOP = [
 # (strat, tf, idx, tier, status-label)
 ('swing', '15m', 0, 'A'), ('stpull', '4h', 0, 'A'), ('connors', '15m', 0, 'A'), ('willr', '15m', 0, 'A'),
 ('cluc', '15m', 0, 'B'), ('bbrsi', '15m', 0, 'B'), ('downbars', '15m', 0, 'B'), ('binh', '15m', 0, 'B'),
 ('ibs', '4h', 0, 'C'), ('stoch', '1h', 0, 'C'),
]
TIER = {'A': 'Cumpre todos os critérios no walk-forward e no forward test',
        'B': 'Cumpre no walk-forward 2021-26; forward positivo mas com poucos trades (&lt; 15)',
        'C': 'Cumpre parcialmente: um critério falha num dos períodos'}


def spark(curve, i):
    w, h, pad = 300, 70, 4
    lo, hi = min(curve + [1.0]), max(curve + [1.0])
    if hi - lo < 1e-6: hi = lo + 0.01
    n = len(curve)
    X = lambda k: pad + k * (w - 2 * pad) / (n - 1)
    Y = lambda v: h - pad - (v - lo) / (hi - lo) * (h - 2 * pad)
    pts = ' '.join(f'{X(k):.1f},{Y(v):.1f}' for k, v in enumerate(curve))
    area = f'{X(0):.1f},{h - pad} ' + pts + f' {X(n - 1):.1f},{h - pad}'
    fx = X(54)  # 2025-07 = índice 54 (desde 2021-01)
    y1 = Y(1.0)
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="Curva de capital 2021–2026" data-curve="{",".join(map(str, curve))}" data-lo="{lo}" data-hi="{hi}">'
            f'<rect x="{fx:.1f}" y="0" width="{w - pad - fx:.1f}" height="{h}" class="fwdzone"/>'
            f'<line x1="{pad}" x2="{w - pad}" y1="{y1:.1f}" y2="{y1:.1f}" class="base"/>'
            f'<polygon points="{area}" class="area"/><polyline points="{pts}" class="line"/>'
            f'<circle cx="{X(n - 1):.1f}" cy="{Y(curve[-1]):.1f}" r="3" class="end"/>'
            f'<line class="cross" x1="0" x2="0" y1="0" y2="{h}" visibility="hidden"/></svg>')


rows = []; cards = []
for rank, (s, tf, idx, tier) in enumerate(TOP, 1):
    x = get(s, tf, idx); nm, src = NAMES[s]
    if x['kind'] == 'WFO':
        o, f = x['oos'], x['fwd']
        bt = x['pre']
        p = x['current']
        rob = f"{x['ok_runs']}/{x['runs']} sementes"
        stress = x['stress']['pf']
        meth = 'Walk-forward (re-otimização periódica)'
    else:
        o = x['full']; f = x['fwd']; bt = x['is_']; p = x['params']
        rob = f"{round(x['stab'] * 100)}% vizinhos"
        stress = x['stress_fwd_pf']
        meth = 'Parâmetros fixos'
    rows.append(f'<tr><td class="rk">{rank}</td><td class="nm"><b>{nm}</b><small>{tf} · {meth}</small></td>'
                f'<td><span class="tier t{tier}">{tier}</span></td>{cell(o)}{cell(f, False)}<td>{num(stress, 2)}</td><td>{num(x["mc_dd95"])}%</td><td>{rob}</td></tr>')
    yrs = ''.join(f'<tr><td>{y}</td><td>{v[0]}</td><td>{num(v[1])}%</td><td>{num(v[2], 2, inf=True)}</td></tr>' for y, v in x['yearly'].items() if v[0] > 0)
    if x['kind'] == 'WFO':
        perf = (f'<dl class="kv"><div><dt>Walk-forward OOS 2021-01 → 2026-10</dt><dd>{int(o["trades"])} trades · WR {num(o["winrate"])}% · PF {num(o["pf"], 2)} · DD {num(o["maxdd"])}% · retorno {num(o["ret"])}%</dd></div>'
                f'<div><dt>Forward test jul/2025 → out/2026</dt><dd>{int(f["trades"])} trades · WR {num(f["winrate"])}% · PF {num(f["pf"], 2, inf=True)} · DD {num(f["maxdd"])}% · retorno {num(f["ret"])}%</dd></div>'
                f'<div><dt>Stress (custo 0,10%/lado)</dt><dd>PF {num(stress, 2)} · DD Monte-Carlo p95 {num(x["mc_dd95"])}%</dd></div>'
                f'<div><dt>Meta-configuração WFO</dt><dd>{x["meta"]} · ativa em {x["windows_active"]}/{x["windows"]} janelas · robustez {rob} (PF mediano {num(x["pf_med"], 2)}, mínimo {num(x["pf_min"], 2)})</dd></div></dl>')
    else:
        perf = (f'<dl class="kv"><div><dt>Backtest 2018–2023 (otimização)</dt><dd>{int(bt["trades"])} trades · WR {num(bt["winrate"])}% · PF {num(bt["pf"], 2)} · DD {num(bt["maxdd"])}%</dd></div>'
                f'<div><dt>Validação jan/2024 → jun/2025</dt><dd>{int(x["val"]["trades"])} trades · WR {num(x["val"]["winrate"])}% · PF {num(x["val"]["pf"], 2)} · DD {num(x["val"]["maxdd"])}%</dd></div>'
                f'<div><dt>Forward test jul/2025 → out/2026 (holdout intocado)</dt><dd>{int(f["trades"])} trades · WR {num(f["winrate"])}% · PF {num(f["pf"], 2, inf=True)} · DD {num(f["maxdd"])}% · retorno {num(f["ret"])}%</dd></div>'
                f'<div><dt>Período completo 2018 → 2026</dt><dd>{int(o["trades"])} trades · WR {num(o["winrate"])}% · PF {num(o["pf"], 2)} · DD {num(o["maxdd"])}% · CAGR {num(o["cagr"])}%</dd></div>'
                f'<div><dt>Stress e robustez</dt><dd>PF forward com custo 0,10%/lado: {num(stress, 2)} · DD Monte-Carlo p95 {num(x["mc_dd95"])}% · {rob} também passam</dd></div></dl>')
    cards.append(f'''<article class="card" id="s{rank}">
<header><span class="rk big">{rank}</span><div><h3>{nm} <span class="tf">{tf}</span></h3><p class="src">Origem: {src}</p></div><span class="tier t{tier}">Tier {tier}</span></header>
<div class="grid2"><div class="txt"><p>{RULES[s]}</p>
<p class="lbl">{"Parâmetros em vigor (última re-otimização, jul/2026)" if x["kind"] == "WFO" else "Parâmetros"}</p><div class="chips">{fmt_params(p)}</div>
{perf}</div>
<div class="viz"><p class="lbl">Capital 2021 → out/2026 <span class="muted">(zona sombreada = forward test)</span></p>{spark(x["curve"], rank)}<p class="tip" aria-live="polite"> </p>
<details><summary>Resultado por ano</summary><div class="tw"><table class="yr"><thead><tr><th>Ano</th><th>Trades</th><th>WR</th><th>PF</th></tr></thead><tbody>{yrs}</tbody></table></div></details></div></div>
</article>''')

# ---------------------------------------------------------------- multi-ativo
import pandas as pd
XT = pd.read_csv(f'{S}/xtransfer.csv'); XW = pd.read_csv(f'{S}/xwfo_summary.csv')
ASSETS = ['ETH', 'SOL', 'XRP']


def xcell(r):
    if r is None: return '<td class="xc na">—</td>'
    pf = r['all_pf']; ok = bool(r['pass_all'])
    cls = 'xg' if ok else ('xa' if pf > 1 else 'xr')
    why = []
    if r['all_winrate'] < 57: why.append(f"WR {r['all_winrate']:.1f}%")
    if r['all_maxdd'] >= 20: why.append(f"DD {r['all_maxdd']:.1f}%")
    if r['all_trades'] <= 100: why.append(f"{int(r['all_trades'])} trades")
    icon = '✓' if ok else ('◐' if pf > 1 else '✕')
    tip = f"{int(r['all_trades'])} trades · WR {r['all_winrate']:.1f}% · PF {r['all_pf']:.2f} · DD {r['all_maxdd']:.1f}% | forward: {int(r['fwd_trades'])} tr, PF {min(r['fwd_pf'], 99):.2f}"
    sub = ', '.join(why) if (why and not ok) else f"DD {r['all_maxdd']:.1f}%"
    return f'<td class="xc {cls}" title="{tip}"><b><span aria-hidden="true">{icon}</span> {pf:.2f}</b><small>{sub}</small></td>'


xrows = []; det = []; summary = []
for rank, (s_, tf, idx, tier) in enumerate(TOP, 1):
    nm = NAMES[s_][0]; cells = []; npf = 0; npass = 0; ntest = 0
    for a in ASSETS:
        t = XT[(XT.sym == a) & (XT.strat == s_) & (XT.tf == tf)]
        w = XW[(XW.sym == a) & (XW.strat == s_) & (XW.tf == tf)]
        tr_ = t.iloc[0].to_dict() if len(t) else None; wr_ = w.iloc[0].to_dict() if len(w) else None
        cells.append(xcell(tr_)); cells.append(xcell(wr_))
        for r in (tr_, wr_):
            if r is None: continue
            ntest += 1; npf += r['all_pf'] > 1; npass += bool(r['pass_all'])
            det.append(f"<tr><td>{nm}</td><td>{a}</td><td>{'Transferência' if r is tr_ else 'WFO no par'}</td><td>{int(r['all_trades'])}</td><td>{r['all_winrate']:.1f}%</td><td>{min(r['all_pf'], 99):.2f}</td><td>{r['all_maxdd']:.1f}%</td><td>{r['all_ret']:.1f}%</td><td>{int(r['fwd_trades'])}</td><td>{r['fwd_winrate']:.1f}%</td><td>{min(r['fwd_pf'], 99):.2f}</td><td>{r['fwd_maxdd']:.1f}%</td><td>{'' if r is tr_ else str(int(r['seeds_ok'])) + '/3'}</td><td>{'' if r is tr_ else str(int(r['size_dd20'] * 100)) + '%'}</td></tr>")
    verdict = 'xg' if npf / ntest >= 0.8 else ('xa' if npf / ntest >= 0.5 else 'xr')
    summary.append((nm, npf, ntest, npass))
    xrows.append(f'<tr><td class="rk">{rank}</td><td class="nm"><b>{nm}</b><small>{tf}</small></td>{"".join(cells)}<td class="xc {verdict}"><b>{npf}/{ntest}</b><small>{npass} cumprem tudo</small></td></tr>')

XSEC = f'''<section id="multiativo">
  <h2>Teste noutros pares: ETH, SOL e XRP</h2>
  <p>Testei as 10 estratégias nos três maiores pares de cripto a seguir ao BTC com dados disponíveis: ETHUSDT (desde ago/2017), SOLUSDT (desde ago/2020) e XRPUSDT (desde mai/2018), em velas de 1 minuto da Binance spot até 24/10/2026. Usei os mesmos custos e 100% do capital por trade. Cada par foi testado de duas formas:</p>
  <ul>
    <li><b>Transferência:</b> exatamente os parâmetros escolhidos no BTC, janela a janela, sem nenhuma re-otimização. É o teste mais exigente: nenhum dado do par entrou na escolha.</li>
    <li><b>WFO no par:</b> o mesmo procedimento walk-forward, re-otimizado só com o histórico passado desse par, com 3 sementes (mostro a corrida mediana). As estratégias de parâmetros fixos (#2 e #9) só têm teste de transferência.</li>
  </ul>
  <div class="legend"><span><span class="xk xg">✓</span> Cumpre os 4 critérios no período 2021 → out/2026 (parâmetros fixos: período completo)</span><span><span class="xk xa">◐</span> PF &gt; 1 mas falha outro critério, quase sempre DD &gt; 20% com 100% do capital</span><span><span class="xk xr">✕</span> PF &lt; 1 (perde dinheiro)</span></div>
  <div class="tw"><table class="main xt">
    <thead><tr><th></th><th class="nm"></th><th colspan="2">ETH</th><th colspan="2">SOL</th><th colspan="2">XRP</th><th>Veredicto</th></tr>
    <tr><th>#</th><th class="nm">Estratégia</th><th>Transf.</th><th>WFO</th><th>Transf.</th><th>WFO</th><th>Transf.</th><th>WFO</th><th>PF &gt; 1</th></tr></thead>
    <tbody>{"".join(xrows)}</tbody></table></div>
  <p class="muted" style="font-size:.85rem">Cada célula mostra o PF; o texto pequeno indica o que falhou. Passe o cursor para ver trades, WR, DD e forward.</p>
  <div class="note">
    <b>O que isto diz</b>
    <ul>
      <li><b>ClucMay Dip Buyer é o edge mais transferível:</b> PF &gt; 1 nos 6 testes (1,07 a 1,92). No WFO cumpre os 4 critérios em SOL (PF 1,83) e XRP (PF 1,92). Em transferência cumpre em XRP e falha em ETH e SOL só por DD acima de 20%.</li>
      <li><b>BinHV45 vem a seguir</b>, com PF &gt; 1 em 5 de 6 testes, mas o DD fica entre 25% e 34% com 100% do capital.</li>
      <li><b>SwingHighToSky (#1 no BTC)</b> cumpre tudo no XRP com os parâmetros do BTC (PF 1,71, WR 76%, DD 17%, forward PF 1,84), mas re-otimizada no próprio XRP o PF cai para 0,90. No SOL tem PF 1,30–1,46 e no ETH falha (PF 0,89–0,90).</li>
      <li><b>Consecutive Bars</b> cumpre tudo no ETH com WFO (PF 1,48, DD 7%, 3/3 sementes) e tem PF &gt; 1 em 4 de 6 testes.</li>
      <li><b>Williams %R, Stochastic, IBS Short e Supertrend 4h parecem específicas do BTC</b>, com PF &lt; 1 na maioria dos outros pares. Baixe a confiança nestas, mesmo nas que são Tier A no BTC.</li>
      <li><b>O ETH é o par mais difícil:</b> só 1 dos 18 testes (transferência + WFO) cumpre tudo. Em SOL e XRP o critério que mais falha é o DD, porque a volatilidade em 15m é 1,4 a 2× a do BTC (ATR mediano desde 2021: BTC 0,32%, ETH 0,44%, XRP 0,50%, SOL 0,65%). Onde o PF é positivo, uma fração menor do capital por trade baixa o DD para menos de 20% sem alterar o WR nem o PF (coluna "Tamanho p/ DD&lt;20%" na tabela detalhada).</li>
    </ul>
  </div>
  <details><summary>Tabela detalhada por par e método</summary><div class="tw"><table class="main det">
    <thead><tr><th class="nm">Estratégia</th><th>Par</th><th>Método</th><th>Trades</th><th>WR</th><th>PF</th><th>DD</th><th>Retorno</th><th>Fwd trades</th><th>Fwd WR</th><th>Fwd PF</th><th>Fwd DD</th><th>Sementes OK</th><th>Tamanho p/ DD&lt;20%</th></tr></thead>
    <tbody>{"".join(det)}</tbody></table></div></details>
</section>'''

TPL = open(f'{S}/report_tpl.html').read()
out = TPL.replace('{{ROWS}}', '\n'.join(rows)).replace('{{CARDS}}', '\n'.join(cards)).replace('{{XASSET}}', XSEC)
for nm, a, b, c in summary: print(nm, a, b, c)
open(f'{S}/relatorio_estrategias_crypto.html', 'w').write(out)
print('ok', len(out))
