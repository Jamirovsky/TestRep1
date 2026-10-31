import pandas as pd, numpy as np, sys
S=sys.argv[1]
a=pd.read_csv(f'{S}/dl/btc_hist.csv.gz'); b=pd.read_csv(f'{S}/dl/btc_latest.csv')
d=pd.concat([a,b]).drop_duplicates('timestamp').sort_values('timestamp')
d=d[d.timestamp>=pd.Timestamp('2017-06-01').timestamp()]
d.index=pd.to_datetime(d.timestamp,unit='s'); d=d.drop(columns='timestamp')
print(d.index[0], d.index[-1], len(d))
for tf,r in [('15m','15min'),('1h','1h'),('4h','4h'),('1d','1D')]:
    x=d.resample(r).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    x.to_pickle(f'{S}/data/BTCUSD_{tf}.pkl'); print(tf,len(x))
