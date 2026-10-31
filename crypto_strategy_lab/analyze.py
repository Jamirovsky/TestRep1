import sys, json, pandas as pd
from engine import S
tags = sys.argv[1].split(',')
d = pd.concat([pd.read_csv(f'{S}/res_{t}.csv').assign(tag=t) for t in tags], ignore_index=True)
d = d.drop_duplicates(['strat', 'tf', 'params'])
c = ['strat', 'tf', 'is_trades', 'is_winrate', 'is_pf', 'is_maxdd', 'h1_pf', 'h2_pf', 'oos_trades', 'oos_winrate', 'oos_pf', 'oos_maxdd', 'oos_ret']
p = d[d.is_pass]
q = p[p.rob > 1].sort_values('is_score', ascending=False)
print('total', len(d), 'IS pass:', len(p), ' robust:', len(q))
op = (q.oos_trades >= 30) & (q.oos_winrate >= 57) & (q.oos_pf >= 1.05) & (q.oos_maxdd < 20)
print('OOS pass among robust IS:', op.sum(), ' (>=100 total trades both)')
print(q.groupby(['strat', 'tf']).size().to_string())
pd.set_option('display.width', 250)
print(q[op][c].round(2).head(40).to_string())
q[op].to_csv(f'{S}/cand_{"_".join(tags)}.csv', index=False)
