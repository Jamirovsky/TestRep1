"""Download Bitstamp BTC/USD 1-minute OHLC (a true USD market) into data/bitstamp_btcusd_1m.parquet.

    python scripts/download_bitstamp.py 2024-11-01 2026-11-19
"""
import sys, time, os, json, urllib.request
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "bitstamp_btcusd_1m.parquet")
URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60&limit=1000&start={}"


def fetch(start):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(URL.format(start), timeout=30) as r:
                return json.load(r)["data"]["ohlc"]
        except Exception as e:  # noqa
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed at {start}")


def main(a, b, out=OUT):
    t0 = int(pd.Timestamp(a, tz="UTC").timestamp())
    t1 = int(pd.Timestamp(b, tz="UTC").timestamp())
    rows, t = [], t0
    while t < t1:
        chunk = fetch(t)
        if not chunk:
            t += 1000 * 60
            continue
        rows.extend(chunk)
        last = int(chunk[-1]["timestamp"])
        t = max(t + 60, last + 60)
        if len(rows) % 50000 < 1000:
            print(pd.Timestamp(last, unit="s"), len(rows), flush=True)
        time.sleep(0.12)
    df = pd.DataFrame(rows).astype({"timestamp": "int64"}).drop_duplicates("timestamp")
    df.index = pd.to_datetime(df.pop("timestamp"), unit="s", utc=True)
    df.index.name = "time"
    df = df[["open", "high", "low", "close", "volume"]].astype("float64").sort_index()
    df = df[df.index < pd.Timestamp(b, tz="UTC")]
    df.to_parquet(out)
    print("saved", out, df.shape, df.index[0], df.index[-1])


if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) >= 3 else ["2024-11-01", "2026-11-19"]
    main(*args)
