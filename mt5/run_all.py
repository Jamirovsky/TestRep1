"""One command on the Windows PC: export broker data + run the Strategy Tester.

    pip install MetaTrader5 pandas
    python mt5/run_all.py

What it does
1. Connects to the running MT5 terminal (Capital Point Trading) and exports
   BTCUSD M1 history + contract spec into data/  (mt5/export_btcusd.py).
2. Asks you to CLOSE MetaTrader 5 (the tester can only be started from a
   closed terminal), then runs two unattended Strategy Tester runs of
   AMS_BTCUSD ("Every tick based on real ticks", 150 EUR deposit):
       full     2025-01-01 -> today
       forward  2026-08-01 -> today
3. Copies the HTML reports to results/mt5/ and prints the key numbers next to
   the Python backtest's numbers.

Then commit/push data/mt5_symbol_spec.json, data/mt5_btcusd_m1.csv.gz and
results/mt5/, or paste the printed summary into the chat.
"""
from __future__ import annotations
import datetime as dt
import os, re, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mt5"))

EXPECTED = {"full": "~280 trades, PF ~1.5, max DD ~12%, ~617 EUR",
            "forward": "~57 trades, PF ~1.5, max DD ~13%, ~202 EUR"}


def export():
    import MetaTrader5 as mt5
    import export_btcusd
    sys.argv = ["export_btcusd.py", "--symbol", "BTCUSD", "--start", "2024-11-01"]
    export_btcusd.main()                       # ends with mt5.shutdown()
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    ti, acc = mt5.terminal_info(), mt5.account_info()
    info = dict(exe=os.path.join(ti.path, "terminal64.exe"), data=ti.data_path,
                leverage=acc.leverage, currency=acc.currency)
    mt5.shutdown()
    return info


def ini_text(name, start, end, info):
    return "\n".join([
        "[Tester]",
        "Expert=AMS_BTCUSD",
        "Symbol=BTCUSD",
        "Period=M15",
        "Model=4",                 # every tick based on real ticks
        "Optimization=0",
        f"FromDate={start}",
        f"ToDate={end}",
        "ForwardMode=0",
        "Deposit=150",
        "Currency=EUR",
        f"Leverage=1:{info['leverage']}",
        "ExecutionMode=0",
        "Visual=0",
        f"Report=reports\\AMS_{name}",
        "ReplaceReport=1",
        "ShutdownTerminal=1",
        "",
    ])


def run_tester(name, start, end, info):
    ini = os.path.join(info["data"], f"ams_{name}.ini")
    with open(ini, "w", encoding="utf-16") as f:
        f.write(ini_text(name, start, end, info))
    print(f"\nRunning Strategy Tester '{name}' {start} -> {end} (can take 10-40 min) ...")
    t = time.time()
    subprocess.run([info["exe"], f"/config:{ini}"], check=False)
    print(f"  finished in {(time.time() - t) / 60:.1f} min")
    for ext in (".htm", ".html", ".xml"):
        src = os.path.join(info["data"], "reports", f"AMS_{name}{ext}")
        if os.path.exists(src):
            dst_dir = os.path.join(ROOT, "results", "mt5")
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, os.path.basename(src))
            shutil.copy2(src, dst)
            for png in ("", "-hst", "-mfemae", "-holding"):
                p = src.replace(ext, f"{png}.png")
                if os.path.exists(p):
                    shutil.copy2(p, dst_dir)
            return dst
    print("  report not found - check the MT5 'Journal' tab of the tester")
    return None


def summarise(path):
    raw = open(path, "rb").read()
    for enc in ("utf-16", "utf-8", "cp1252"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    txt = re.sub(r"<[^>]+>", "|", txt)
    txt = re.sub(r"\|+", "|", txt.replace("&nbsp;", " "))
    out = {}
    for label in ("Total Net Profit", "Profit Factor", "Sharpe Ratio", "Total Trades",
                  "Equity Drawdown Maximal", "Balance Drawdown Maximal", "Profit Trades (% of total)"):
        m = re.search(re.escape(label) + r":?\|\s*([^|]+)", txt)
        if m:
            out[label] = m.group(1).strip()
    return out


def main():
    info = export()
    input("\nExport done. Now CLOSE MetaTrader 5 completely, then press Enter to start the tester ...")
    today = dt.date.today().strftime("%Y.%m.%d")
    for name, start in (("full", "2025.01.01"), ("forward", "2026.08.01")):
        rep = run_tester(name, start, today, info)
        if rep:
            print(f"  MT5 report : {summarise(rep)}")
            print(f"  Python ref : {EXPECTED[name]}")
    print("\nDone. Push data/mt5_symbol_spec.json, data/mt5_btcusd_m1.csv.gz and results/mt5/ "
          "(or paste this summary into the chat).")


if __name__ == "__main__":
    main()
