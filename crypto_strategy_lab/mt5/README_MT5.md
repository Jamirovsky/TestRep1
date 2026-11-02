# Estratégias para MetaTrader 5

Dois Expert Advisors em MQL5, convertidos do motor de backtest em Python deste repositório:

| Ficheiro | Estratégia | Resultado walk-forward BTC 2021 → out/2026 |
|---|---|---|
| `SwingHighToSky_CCI_RSI.mq5` | Mean-reversion CCI + RSI (origem: freqtrade SwingHighToSky) | 120 trades · WR 71,7% · PF 1,62 · DD 8,9% |
| `ClucMay_DipBuyer.mq5` | Compra de quedas abaixo da banda de Bollinger (origem: freqtrade ClucMay72018) | 114 trades · WR 70,2% · PF 1,77 · DD 7,9% |

Os ficheiros `.set` trazem os intervalos de otimização, que são os mesmos do walk-forward.

> **Atenção:** os EAs não foram compilados nem testados no MT5, porque este ambiente não tem MetaEditor. Compile-os primeiro (F7 no MetaEditor) e faça um backtest antes de usar dinheiro real. Se houver algum erro de compilação, envie-me a mensagem.

## Instalação

1. No MT5: **Ficheiro → Abrir pasta de dados → MQL5 → Experts**. Copie para lá os dois `.mq5`.
2. Abra cada um no MetaEditor e compile (F7).
3. Copie os `.set` para **MQL5 → Profiles → Tester**.
4. Arraste o EA para um gráfico **BTCUSD M15** e ative o Algo Trading.

## Lógica

As duas estratégias decidem no fecho de cada vela M15 e enviam a ordem a mercado logo na abertura da vela seguinte, como no backtest. Cada EA tem uma posição de cada vez por símbolo e magic number.

**SwingHighToSky (long; o short é o espelho)**
- **Entrada:** CCI(20) < −150 **e** RSI(14) < 30, com ATR(14)/preço ≥ 0,70%.
- **Saída:**
  - CCI > 0 e RSI > 50 no fecho da vela;
  - TP +0,75%;
  - SL −8%;
  - trailing de 0,25% a partir de +0,5% de lucro;
  - fecho forçado após 24 velas (6 h).

**ClucMay (só long)**
- **Entrada:** fecho abaixo da EMA(100), **e** abaixo da banda inferior de Bollinger(20, 2), **e** volume abaixo de 2× a média das 30 velas anteriores. Também exige ATR(14)/preço ≥ 0,70%.
- **Saída:**
  - fecho acima da banda média de Bollinger;
  - TP +0,75%;
  - SL −8%;
  - fecho forçado após 96 velas (24 h).

**Filtro de volatilidade (0,70%):** é o mais importante para as duas. Garante que o movimento esperado cobre os custos (0,70% = 5× o custo de ida e volta de 0,14%). Por isso as estratégias passam muito tempo fora do mercado.

## Fidelidade ao backtest

- O CCI, o ATR e as bandas de Bollinger são calculados no próprio EA com as mesmas fórmulas do backtest:
  - o CCI usa o desvio padrão × 0,8 em vez do desvio médio do CCI clássico;
  - o ATR usa a média de Wilder, enquanto o iATR do MT5 usa média simples;
  - as bandas de Bollinger usam o desvio padrão amostral.
- O RSI e as médias usam os indicadores nativos do MT5. A diferença está só na inicialização e desaparece após algumas centenas de velas.
- O volume usa o volume de ticks por defeito, porque muitas corretoras não dão volume real em CFDs de cripto. O filtro com 2× a média quase nunca bloqueia entradas.
- **O tamanho da posição está em 100% do capital como nocional,** para ser comparável com o backtest. Num CFD alavancado isto usa margem. Reduza `InpEquityPct` para baixar o drawdown: com 50%, o DD cai para cerca de metade e o WR e o PF ficam iguais.
- **Custos:** o backtest assumiu 0,07% por lado mais funding. Os CFDs de BTC têm spread, comissão e swap overnight que podem ser bem maiores, e os resultados pioram na mesma proporção.

## Números de referência para comparar no Strategy Tester

Com os **parâmetros atuais fixos**, no BTC (dados Bitstamp), 100% do capital e custo de 0,07% por lado:

| | Período | Trades | WR | PF | DD |
|---|---|---|---|---|---|
| ClucMay | 2021-01 → 2026-10 | 342 | 83,0% | 1,35 | 18,4% |
| ClucMay | 2025-07 → 2026-10 | 11 | 72,7% | 2,03 | 4,3% |
| SwingHighToSky | 2021-01 → 2026-10 | 418 | 77,8% | 1,06 | 38,5% ✗ |
| SwingHighToSky | 2025-07 → 2026-10 | 21 | 81,0% | 2,87 | 4,9% |

Os dados da sua corretora vão dar números um pouco diferentes, mas a ordem de grandeza deve bater certo.

**A ClucMay cumpre os critérios mesmo com parâmetros fixos. A SwingHighToSky não.** Os 120 trades com PF 1,62 da Swing vêm do walk-forward, com os parâmetros re-otimizados a cada 3 meses. Para obter esse resultado tem de fazer a re-otimização trimestral descrita abaixo.

## Re-otimização trimestral (walk-forward)

Faça isto a 1 de jan, abr, jul e out:

1. Abra o Strategy Tester (Ctrl+R) e escolha o EA, o símbolo BTCUSD e o timeframe M15.
2. Datas: **os últimos 24 meses** até hoje.
3. Modelagem: "1 minute OHLC" (mais rápido) ou "Every tick based on real ticks".
4. Otimização: **"Fast genetic based algorithm"**. Critério: **"Custom max"**.
5. Nos Inputs, faça **Load** do `.set` da estratégia.
6. Corra a otimização e ordene os resultados por **Custom**.
   - Pontuação > 0 significa que o conjunto cumpre WR ≥ 57%, PF ≥ 1,05, DD < 20%, pelo menos 40 trades e PF ≥ 1 nos últimos 12 meses.
   - A pontuação é (PF − 1) × ln(trades). Na Swing usa o pior PF das duas metades do período (`InpRobustSelect=true`).
7. Escolha o melhor resultado e use esses parâmetros no gráfico real durante os 3 meses seguintes.
8. **Se nenhum resultado tiver pontuação > 0, não opere essa estratégia nesse trimestre.**

## Estado atual (re-otimização de 1/out/2026, BTC)

- **SwingHighToSky:** operar com os valores por defeito do EA.
- **ClucMay:** **nenhum conjunto de parâmetros qualificou** na janela out/2024 → set/2026. Pelas regras do walk-forward, a ClucMay **não deve operar até à próxima re-otimização** (1/jan/2027). Os valores por defeito do EA são os de jul/2026, os últimos que qualificaram.

Histórico dos parâmetros escolhidos (corrida mediana do walk-forward):

**SwingHighToSky** (pct = TP/SL em %; atr = múltiplos de ATR)

| Desde | Lado | CCI n / entrada / saída | RSI n / entrada / saída | Filtros | TP / SL | Trailing | Máx. velas |
|---|---|---|---|---|---|---|---|
| 2024-07 | long | 20 / −150 / >150 | 7 / <25 / >70 | SMA 200 dias, ATR ≥ 0,70% | sem TP / 8% | 0,25% após +0,5% | 12 |
| 2026-01 | long | 20 / −150 / >150 | 7 / <20 / >60 | ATR ≥ 0,70% | 1,5 / 3 ATR | sim | — |
| 2026-04 → hoje | long | 20 / −150 / >0 | 14 / <30 / >50 | ATR ≥ 0,70% | 0,75% / 8% | 0,25% após +0,5% | 24 |

**ClucMay**

| Desde | EMA | k × BB inferior | Volume | Filtros | TP / SL | Máx. velas |
|---|---|---|---|---|---|---|
| 2024-07 | 100 | 1,00 | < 5× | SMA 200 velas × 1,0; ATR ≥ 0,42% | 2% / 8% | 48 |
| 2025-01 | 100 | 1,00 | < 20× | SMA 400 velas × 0,95; SMA 50 dias; ATR ≥ 0,70% | 1,5 / 6 ATR | — |
| 2025-04 → 2026-09 | 100 | 1,00 | < 2× | ATR ≥ 0,70% | 0,75% / 8% | 96 |
| 2026-10 | — | — | — | nenhum conjunto qualificou → fora do mercado | — | — |

## Outros pares

No teste multi-ativo, a **ClucMay foi a estratégia que melhor se transferiu**: teve PF > 1 em ETH, SOL e XRP e cumpriu os critérios todos em XRP e SOL. A **SwingHighToSky funciona em XRP e SOL mas falha no ETH.** Se usar estes EAs noutros símbolos, re-otimize no próprio símbolo. Nesses pares, reduza também `InpEquityPct`, porque a volatilidade é 1,4 a 2× a do BTC.

## Riscos

São resultados de backtest e walk-forward. A seleção entre muitas configurações enviesa-os para cima, por isso conte com resultados futuros piores. Faça 1 a 3 meses em conta demo antes de usar capital real. Isto não é aconselhamento financeiro.
