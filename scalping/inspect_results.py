import json, sys, pandas as pd
def load(path):
    rows=[json.loads(l) for l in open(path)]
    out=[]
    for r in rows:
        d={'score':r['score_bt'], **r['params']}
        for s in ('backtest','forward'):
            for k in ('trades','win_rate','profit_factor','max_dd_pct','max_consec_losses','ret_pct'):
                d[s[:2]+'_'+k[:6]]=r[s][k]
        d['chunk_rets']=[round(c['ret_pct'],1) for c in r['chunks']]
        out.append(d)
    return pd.DataFrame(out).sort_values('score',ascending=False)
if __name__=='__main__':
    df=load(sys.argv[1]); n=int(sys.argv[2]) if len(sys.argv)>2 else 20
    pd.set_option('display.width',300); pd.set_option('display.max_columns',80); pd.set_option('display.max_colwidth',40)
    cols=['score','family','tf','sl_mode','sl_usd','tp_usd','sl_atr','tp_atr','max_hold','be_frac','guard_mode','hours','trend','side','chunk_rets']+[c for c in df.columns if c[:3] in ('ba_','fo_')]
    cols=[c for c in cols if c in df.columns]
    print(df[cols].head(n).to_string())
    print(df.groupby('family').score.max().sort_values())
