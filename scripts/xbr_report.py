#!/usr/bin/env python3
"""Write docs/RESULTS_XBRUSD.md (Portuguese) from reports/xbr_top3.json + the loop reports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FAM = {"orb": "ORB (rompimento da faixa de abertura)", "rsi2": "RSI-2 a favor da tendência",
       "sweep": "Sweep (falso rompimento)", "momentum": "Momentum", "breakout": "Breakout Donchian",
       "fade": "Fade à VWAP da sessão", "bands": "Bands (fade ao desvio da média móvel)"}
SESS = {"london": "Londres 07–12 UTC", "ny": "Nova Iorque 12–18 UTC", "london_ny": "07–18 UTC",
        "overlap": "sobreposição 13–17 UTC", "extended": "06–20 UTC"}


def pct(x):
    return f"{x*100:.1f}%".replace(".", ",")


def num(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def chk(ok):
    return "✔" if ok else "✘"


def describe(t) -> str:
    s, e = t["strategy"], t["execution"]
    m = s["mode"]
    if m == "bands":
        entry = (f"fecho a ≥ {num(s['band_k'],1)} desvios-padrão da média de {s['bb_period']} barras, "
                 f"RSI(7) ≤ {num(s['rsi_lo'],0)} (compra) / ≥ {num(s['rsi_hi'],0)} (venda)"
                 + (f", ADX ≤ {num(s['adx_max'],0)}" if s["adx_max"] < 100 else "")
                 + (f", Efficiency Ratio ≤ {num(s['er_max'])}" if s["er_max"] < 1 else "")
                 + f", confirmação modo {s['confirm_mode']}")
    elif m == "fade":
        entry = (f"fecho a ≥ {num(s['band_k'],1)} σ da VWAP do dia, RSI(7) ≤ {num(s['rsi_lo'],0)}/≥ {num(s['rsi_hi'],0)}"
                 f", confirmação modo {s['confirm_mode']}")
    elif m == "rsi2":
        entry = (f"RSI({s['r2_period']}) ≤ {num(s['r2_lo'],0)} com fecho acima da EMA({s['trend_ema']}) → compra; "
                 f"RSI ≥ {num(100-s['r2_lo'],0)} abaixo da EMA → venda")
    elif m == "orb":
        entry = (f"faixa das {s['orb_hour']}:00 UTC ({s['orb_bars']} barras); "
                 + ("**fade** do primeiro rompimento" if s["orb_fade"] else "primeiro rompimento")
                 + (f" com folga de {num(s['orb_buffer_atr'],1)} ATR" if s["orb_buffer_atr"] else ""))
    elif m == "sweep":
        entry = (f"varre o máximo/mínimo de {s['sweep_lookback']} barras e fecha de volta para dentro, "
                 f"pavio ≥ {num(s['sweep_wick_atr'],1)} ATR → fade")
    elif m == "momentum":
        entry = (f"movimento de {s['mom_period']} barras ≥ {num(s['mom_min_atr'],1)} ATR, "
                 f"Efficiency Ratio ≥ {num(s['er_min'])}")
    else:
        entry = (f"rompimento Donchian {s['don_period']} barras, EMA 12/48 a favor, ADX ≥ {num(s['adx_min'],0)}, "
                 f"ATR ≥ {num(s['expansion_mult'])}× a média, ER ≥ {num(s['er_min'])}")
    ex = [f"stop = max({num(s['sl_atr'],1)} ATR, {num(s['min_sl_bp']/100,2)}% do preço)",
          f"alvo {num(s['tp_r'],1)}R"]
    if e["be_trigger_r"]:
        ex.append(f"break-even a +{num(e['be_trigger_r'],1)}R")
    if e["partial_r"]:
        ex.append(f"fecho parcial de 50% a +{num(e['partial_r'],2)}R")
    if e["trail_start_r"]:
        ex.append(f"trailing a partir de +{num(e['trail_start_r'],1)}R")
    ex += [f"máximo {e['max_bars']} min", f"{e['max_trades_per_day']} trades/dia",
           f"pausa {e['cooldown_bars']} min", f"risco {num(e['risk_pct']*100,2)}% por trade"]
    return f"**Entrada:** {entry}. **Saída:** " + ", ".join(ex) + "."


def chart(i, t):
    tr = pd.read_csv(ROOT / "reports" / f"xbr_top{i}_trades.csv", parse_dates=["exit_time"]).sort_values("exit_time")
    fig, ax = plt.subplots(figsize=(10, 3.8), dpi=110)
    ax.plot(tr["exit_time"], tr["r"].cumsum(), color="black", lw=1.6)
    ax.axvspan(pd.Timestamp("2025-01-01", tz="UTC"), tr["exit_time"].max(), color="tab:green", alpha=0.08,
               label="holdout 2025–26 (fora da amostra)")
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_ylabel("R acumulado")
    ax.set_title(f"Top {i}: XBRUSD {t['mode']} M{t['tf']} — 2019–2026")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = ROOT / "reports" / f"xbr_top{i}_equity.png"
    fig.savefig(path)
    plt.close(fig)
    return path.name


WF_RUNS = [("bands", "wf_m30t", "Bands M30 tight — portões WR≥57% PF≥1,02"),
           ("bands", "wf_m15b", "Bands M15 base — portões WR≥57% PF≥1,02"),
           ("rsi2", "wf_rsi2", "RSI-2 M30 tight — portões WR≥57% PF≥1,02"),
           ("bands", "wfr_m30t", "Bands M30 tight — portões WR≥55% PF≥1,0"),
           ("bands", "wfr_m15b", "Bands M15 base — portões WR≥55% PF≥1,0"),
           ("rsi2", "wfr_rsi2", "RSI-2 M30 tight — portões WR≥55% PF≥1,0")]


def _m(tr):
    if not len(tr):
        return None
    w, l = tr.r[tr.r > 0].sum(), -tr.r[tr.r <= 0].sum()
    eq = (1 + 0.005 * tr.r).cumprod()
    dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
    t = tr.r.mean() / tr.r.std() * len(tr) ** 0.5 if len(tr) > 1 else 0.0
    return len(tr), (tr.r > 0).mean(), (w / l if l > 0 else float("inf")), dd, t


def wf_section() -> str:
    rows = ["| estratégia | período | trades | WR | PF | DD máx (0,5%/trade) | t | alvos |",
            "|---|---|---|---|---|---|---|---|"]
    for mode, label, name in WF_RUNS:
        f = ROOT / "reports" / f"XBRUSD_{mode}_{label}_oos_trades.csv"
        if not f.exists():
            rows.append(f"| {name} | 2021-01 → 2026-10 | 0 — nenhum reajuste passou os portões (EA parado) | | | | | |")
            continue
        tr = pd.read_csv(f, parse_dates=["entry_time"]).sort_values("entry_time")
        for per, sub in (("2021-01 → 2026-10", tr),
                         ("só 2025-01 → 2026-10", tr[tr.entry_time >= pd.Timestamp("2025-01-01", tz="UTC")])):
            m = _m(sub)
            if m is None:
                rows.append(f"| {name} | {per} | 0 — nenhum reajuste passou os portões (EA parado) | | | | | |")
                continue
            n, wr, pf, dd, t = m
            okk = [n >= 100, wr >= 0.57, pf >= 1.01, dd <= 20]
            rows.append(f"| {name} | {per} | {n} | {pct(wr)} | {num(pf)} | {num(dd,1)}% | {num(t)} | "
                        f"{'**todos**' if all(okk) else f'{sum(okk)}/4'} |")
    return "\n".join(rows) + ("\n\nEm cada janela de 120 dias o otimizador reescolhe os parâmetros com os 2 anos "
                               "anteriores. Se nenhuma configuração passa os portões, o EA não negoceia nessa "
                               "janela. O DD está calculado a 0,5% de risco por trade.")


def main() -> int:
    top = json.loads((ROOT / "reports" / "xbr_top3.json").read_text())
    rounds = [json.loads(p.read_text()) for p in sorted((ROOT / "reports").glob("xbr_loop_r*.json"))]
    L = []
    L += ["# Relatório XBRUSD (Brent) — top 3 estratégias", ""]
    L += ["**Pedido:** criar estratégias de scalping para o XBRUSD e otimizá-las em loop até cumprir, no mínimo, "
          "**WR ≥ 57%, PF ≥ 1,01, DD máx. ≤ 20% e ≥ 100 trades**; entregar o top 3 a correr em MT5.", ""]
    L += ["## Resumo", "",
          "| # | EA (MT5) | Estratégia | TF | Sessão | Holdout 2025-01 → 2026-10: trades | WR | PF | DD máx | t | Alvos |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in top["top"]:
        h = t["holdout_2025_2026"]
        okt = [h["n_trades"] >= 100, h["win_rate"] >= 0.57, h["profit_factor"] >= 1.01, h["max_dd_pct"] <= 20]
        L.append(f"| {t['rank']} | [`{t['ea']}.mq5`](../mql5/{t['ea']}.mq5) | {FAM[t['mode']]} | M{t['tf']} | "
                 f"{SESS.get(t['strategy']['session'], t['strategy']['session'])} | {h['n_trades']} {chk(okt[0])} | "
                 f"{pct(h['win_rate'])} {chk(okt[1])} | {num(h['profit_factor'])} {chk(okt[2])} | "
                 f"{num(h['max_dd_pct'],1)}% {chk(okt[3])} | {num(h['t_stat'])} | "
                 f"{'**todos**' if all(okt) else f'{sum(okt)}/4'} |")
    L += ["", "No mesmo período de ajuste (2019–2024, dentro da amostra):", "",
          "| # | trades | WR | PF | DD máx | anos positivos |", "|---|---|---|---|---|---|"]
    for t in top["top"]:
        f = t["fit_2019_2024"]
        L.append(f"| {t['rank']} | {f['n_trades']} | {pct(f['win_rate'])} | {num(f['profit_factor'])} | "
                 f"{num(f['max_dd_pct'],1)}% | {t['years_positive']}/6 |")
    L += ["", "INTERPRETATION", ""]
    for t in top["top"]:
        i = t["rank"]
        img = chart(i, t)
        L += [f"## Top {i} — {FAM[t['mode']]}, M{t['tf']}", "", describe(t), "",
              "| ano | " + " | ".join(str(y["year"]) for y in t["by_year"]) + " |",
              "|---|" + "---|" * len(t["by_year"]),
              "| trades | " + " | ".join(str(y["trades"]) for y in t["by_year"]) + " |",
              "| WR | " + " | ".join(pct(y["wr"]) for y in t["by_year"]) + " |",
              "| PF | " + " | ".join(num(y["pf"]) if y["pf"] is not None else "–" for y in t["by_year"]) + " |",
              "| R | " + " | ".join(num(y["total_r"], 1) for y in t["by_year"]) + " |",
              "", "2025 e 2026 são o holdout, fora da amostra. "
              "Sensibilidade a custos no holdout (PF / WR):", "",
              "| custo × | " + " | ".join(num(c["cost_multiple"], 1) for c in t["holdout_cost_curve"]) + " |",
              "|---|" + "---|" * len(t["holdout_cost_curve"]),
              "| PF | " + " | ".join(num(c["pf"]) for c in t["holdout_cost_curve"]) + " |",
              "| WR | " + " | ".join(pct(c["wr"]) for c in t["holdout_cost_curve"]) + " |",
              "", f"![top {i}](../reports/{img})", ""]
    L += ["## Volta final: walk-forward com reotimização a cada 4 meses", "", "WF_SECTION", ""]
    L += ["## O loop de otimização", "", "LOOP_TABLE", ""]
    L += ["## Como correr no MT5", "",
          "1. Copiar `mql5/ScalperXBR_T1.mq5`, `ScalperXBR_T2.mq5` e `ScalperXBR_T3.mq5` para `MQL5/Experts/` "
          "e compilar no MetaEditor.",
          "2. Anexar ao gráfico **XBRUSD** (qualquer timeframe; o EA usa o timeframe de sinal definido em "
          "`InpSignalTF`). Se a corretora usar outro nome (`UKOIL`, `BRENT`, `XBRUSD.r`), pôr `InpCheckSymbol=false`.",
          "3. **Strategy Tester:** usar \"Every tick based on real ticks\" e `InpGmtOffsetHours` = offset do servidor "
          "(normalmente 2 no inverno e 3 no verão), porque todas as horas são UTC.",
          "4. **Otimização no MT5:** carregar o `.set` correspondente em `mql5/sets/` (as linhas `Y` são os "
          "parâmetros a otimizar) e usar o *genetic algorithm* com *Forward 1/3*.",
          "5. **Risco por trade:** definido em `InpRiskPct`. Foi escolhido em 2019–2024 para o DD ficar ≤ 12% no "
          "ajuste (folga para os 20%). O DD escala com este valor; a WR e o PF não.",
          "6. Os três EAs usam magic numbers diferentes e podem correr em simultâneo no mesmo gráfico ou em gráficos "
          "separados.", ""]
    L += ["## Pressupostos e limites", "",
          "- **Dados:** OANDA BCO/USD M1 reais, jan/2019 → out/2026 (preços médios). Os custos modelados são "
          "spread de 5 bp (US$0,04 a US$80), que alarga ×2 na sessão asiática, ×5 no rollover e com a volatilidade, "
          "mais slippage de 0,6 bp na entrada e 1,5 bp no stop. São cerca de 7 bp por trade, do lado conservador para "
          "uma conta ECN.",
          "- **Este ambiente não tem MetaTrader 5.** A otimização foi feita no backtester Python do repositório, que "
          "replica a lógica do EA. Não consegui compilar os EAs nem corrê-los no Strategy Tester aqui. "
          "Confirma-os no MT5 com os ticks da tua corretora antes de os usar.",
          "- **Seleção:** foram geradas e avaliadas milhares de configurações em várias voltas, e o top 3 foi "
          "escolhido só com 2019–2024. O holdout 2025–26 foi olhado **uma única vez**, já com o top 3 escolhido. "
          "Mesmo assim, com edges deste tamanho, um t-stat abaixo de 2 significa que o resultado pode ser sorte.",
          ""]
    text = "\n".join(L)
    rows = ["| volta | protocolo | resultado |", "|---|---|---|"]
    rows += ["| 1 | 7 famílias × M1/M5/M15/M30, ajuste 2019–22 com portões WR ≥ 57%, PF ≥ 1,05, DD ≤ 20%, "
             "validação 2023–24 | 1 configuração passou o ajuste (M30 breakout) e falhou a validação (PF 0,64). "
             "M1 é inviável (custo 0,9 ATR) |",
             "| 2 | variante *tight* (alvos 0,3–0,8R, break-even, parcial), portões WR ≥ 55%, PF ≥ 1,0 | "
             "3 passaram o ajuste (WR 62–72%) e todas caíram na validação (PF 0,50–0,69): mudança de regime |",
             "| — | estatística direta | reversão após 2σ: 1–5 bp; ORB das 07/13 UTC reverte ~4–5 bp → nova família "
             "**ORB fade**; nenhum efeito sessão/dia × hora acima do custo (~7 bp) |"]
    for r in rounds:
        n_cells = len(r["cells"])
        n_viable = sum(1 for c in r["cells"] if c["top"])
        n_meet = sum(1 for c in r["cells"] for t in c["top"] if t.get("meets_targets_fit"))
        g = r["gates"]
        proto = {"r3": "protocolo v2: ajuste em 2019–2024 inteiro, portões WR ≥ 57%, PF ≥ 1,02, DD ≤ 20%; "
                       "ordenação por consistência anual",
                 "r4": "duas fases: entradas com vantagem bruta e depois só saídas; sem portão de DD",
                 "r5": "portões WR ≥ 55%, PF ≥ 1,0, 500 iterações, M15/M30",
                 "r6": "pontuação suave orientada aos alvos + subida coordenada a partir das 3 melhores sementes "
                       "por célula",
                 "r7": "aprofundamento das famílias que funcionaram (bands, RSI-2, fade) em M10/M15/M20/M30, "
                       "5 sementes, piso de 60 trades/ano para chegar aos 100 trades no holdout"}.get(
                     r["round"], json.dumps(g))
        rows.append(f"| {r['round'][1:]} | {proto} | {n_cells} células, {n_viable} com candidatos, "
                    f"{n_meet} candidatos a cumprir os alvos no ajuste |")
    text = text.replace("LOOP_TABLE", "\n".join(rows))
    text = text.replace("WF_SECTION", wf_section())
    interp = sys.argv[1] if len(sys.argv) > 1 else ""
    text = text.replace("INTERPRETATION", interp)
    (ROOT / "docs" / "RESULTS_XBRUSD.md").write_text(text)
    print("wrote docs/RESULTS_XBRUSD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
