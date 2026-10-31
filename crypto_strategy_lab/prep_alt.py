import pandas as pd, glob, sys
S = sys.argv[1]
for sym in ['ETHUSDT', 'SOLUSDT', 'XRPUSDT']:
    fs = sorted(glob.glob(f'{S}/dl2/raw_{sym}/*.csv'))
    parts = []
    for f in fs:
        x = pd.read_csv(f, usecols=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        parts.append(x)
    d = pd.concat(parts).drop_duplicates('timestamp').sort_values('timestamp')
    d.index = pd.to_datetime(d.timestamp, unit='ms'); d = d.drop(columns='timestamp').astype(float)
    gaps = (d.index.to_series().diff() > pd.Timedelta('10min')).sum()
    print(sym, d.index[0], d.index[-1], len(d), 'gaps>10min:', gaps, 'bad hl:', (d.high < d.low).sum())
    for tf, r in [('15m', '15min'), ('1h', '1h'), ('4h', '4h'), ('1d', '1D')]:
        x = d.resample(r).agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
        x.to_pickle(f'{S}/data/{sym[:3]}USD_{tf}.pkl')
