# Laboratório de scalping BTCUSD (conta de 100 €, ICTrading)

Pesquisa automática de estratégias de scalping para BTCUSD com backtest e forward test,
otimizadas para os pressupostos do cliente:

| Pressuposto | Alvo |
|---|---|
| Nº de trades | > 100 |
| Win rate | > 57% |
| Profit factor | > 1,01 |
| Drawdown máximo | ≤ 20% |
| Perdas consecutivas | < 3 (máx. 2) |
| SL / TP | editáveis (USD ou múltiplos de ATR) |
| Conta | 100 € |

O relatório final está em [`report/RELATORIO.md`](report/RELATORIO.md).

## Estrutura

```
scalping/engine.py          motor de simulação (numba) em velas de 1 minuto, execução tipo MT5
scalping/strategies.py      14 famílias de setups + indicadores + espaço de parâmetros
scalping/backtest.py        pressupostos da conta/custos, divisão backtest / forward test, score
scalping/search.py          loop de geração/otimização com deadline (aleatório + mutação)
scalping/robust_rank.py     seleção robusta (planalto de parâmetros, só com dados de backtest)
scalping/robustness.py      Monte Carlo, vizinhança de parâmetros
scalping/final_analysis.py  gera tabelas, gráficos e JSON para o relatório
mt5/BTCUSD_Scalper_Lab.mq5  Expert Advisor MT5 com todos os setups e SL/TP editáveis
data/download_data.sh       descarrega os dados de 1 minuto
```

## Reproduzir

```bash
pip install numpy pandas numba matplotlib
./data/download_data.sh
python -m scalping.search --deadline "2026-11-02 13:15" --out results/search.jsonl
python -m scalping.robust_rank results/search.jsonl
python scalping/final_analysis.py results/search.jsonl
```

## Modelo de execução e custos (editáveis em `scalping/backtest.py`)

* Preços de dados = mid. Compra entra no Ask, sai no Bid (igual ao MT5); SL/TP são distâncias
  a partir do preço de execução.
* Spread base 25 USD por BTC (testado de 10 a 75 USD), slippage de 5 USD nos stops, swap
  ~50 USD/BTC/noite em compras e 20 USD em vendas.
* Se SL e TP são tocados na mesma vela de 1 minuto, assume-se que o SL foi primeiro (conservador).
* Sinal no fecho da vela do timeframe do setup, entrada na abertura do minuto seguinte.
* 0,01 lote = 0,01 BTC → 1 USD de movimento = 0,01 USD de lucro/prejuízo.

## Dados

As APIs da ICTrading não estão acessíveis a partir deste ambiente (nem os exchanges).
Usaram-se velas de 1 minuto BTC/USD da Bitstamp (spot), de 07/01/2025 a 02/11/2026
(956 mil velas), via [ff137/bitstamp-btcusd-minute-data](https://github.com/ff137/bitstamp-btcusd-minute-data).
O CFD BTCUSD da ICTrading segue o preço spot, mas o feed, o spread e o swap reais diferem:
**confirmar no Strategy Tester do MT5 com os ticks reais da ICTrading antes de operar.**

## Aviso

Resultados de backtest e forward test não garantem lucros futuros. Trading com
alavancagem pode levar à perda total da conta. Testar sempre primeiro em conta demo.
