"""
Motor de backtest para scalping BTCUSD (CFD) em velas de 1 minuto.

Modelo de execução (igual ao MT4/MT5):
  * Os preços dos dados são tratados como MID. Ask = mid + spread/2, Bid = mid - spread/2.
  * Compra entra no Ask, sai no Bid. Venda entra no Bid, sai no Ask.
  * SL/TP são distâncias em USD (pontos de preço) a partir do preço de execução,
    exatamente como se editam no terminal (ex.: SL=300 -> stop 300$ abaixo da entrada).
  * Ordens stop (SL) sofrem slippage adicional; se a vela abrir para lá do stop (gap),
    a execução é ao preço de abertura (pior caso).
  * Se SL e TP forem tocados na mesma vela de 1m assume-se que o SL foi tocado primeiro
    (pressuposto conservador).
  * Sinais calculados no fecho da vela do timeframe do setup; entrada na abertura do
    minuto seguinte (sem look-ahead).
  * Uma posição de cada vez.
"""
import numpy as np
from numba import njit

# Razões de saída
R_TP, R_SL, R_TIME, R_BE = 0, 1, 2, 3


@njit(cache=True)
def simulate(o, h, l, c, ts,
             sig_idx, sig_dir, sig_sl, sig_tp,
             spread, slip, max_hold,
             be_frac,
             guard_k, guard_mode, guard_pause_s,
             swap_long_day, swap_short_day, rollover_hour):
    """
    sig_idx: índice (1m) da vela onde se entra na abertura
    sig_dir: +1 compra / -1 venda
    sig_sl, sig_tp: distâncias em USD
    be_frac: se >0, quando o lucro atinge be_frac*TP move SL para entrada (+1$)
    guard_mode: 0 = sem proteção; 1 = pausa de guard_pause_s segundos após guard_k perdas seguidas;
                2 = "modo sombra": após guard_k perdas seguidas as entradas passam a virtuais
                    até um trade virtual ganhar.
    swap_*_day: custo de swap por rollover em USD por 1 BTC (positivo = custo)
    """
    n = sig_idx.shape[0]
    N = o.shape[0]
    out_ei = np.empty(n, np.int64)
    out_xi = np.empty(n, np.int64)
    out_dir = np.empty(n, np.int64)
    out_ep = np.empty(n, np.float64)
    out_xp = np.empty(n, np.float64)
    out_pnl = np.empty(n, np.float64)
    out_reason = np.empty(n, np.int64)
    out_real = np.empty(n, np.bool_)
    k = 0
    busy_until = -1
    consec = 0
    shadow = False
    pause_until_ts = -1
    half = spread / 2.0
    for s in range(n):
        i = sig_idx[s]
        if i <= busy_until or i >= N:
            continue
        if guard_mode == 1 and ts[i] < pause_until_ts:
            continue
        d = sig_dir[s]
        sl = sig_sl[s]
        tp = sig_tp[s]
        if d == 1:
            ep = o[i] + half
            sl_px = ep - sl
            tp_px = ep + tp
        else:
            ep = o[i] - half
            sl_px = ep + sl
            tp_px = ep - tp
        be_done = False
        reason = R_TIME
        xp = 0.0
        j = i
        last = min(N - 1, i + max_hold)
        while True:
            # bid/ask extremos desta vela
            if d == 1:
                bid_o = o[j] - half
                bid_h = h[j] - half
                bid_l = l[j] - half
                if bid_o <= sl_px and j > i:
                    xp = bid_o - slip
                    reason = R_BE if be_done else R_SL
                    break
                if bid_l <= sl_px:
                    xp = sl_px - slip if not be_done else sl_px
                    reason = R_BE if be_done else R_SL
                    break
                if bid_o >= tp_px and j > i:
                    xp = bid_o
                    reason = R_TP
                    break
                if bid_h >= tp_px:
                    xp = tp_px
                    reason = R_TP
                    break
                if be_frac > 0 and not be_done and bid_h - ep >= be_frac * tp:
                    be_done = True
                    sl_px = ep + 1.0
            else:
                ask_o = o[j] + half
                ask_h = h[j] + half
                ask_l = l[j] + half
                if ask_o >= sl_px and j > i:
                    xp = ask_o + slip
                    reason = R_BE if be_done else R_SL
                    break
                if ask_h >= sl_px:
                    xp = sl_px + slip if not be_done else sl_px
                    reason = R_BE if be_done else R_SL
                    break
                if ask_o <= tp_px and j > i:
                    xp = ask_o
                    reason = R_TP
                    break
                if ask_l <= tp_px:
                    xp = tp_px
                    reason = R_TP
                    break
                if be_frac > 0 and not be_done and ep - ask_l >= be_frac * tp:
                    be_done = True
                    sl_px = ep - 1.0
            if j >= last:
                xp = (c[j] - half) if d == 1 else (c[j] + half)
                reason = R_TIME
                break
            j += 1
        pnl = (xp - ep) * d
        # swap: cobra por cada rollover atravessado
        if swap_long_day != 0.0 or swap_short_day != 0.0:
            t0 = ts[i]
            t1 = ts[j]
            day0 = (t0 - rollover_hour * 3600) // 86400
            day1 = (t1 - rollover_hour * 3600) // 86400
            nroll = day1 - day0
            if nroll > 0:
                pnl -= nroll * (swap_long_day if d == 1 else swap_short_day)
        real = not shadow
        out_ei[k] = i
        out_xi[k] = j
        out_dir[k] = d
        out_ep[k] = ep
        out_xp[k] = xp
        out_pnl[k] = pnl
        out_reason[k] = reason
        out_real[k] = real
        k += 1
        busy_until = j
        win = pnl > 0
        if guard_mode == 2:
            if shadow:
                if win:
                    shadow = False
                    consec = 0
            else:
                if win:
                    consec = 0
                else:
                    consec += 1
                    if guard_k > 0 and consec >= guard_k:
                        shadow = True
        else:
            if win:
                consec = 0
            else:
                consec += 1
                if guard_mode == 1 and guard_k > 0 and consec >= guard_k:
                    pause_until_ts = ts[j] + guard_pause_s
                    consec = 0
    return (out_ei[:k], out_xi[:k], out_dir[:k], out_ep[:k], out_xp[:k],
            out_pnl[:k], out_reason[:k], out_real[:k])


def metrics(pnl_usd, start_balance_usd, ts_exit=None):
    """pnl_usd: lucro/prejuízo por trade (já na moeda da conta, em USD)."""
    n = len(pnl_usd)
    res = dict(trades=n)
    if n == 0:
        res.update(win_rate=0.0, profit_factor=0.0, net=0.0, max_dd_pct=0.0,
                   max_consec_losses=0, avg_win=0.0, avg_loss=0.0, expectancy=0.0,
                   final_balance=start_balance_usd, ret_pct=0.0)
        return res
    wins = pnl_usd > 0
    gp = pnl_usd[wins].sum()
    gl = -pnl_usd[~wins].sum()
    eq = start_balance_usd + np.cumsum(pnl_usd)
    peak = np.maximum.accumulate(np.concatenate([[start_balance_usd], eq]))[1:]
    dd = (peak - eq) / peak
    # perdas consecutivas
    mcl = 0
    cur = 0
    for w in wins:
        if w:
            cur = 0
        else:
            cur += 1
            if cur > mcl:
                mcl = cur
    res.update(
        win_rate=float(wins.mean()),
        profit_factor=float(gp / gl) if gl > 0 else float('inf'),
        net=float(pnl_usd.sum()),
        max_dd_pct=float(dd.max() * 100),
        max_consec_losses=int(mcl),
        avg_win=float(pnl_usd[wins].mean()) if wins.any() else 0.0,
        avg_loss=float(pnl_usd[~wins].mean()) if (~wins).any() else 0.0,
        expectancy=float(pnl_usd.mean()),
        final_balance=float(eq[-1]),
        ret_pct=float((eq[-1] / start_balance_usd - 1) * 100),
        min_balance=float(eq.min()),
    )
    return res
