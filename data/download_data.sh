#!/usr/bin/env bash
# Descarrega velas de 1 minuto BTC/USD (Bitstamp, atualizadas diariamente) e converte para npz.
# Fonte: https://github.com/ff137/bitstamp-btcusd-minute-data
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data_raw
curl -sSL -o data_raw/btc_latest.csv https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/updates/btcusd_bitstamp_1min_latest.csv
python3 - <<'PY'
import pandas as pd, numpy as np
df = pd.read_csv('data_raw/btc_latest.csv')
np.savez_compressed('data/btc_1m.npz', ts=df.timestamp.values.astype(np.int64), o=df.open.values,
                    h=df.high.values, l=df.low.values, c=df.close.values, v=df.volume.values)
print('velas:', len(df))
PY
