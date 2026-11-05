# Relatório final: estratégias de scalping BTCUSD (conta de 100 €, ICTrading)

> Secção 000 = ronda 5 (Chart Fanatics / World Cup). Secção 00 = ronda 4 (validação 2018–21). Secção 0 = ronda 3 (A2). Secções 1–7 = relatório original de 02/11/2026.

**Data:** 2 de novembro de 2026 · **Período analisado:** 07/01/2025 a 01/11/2026 (velas de 1 minuto)

## 000. Atualização: ronda 5 (05/11/2026), ideias do Chart Fanatics e do World Cup Trading Championship

**Fontes e limites**
* O YouTube e os sites do Chart Fanatics estão bloqueados na rede deste ambiente. As regras vêm de pesquisa web: páginas de estratégia do Chart Fanatics indexadas, resumos da Tradezella/TradingView e artigos da Unger Academy e da EBC sobre Larry Williams.
* Não há dados de order flow nem de footprint, por isso essas partes foram aproximadas com velas OHLC de 1 minuto.

**8 estratégias adaptadas** (`scalping/strategies_yt.py`)

| Fonte | Estratégia | Adaptação a BTCUSD |
|---|---|---|
| Chart Fanatics: Kyle Ng (Jadecap) | Liquidity raid | Varrimento da máx/mín do dia anterior e das sessões asiática e de Londres, seguido de mudança de estrutura; stop no varrimento |
| Chart Fanatics: Josh | IFVG | Varrimento de mínimos/máximos recentes seguido de fecho através de um fair value gap contrário |
| Chart Fanatics: Fabio Valentini | Auction market | Reversão: sai das bandas σ do VWAP e volta para dentro, alvo no VWAP. Tendência: pullback ao VWAP |
| Chart Fanatics: Okala | 80/20 | Rejeição de níveis "redondos" (grelha 1-2-5 com ~0,1–1% do preço) |
| WCTC: Larry Williams (1987) | Volatility breakout | Abertura do dia UTC ± k × amplitude do dia anterior |
| WCTC: Larry Williams | "Oops!" | Fura a mín/máx do dia anterior e volta para dentro |
| WCTC: Andrea Unger (4× campeão) | Rompimento do dia anterior | Primeiro rompimento do dia, com filtro ADX |
| WCTC: Andrea Unger | "Compressed candle" | Rompimento depois de um dia de amplitude < comp × média de 10 dias |

**1) Parâmetros tal como publicados, sem otimização** (2018–2026, 100 €, 0,01 lote, spread 0,025%):

| Estratégia | Trades | WR | PF | Lucro | Perdas seguidas |
|---|---|---|---|---|---|
| Liquidity raid | 8.117 | 35% | 0,84 | −1.553 € | 19 |
| IFVG | 9.004 | 37% | 0,87 | −1.440 € | 17 |
| Fabio (reversão ao VWAP) | 7.249 | 39% | 0,79 | −1.001 € | 14 |
| 80/20 níveis redondos | 115.803 | 32% | 0,70 | −11.369 € | 43 |
| Williams volatility breakout | 2.329 | 50% | 1,07 | +321 € | 11 |
| Williams "Oops!" | 2.463 | 43% | 0,99 | −40 € | 14 |
| Unger rompimento | 1.068 | 42% | 1,03 | +59 € | 9 |
| Unger "compressed" | 671 | 43% | 1,19 | +129 € | 10 |

Nesta versão, os modelos Chart Fanatics perdem dinheiro em BTC CFD. Dependem de leitura discricionária de order flow e de stops muito apertados, e o spread come o edge. Os modelos dos campeões ficam à volta de zero ou ligeiramente positivos, mas com perfil de tendência (WR ~45% e até 14 perdas seguidas). **Nenhum cumpre os pressupostos tal como publicado.**

**2) Loop de adaptação:** 125 mil variantes, das 12:29 às 15:30 UTC, otimizadas só com 2022–26 e com as mesmas exigências de robustez da ronda 4. A regra pré-declarada está em `results/REGRA_RONDA5.md`.

**3) Juiz pré-declarado 2018–2021** (para estas estratégias, nunca usado em nenhuma escolha):

| Desafiante (melhor robusto 2022–26) | PF 2022–26 | Trades 18–21 | WR 18–21 | PF 18–21 | Lucro 18–21 | DD 18–21 | Perdas seguidas | Passa? |
|---|---|---|---|---|---|---|---|---|
| Liquidity raid | 2,01 | 67 | 73% | 1,46 | +12,2 € | 10,5% | 2 | ✘ (< 100 trades) |
| IFVG | 1,47 | 71 | 82% | 2,21 | +20,7 € | 6,9% | 3 | ✘ |
| Fabio | 1,74 | 142 | 58% | 0,80 | −11,9 € | 25,4% | 4 | ✘ |
| 80/20 | nenhum setup cumpre os pressupostos em 2022–26 | | | | | | | ✘ |
| Williams VB | 1,59 | 158 | 71% | 1,22 | +28,3 € | 28,1% | 3 | ✘ |
| Williams "Oops!" | 1,87 | 126 | 56% | 0,55 | −42,5 € | 50,1% | 5 | ✘ |
| **Unger rompimento** | **1,73** | **105** | **86%** | **2,07** | **+35,5 €** | **11,4%** | **2** | **✔** |
| **Unger "compressed"** | 1,09 | 105 | 87% | 3,38 | +27,2 € | 3,4% | 2 | **✔** |

**Decisão da regra:**
* **A A2 continua a ser a estratégia principal.** Nenhuma estratégia nova bate a A2 nos dois períodos. A "Unger rompimento" bate em 2018–21 (2,07 contra 1,96) mas não em 2022–26 (1,73 contra 1,83).
* **A "Unger rompimento" (U) é a segunda estratégia validada.** Cumpre todos os pressupostos em ambos os períodos. Regras:
  * M10, primeiro fecho do dia acima da máxima (abaixo da mínima) do dia UTC anterior.
  * ADX(14) ≥ 30, a favor da EMA(200), só na sessão europeia (07–13 UTC).
  * SL 5×ATR, TP 1×ATR, breakeven a 80% do TP, fecho ao fim de 480 min, pausa de 4 h após 2 perdas.

**4) Diversificação: A2 + U em paralelo** (correlação mensal 0,13; quase nunca estão abertas ao mesmo tempo):

| 2018–2026 | Trades | WR | PF | Lucro | DD máx | Perdas seguidas |
|---|---|---|---|---|---|---|
| A2 | 1.025 | 87,4% | 1,87 | +225 € | 12,3% | 2 |
| U | 237 | 86,1% | 1,86 | +84 € | 11,4% | 2 |
| **A2 + U** | 1.262 | 87,2% | 1,87 | **+309 €** | **9,5%** | **3** ✘ |

Em conjunto há mais lucro e menos DD, mas a sequência combinada chega a **3 perdas seguidas**, o que quebra o teu critério. Se o limite das 2 perdas seguidas for absoluto, usa só a A2. Se aceitares 3 perdas seguidas em troca de mais lucro e menor DD, corre A2 + U.

**EA:** novo setup `SETUP_UNGER_PDBO` e ficheiro `mt5/sets/U_UNGER_PDBO_M10.set`, com magic number diferente para poder correr ao lado da A2.

## 00. Atualização: ronda 4 (03/11/2026), tentativa de melhorar a A2 e validação independente

**O que foi feito**
* Loop de **1,67 milhões de variantes** da A2 (21:07 a 23:15 UTC).
* Novas opções testadas: entrada por **ordem limite**, **TP mínimo** em % do preço, filtro HTF, timeframes de 5 a 30 min.
* O score passou a exigir **robustez a 1 minuto de atraso e a spread de 0,035%**, os dois pontos fracos da A2.
* **Juiz novo:** 01/01/2018 a 31/12/2021. São 4 anos **nunca usados em nenhuma ronda**: mercado em baixa de 2018, crash da COVID em 2020, subida de 2021. Regra pré-declarada em `results/REGRA_RONDA4.md`.

**Decisão da regra: mantém-se a A2.** O desafiante (RSI(3) < 8, EMA 200, SL 1.600 $, TP 125–150 $, ordem limite, sessão europeia) melhorava muito em 2022–26, mas **falhou no juiz**:

| 2018–2021 (nunca visto) | Trades | WR | PF | Lucro | DD máx | Perdas seguidas |
|---|---|---|---|---|---|---|
| **A2** | **391** | **84,9%** | **1,96** | **+69,9 €** | **10,3%** | **2** ✔ |
| Desafiante ronda 4 | 172 | 77,9% | 0,99 | −1,1 € | 27,5% | 4 ✘ |

**A conclusão mais importante desta ronda: a A2 passou num teste totalmente independente.** Foi definida só com dados de 2022–26. Em 2018–21, um período que nunca tinha sido usado, cumpre **todos** os pressupostos e **todos os anos são positivos**: 2018 +14,9 €, 2019 +2,3 €, 2020 +5,9 €, 2021 +46,7 €. Este é o resultado mais forte de todo o estudo.

**A2 em 9 anos** (2018 a 2026, conta de 100 €, 0,01 lote, spread de 0,025%):
* 1.025 trades, WR 87,4%, PF 1,87, **+225 €**, DD 12,3%¹, **máximo 2 perdas seguidas**.
* Todos os 9 anos foram positivos.

¹ O DD conta a partir de 2018. A partir de 2022 o DD máximo é de 18,5%, porque o saldo inicial é mais baixo.

**Monte Carlo** (próximos 100 trades, com base em 2018–26):
* P(lucro) = 93%
* P(DD > 20%) = 7%
* P(≥ 3 perdas seguidas) = 16%
* **P(cumprir todos os pressupostos) = 77%**

**Os pontos fracos da A2 confirmam-se em 2018–21:**

| Cenário 2018–21 | PF | Lucro | DD | Perdas seguidas |
|---|---|---|---|---|
| Base (spread 0,025%) | 1,96 | +69,9 € | 10,3% | 2 |
| Spread 0,035% | 1,90 | +66,1 € | 10,3% | 2 |
| **Atraso de 1 minuto** | **1,22** | +23,7 € | **29,8%** | 3 |
| Spread fixo 25 $ (irrealista em 2018: 0,3–0,6% do preço) | 1,27 | +25,3 € | 19,8% | 7 |

O ponto crítico continua a ser a **velocidade de execução**: o EA tem de entrar logo no primeiro tick da vela nova. A ordem limite não resolveu este problema de forma robusta.

**Recomendação (sem alterações):**
* **A2** é a estratégia do EA (valores por defeito / `mt5/sets/A2_RSI_TENDENCIA_SOMBRA_M15.set`).
* Antes de dinheiro real, fazer demo durante 100 trades, verificar o spread real e manter o VPS/terminal perto do servidor da ICTrading para minimizar a latência.

Gráfico: `report/equity_A2_2018_2026.png` · trades: `report/trades_A2_2018_2026.csv`.

## 0. Atualização: ronda 3 (03/11/2026), melhoria da estratégia A

**O que foi feito**
* Loop de melhoria só na família RSI: **1,51 milhões de variantes** (23:45 a 01:07 UTC; o contentor reiniciou antes do prazo das 01:50).
* Novas opções testadas: filtro de tendência em 1h/4h, timeframes de 20 e 30 min, grelhas mais finas de SL/TP/breakeven.
* Novo juiz independente: **15/01/2022 a 06/01/2025**, com **velas que a estratégia A nunca viu**. Inclui o mercado em baixa de 2022 e o mercado em alta de 2023–24.
* Spread proporcional ao preço (0,025% ≈ 25 $ a 100 k$). Um spread fixo de 25 $ com o BTC a 20 k$ não seria realista; os resultados com spread fixo também estão abaixo.

**Regra pré-declarada** (`results/REGRA_RONDA3.md`, escrita antes de ver resultados)
* Desafiante = melhor score robusto do backtest. Resultou outra vez num "RSI contra a tendência".
* Nos dados nunca vistos de 2022–24 o desafiante **perdeu 105%** (destruiria a conta). **A regra rejeitou-o.**

**Teste exploratório** (não pré-declarado; foi assim que se encontrou a A2)
* Restringi a pesquisa às variantes que mantêm a lógica da A (a favor da tendência) e ordenei-as **só pelo backtest**.
* Avaliei as 3 primeiras, com e sem "modo sombra", no período completo de 2022 a 2026.
* Como esta escolha usou o período 2022–26, já não há nenhum período totalmente "virgem". **A prova final continua a ser a demo.**

### Estratégia A2 (nova versão recomendada): RSI extremo a favor da tendência + modo sombra, M15

As regras são as da A, com estas alterações: **SL 6,0×ATR** (antes 5,0), **TP 0,35×ATR** (antes 0,5), **breakeven a 80% do TP** (antes 70%), **fecho por tempo de 180 min** (antes 120) e **modo sombra** ativo. No modo sombra, depois de 2 perdas seguidas os trades passam a virtuais até um trade virtual ganhar.

Conta de 100 €, 0,01 lote, spread proporcional de 0,025%:

| Período | Estratégia | Trades | WR | WR estrito¹ | PF | Lucro | DD máx | Perdas seguidas |
|---|---|---|---|---|---|---|---|---|
| 2022–24 (nunca visto) | **A2** | 363 | 88,2% | 79,1% | **1,55** | **+53,7 €** | 18,5% | **2** |
| | A | 365 | 81,4% | 61,6% | 1,28 | +35,8 € | 15,6% | 4 ✘ |
| Backtest jan/25–abr/26 | **A2** | 194 | 91,2% | 81,4% | 2,77 | +98,8 € | 11,4% | 2 |
| | A | 190 | 88,9% | 64,7% | 2,16 | +89,6 € | 12,3% | 1 |
| Forward mai–out/26 | **A2** | 74 | 86,5% | 73,0% | **1,03** | **+1,1 €** | 13,9% | 2 |
| | A | 72 | 84,7% | 58,3% | 1,86 | +16,6 € | 5,8% | 1 |
| **Total 2022–26** | **A2** | **631** | **88,9%** | **79,1%** | **1,83** | **+153,6 €** | **18,5%** | **2** ✔ |
| | A | 627 | 84,1% | 62,2% | 1,63 | +142,0 € | 15,6% | 4 ✘ |

¹ Contando os breakevens como perdas.

**A2 cumpre todos os pressupostos em quase 5 anos de dados**: 631 trades, WR acima de 57%, PF acima de 1,01, DD até 20% e no máximo 2 perdas seguidas. Todos os anos foram positivos: 2022 +11,3 €, 2023 +6,5 €, 2024 +36,0 €, 2025 +72,5 €, 2026 +27,4 €.

**Pontos fracos da A2 (ler antes de usar)**
1. **Os últimos 6 meses ficaram praticamente em zero** (PF 1,03, +1,1 €). A A original foi melhor nesse período.
2. **É muito sensível à execução.** O TP mediano é de apenas 66 $. Se entrar 1 minuto depois do sinal, o PF cai para 1,11, com DD de 32% e 4 perdas seguidas. O EA entra no primeiro tick da vela nova (segundos), mas qualquer atraso ou requote prejudica.
3. **Depende do spread:**

   | Spread | PF | Lucro | DD | Perdas seguidas |
   |---|---|---|---|---|
   | 0,020% | 1,88 | +159,6 € | 18,2% | 3 |
   | 0,025% | 1,83 | +153,6 € | 18,5% | 2 |
   | 0,035% | 1,58 | +119,2 € | 16,8% | 4 |
   | 0,050% | 1,24 | +60,1 € | 21,5% | 4 |
   | 25 $ fixo | 1,61 | +122,8 € | 31,9% | 4 |

   Com spreads acima de ~0,03% (≈ 25–30 $ ao preço atual), o limite de 2 perdas seguidas deixa de se cumprir.
4. **Vizinhança de parâmetros:** 78% dos vizinhos têm PF > 1 (mediana 1,70). O filtro de tendência ("a favor"), o timeframe M15 e a exclusão da sessão asiática são essenciais; sem eles a estratégia perde dinheiro.
5. **Monte Carlo (100 trades):**
   * P(lucro) = 93%
   * P(DD > 20%) = 9%
   * P(≥ 3 perdas seguidas) = 12%
   * **P(cumprir todos os pressupostos) = 80%** (era 73% na A)

**Recomendação:**
* O EA vem agora com a **A2 por defeito** (`mt5/sets/A2_RSI_TENDENCIA_SOMBRA_M15.set`). A `A_RSI_TENDENCIA_M15.set` continua disponível.
* Em demo, correr **A2 e A em paralelo** (magic numbers diferentes), durante pelo menos 100 trades, antes de usar dinheiro real.

Gráfico: `report/equity_A2_2022_2026.png` · trades: `report/trades_A2_2022_2026.csv`.

## 1. Resumo

| | |
|---|---|
| Setups gerados e testados no loop | **≈ 1,97 milhões** (ronda 1: 81 mil; ronda 2: 1,89 milhões), 14 famílias, timeframes de 1m a 15m |
| Setups que cumprem todos os pressupostos no backtest | 652 dos 840 finalistas |
| Famílias cujo melhor setup se manteve lucrativo no forward test | **2 em 14** (+ a estratégia A, encontrada na ronda 1) |
| **Estratégia recomendada** | **A: RSI extremo a favor da tendência, M15** |

**Estratégia A, conta de 100 €, 0,01 lote, spread de 25 $:**

| Período | Trades | Win rate | Profit factor | Lucro | Max DD | Perdas seguidas máx. |
|---|---|---|---|---|---|---|
| Backtest (jan/25 a abr/26) | 187 | 87,7% | 2,07 | +83,47 € | 12,8% | 2 |
| **Forward test (mai/26 a out/26)** | **69** | **81,2%** | **1,76** | **+15,31 €** | **5,9%** | **1** |
| Total | **256** | **85,9%** | **2,01** | **+98,78 €** | **12,8%** | **2** |

No conjunto, a estratégia A cumpre todos os pressupostos: mais de 100 trades, win rate acima de 57%, PF acima de 1,01, DD até 20%, no máximo 2 perdas seguidas e SL/TP editáveis.
Mesmo contando os trades de breakeven como perdas, o win rate continua nos 64%.

### O que deve saber antes de usar
1. **O loop produziu sobretudo overfitting.** Fixei uma regra antes de olhar para o forward (escolher o maior "score robusto" do backtest). O setup que essa regra escolheu ganhou +239% no backtest e **perdeu 37% no forward test**. Em 14 famílias, só 2 mantiveram lucro no forward. Um backtest bonito, por si só, não significa nada.
2. **A estratégia A foi escolhida depois de ver o forward test.** Foi a mais estável entre as 3 sobreviventes: 86% dos setups vizinhos também lucram no forward. Mesmo assim, o forward já não é uma prova independente. A prova que falta é **demo ou conta real com 100 trades novos**.
3. **O edge está a enfraquecer.** Os últimos 3 meses (ago/set/out 2026) fecharam em −0,06 €, −1,04 € e −4,56 €.
4. **"Menos de 3 perdas seguidas" não se garante.** No Monte Carlo (100 trades), a probabilidade de aparecerem 3 perdas seguidas é de **21%** (42% se usarmos só a distribuição do forward). A probabilidade de cumprir **todos** os pressupostos nos próximos 100 trades é de **57 a 73%**.
5. **Perfil de risco: muitos ganhos pequenos e poucas perdas grandes.** O TP mediano é de 121 $ (≈1,0 €) e o SL mediano de 1.208 $ (≈10,4 €). Três stops em 256 trades custaram 31 €. A maior parte das perdas vem do fecho por tempo (26 trades, −64 €).
6. **Os dados não são da ICTrading.** A rede deste ambiente bloqueia a ICTrading e os exchanges. Usei BTC/USD spot da Bitstamp em 1 minuto. **Confirme no Strategy Tester do MT5 com os ticks reais da ICTrading** (modo "Every tick based on real ticks").

## 2. Pressupostos e método

* **Conta:** 100 € (= 116 $ com EUR/USD 1,16), **0,01 lote** (= 0,01 BTC; 1 $ de movimento = 0,01 $).
* **Custos:** spread de **25 $** por BTC, testado de 10 a 75 $; slippage de 5 $ nos stops; swap de 50 $/BTC/noite em compras e 20 $ em vendas, com rollover às 22:00 UTC.
* **Execução igual ao MT5:** compra no Ask e venda no Bid. SL e TP são distâncias a partir do preço de entrada. Se SL e TP caírem na mesma vela de 1m, assume-se que o **SL foi primeiro** (conservador). O sinal é calculado no fecho da vela e a entrada é feita no minuto seguinte, sem look-ahead.
* **Divisão dos dados:**
  * **Backtest** (07/01/2025 a 30/04/2026): única parte usada para otimizar, dividida em 4 blocos de 4 meses para medir consistência.
  * **Forward test** (01/05/2026 a 01/11/2026): 6 meses nunca usados pelo loop de otimização.
* **Loop de otimização** (`scalping/search.py`):
  * Gera setups aleatórios (família, timeframe, parâmetros, SL/TP, filtros) e muta os melhores de cada família, até à hora limite.
  * **Score** = 0,5 × retorno médio dos 4 blocos + 1,0 × retorno do pior bloco, menos penalizações por cada pressuposto não cumprido.
  * Na primeira passagem o loop favoreceu setups "só short", que exploravam a queda do BTC. Por isso, a partir daí, **só se aceitam setups simétricos** (compra e venda).
* **Seleção robusta** (`scalping/robust_rank.py`): para os 60 melhores de cada família avaliam-se todos os vizinhos (cada parâmetro ±1 passo). Score robusto = 0,4 × próprio + 0,6 × mediana dos vizinhos.

## 3. Resultados por família (melhor setup de cada uma pelo score robusto do backtest)

Retorno em % sobre os 100 €, com 0,01 lote. "✔" quer dizer que cumpre WR > 57%, PF > 1,01, DD ≤ 20% e perdas seguidas ≤ 2 nesse período (no forward não se exige o mínimo de 100 trades).

| Família | TF | BT trades | BT WR | BT PF | BT ret. | BT DD | BT ✔ | FW trades | FW WR | FW PF | FW ret. | FW DD | FW perdas seg. | FW ✔ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI extremo (contra tendência)¹ | M15 | 372 | 85,2% | 1,89 | +238,7% | 13,7% | ✔ | 176 | 76,7% | 0,77 | **−37,0%** | 52,6% | 3 | ✘ |
| MACD cruzamento | M15 | 130 | 70,0% | 2,08 | +202,5% | 12,6% | ✔ | 44 | 63,6% | 1,25 | **+16,6%** | 12,5% | 2 | ✔ |
| Z-score reversão | M5 | 198 | 83,3% | 2,03 | +212,8% | 13,5% | ✔ | 41 | 68,3% | 0,98 | −1,1% | 25,3% | 3 | ✘ |
| Pin bar + Bollinger | M1 | 141 | 88,7% | 2,75 | +152,5% | 16,2% | ✔ | 55 | 70,9% | 1,08 | **+5,1%** | 17,6% | 2 | ✔ |
| Donchian fade | M15 | 254 | 80,3% | 1,78 | +181,3% | 10,8% | ✔ | 99 | 70,7% | 0,83 | −17,9% | 29,2% | 3 | ✘ |
| Estocástico cruzamento | M10 | 129 | 76,7% | 2,08 | +179,3% | 20,3% | ✘ | 87 | 66,7% | 0,83 | −25,7% | 46,1% | 3 | ✘ |
| EMA pullback | M5 | 162 | 87,0% | 2,25 | +155,8% | 8,3% | ✔ | 39 | 51,3% | 0,47 | −40,2% | 47,8% | 4 | ✘ |
| Bollinger + RSI | M15 | 138 | 89,1% | 2,53 | +136,8% | 14,8% | ✔ | 78 | 73,1% | 0,99 | −0,8% | 19,3% | 3 | ✘ |
| Donchian breakout | M10 | 144 | 74,3% | 1,82 | +144,2% | 13,4% | ✔ | 53 | 58,5% | 0,66 | −27,2% | 37,7% | 4 | ✘ |
| Keltner reentrada | M5 | 104 | 76,9% | 2,60 | +201,9% | 23,4% | ✘ | 28 | 60,7% | 0,90 | −4,8% | 26,7% | 2 | ✘ |
| N velas seguidas (fade) | M15 | 244 | 91,4% | 2,29 | +130,6% | 8,0% | ✔ | 132 | 86,4% | 0,46 | **−86,6%** | 93,1% | 2 | ✘ |
| VWAP reversão | M15 | 108 | 87,0% | 2,45 | +99,8% | 19,5% | ✔ | 44 | 81,8% | 0,75 | −13,1% | 28,6% | 2 | ✘ |
| Opening Range Breakout | M3 | 134 | 78,4% | 1,53 | +70,3% | 9,9% | ✔ | 40 | 70,0% | 0,72 | −15,0% | 18,4% | 1 | ✘ |
| Inside bar breakout | M10 | 95 | 80,0% | 2,57 | +70,0% | 4,2% | ✘ | 44 | 61,4% | 0,74 | −11,7% | 22,7% | 4 | ✘ |
| **A: RSI extremo (a favor da tendência)**² | **M15** | **187** | **87,7%** | **2,07** | **+83,5%** | **12,8%** | **✔** | **69** | **81,2%** | **1,76** | **+15,3%** | **5,9%** | **1** | **✔** |

¹ Campeão da regra pré-declarada. ² Melhor setup da família RSI na ronda 1 (grelha mais grossa).

Curvas de capital: `report/equity_<FAMILIA>.png`. Lista de trades: `report/trades_<FAMILIA>.csv`.

## 4. Os 3 candidatos que sobreviveram ao forward test

| | A: RSI tendência M15 | B: MACD Ásia M15 | C: Pin bar M1 |
|---|---|---|---|
| Total trades / WR / PF | 256 / 85,9% / 2,01 | 174 / 68,4% / 1,86 | 196 / 83,7% / 2,07 |
| Lucro total / Max DD | +98,8 € / 12,8% | +219,1 € / 12,6% | +157,6 € / 16,2% |
| Forward: lucro / WR / PF | +15,3 € / 81,2% / 1,76 | +16,6 € / 63,6% / 1,25 | +5,1 € / 70,9% / 1,08 |
| **WR estrito** (breakeven = perda) | **64,1%** ✔ | 46,6% ✘ | 46,9% ✘ |
| Perdas seguidas (estrito) | 4 | 7 | 9 |
| Vizinhos lucrativos no forward | **86%** | 68% | 56% |
| Monte Carlo: P(todos os pressupostos em 100 trades) | **73%** | 9% | 58% |
| Monte Carlo: P(DD > 20%) | 10% | 37% | 23% |
| Monte Carlo: P(≥ 3 perdas seguidas) | 21% | 90% | 31% |

**A é a recomendada.** Os bons números de B e C dependem de saídas em breakeven contadas como "ganhos" de 0,01 €. B só opera na sessão asiática e perde muito dinheiro se o horário mudar uma hora.

## 5. Estratégia A em detalhe

### Regras (todas editáveis no EA)

| Parâmetro | Valor |
|---|---|
| Timeframe | **M15** |
| Sinal de compra | RSI(4) < 15 **e** fecho > EMA(100) (sobrevenda dentro de uma tendência de alta) |
| Sinal de venda | RSI(4) > 85 **e** fecho < EMA(100) |
| Entrada | Abertura da vela seguinte, a mercado, 0,01 lote |
| **Stop Loss** | **5,0 × ATR(14)** (mediana de 1.208 $; intervalo de 314 a 4.441 $). Em USD fixo, o equivalente é ≈ 1.200 $ |
| **Take Profit** | **0,5 × ATR(14)** (mediana de 121 $; intervalo de 31 a 444 $). Em USD fixo, o equivalente é ≈ 120 $ |
| Breakeven | Quando o lucro chega a 70% do TP, o SL passa para a entrada + 1 $ |
| Fecho por tempo | 120 minutos |
| Filtro de volatilidade | ATR(14) ≥ 0,5 × média do ATR das últimas 100 velas |
| Horário | 07:00 a 24:00 UTC (sem sessão asiática), só de segunda a sexta |
| Duração dos trades | Mediana de 15 min, média de 33 min, máximo de 120 min |
| Frequência | ≈ 12 trades por mês (≈ 0,4 por dia) |

### Consistência

Os 4 blocos do backtest foram todos positivos: +18,5%, +21,1%, +25,4% e +18,5%. Compras e vendas estão equilibradas: 128 compras (+28,4 €, WR 85%) e 128 vendas (+70,4 €, WR 87%).

| Mês | Trades | Lucro € | WR | | Mês | Trades | Lucro € | WR |
|---|---|---|---|---|---|---|---|---|
| 2025-01 | 11 | +0,67 | 91% | | 2025-12 | 18 | +3,60 | 94% |
| 2025-02 | 12 | +13,28 | 83% | | 2026-01 | 11 | +6,85 | 91% |
| 2025-03 | 9 | +6,42 | 78% | | 2026-02 | 18 | −0,38 | 83% |
| 2025-04 | 9 | −1,90 | 78% | | 2026-03 | 16 | +11,05 | 94% |
| 2025-05 | 11 | +11,78 | 91% | | 2026-04 | 10 | +0,95 | 80% |
| 2025-06 | 9 | +8,46 | 89% | | *forward* 2026-05 | 15 | +8,53 | 87% |
| 2025-07 | 11 | +7,35 | 82% | | 2026-06 | 16 | +5,22 | 81% |
| 2025-08 | 9 | −6,48 | 89% | | 2026-07 | 11 | +7,22 | 100% |
| 2025-09 | 9 | −6,96 | 78% | | 2026-08 | 10 | −0,06 | 70% |
| 2025-10 | 15 | +19,03 | 100% | | 2026-09 | 6 | −1,04 | 83% |
| 2025-11 | 9 | +9,75 | 89% | | 2026-10 | 11 | −4,56 | 64% |

### Sensibilidade ao spread

| Spread | PF backtest | Ret. backtest | PF forward | Ret. forward | WR forward |
|---|---|---|---|---|---|
| 10 $ | 2,67 | +104,6% | 2,35 | +22,6% | 87,7% |
| 15 $ | 2,16 | +88,8% | 1,90 | +17,1% | 84,5% |
| **25 $ (base)** | **2,07** | **+83,5%** | **1,76** | **+15,3%** | **81,2%** |
| 35 $ | 1,50 | +53,6% | 1,69 | +14,6% | 80,9% |
| 50 $ | 1,16 | +20,6% | 1,53 | +12,2% | 75,0% |
| 75 $ | 0,87 | −20,1% | 1,08 | +2,4% | 70,3% |

Acima de 50 $ de spread, a estratégia deixa de valer a pena. O EA não entra se o spread for superior a 60 $ (`InpMaxSpreadUSD`).

### Atraso na execução

| Atraso | PF backtest | Ret. backtest | PF forward | Ret. forward |
|---|---|---|---|---|
| 0 min | 2,07 | +83,5% | 1,76 | +15,3% |
| 1 min | 1,52 | +55,6% | 1,58 | +14,3% |
| 2 min | 1,31 | +37,0% | 1,50 | +12,7% |
| 5 min | 1,34 | +41,0% | 1,42 | +11,1% |

### Tamanho do lote (conta de 100 €, período total)

| Lote | Lucro | Max DD |
|---|---|---|
| **0,01** | **+98,8 €** | **12,8%** |
| 0,02 | +197,6 € | 19,3% (no limite) |
| 0,03 | +296,3 € | 25,1% ✘ |

**Recomendação: 0,01 lote.** Com 0,02 lote o DD histórico fica a 0,7 pontos do limite de 20%.

## 6. Como usar (MetaTrader 5, ICTrading)

1. Copie `mt5/BTCUSD_Scalper_Lab.mq5` para `MQL5/Experts/`, compile no MetaEditor e anexe ao gráfico **BTCUSD**, em qualquer timeframe. O EA usa o timeframe do input `InpTF`.
2. Os valores por defeito correspondem à **estratégia A**. Os ficheiros `mt5/sets/*.set` carregam A, B ou C (Inputs → Load).
3. **SL e TP são editáveis:** `InpSLTPMode` (ATR ou USD), `InpSL_ATR`/`InpTP_ATR`, `InpSL_USD`/`InpTP_USD`, `InpBEFrac` e `InpMaxHoldMin`.
4. Proteções:
   * `InpMaxDDPct = 20`: o EA para quando o DD da conta chega a 20%.
   * `InpGuard`: pausa, ou "modo sombra" após N perdas seguidas. No modo sombra, os trades passam a virtuais até um trade virtual ganhar.
   * `InpMaxSpreadUSD`: não entra se o spread for superior a este valor.
5. **Antes de usar dinheiro real:**
   * Faça um backtest no Strategy Tester com "Every tick based on real ticks" nos dados da ICTrading.
   * Confirme na especificação do símbolo o spread médio, o swap, o lote mínimo e a alavancagem do BTCUSD.
   * Corra o EA **em demo até completar 100 trades** (≈ 2 meses).
   * Só passe a real se em demo o WR for superior a 57%, o PF superior a 1,01 e o DD inferior a 20%.
6. O EA não foi compilado neste ambiente, porque não há MetaEditor disponível. Se o compilador apontar algum erro, é provável que seja trivial de corrigir.

## 7. Limitações

* Dados Bitstamp spot em vez do feed da ICTrading. O volume no MT5 é volume de ticks, o que afeta só o setup VWAP.
* Spread e swap estimados, não medidos na conta. A ICTrading não estava acessível a partir deste ambiente.
* Não foi possível analisar YouTube nem sites de trading diretamente, porque a rede está bloqueada. As famílias de setups são as clássicas do scalping (RSI-2 de Connors, Bollinger/RSI, VWAP, ORB, Donchian, Keltner, pin bar, etc.), com variações geradas pelo loop.
* O forward test não substitui uma demo, e a estratégia A foi escolhida depois de o ver (ver ponto 1.2).
* **Nenhuma estratégia garante lucro real.** Trading alavancado pode levar à perda total do capital.
