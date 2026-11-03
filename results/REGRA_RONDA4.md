# Regra pré-declarada da ronda 4 (escrita às ~21:07 UTC de 03/11/2026, ANTES de correr o loop)

Objetivo: melhorar a A2, sobretudo nos pontos fracos (atraso de execução, spread, TP minúsculo).

* **Dados de otimização:** 15/01/2022 a 03/11/2026 (já vistos nas rondas anteriores), spread proporcional de 0,025%.
* **Score** (`scalping/search_r4.py`), calculado só nesse período:
  * 0,5 × retorno médio anual + 1,0 × pior ano (2022…2026).
  * Penalizações por cada pressuposto não cumprido (trades, WR, PF, DD, perdas seguidas).
  * Penalização se, com **1 minuto de atraso**, o PF ficar abaixo de 1,3 ou houver mais de 2 perdas seguidas.
  * Penalização se, com **spread de 0,035%**, o PF ficar abaixo de 1,3 ou houver mais de 2 perdas seguidas.
* **Espaço de pesquisa:** família RSI com filtro de tendência "a favor" (a lógica da A/A2), mais as novas opções: ordem limite (lim_atr, lim_win), TP mínimo em % do preço e filtro HTF.
* **Desafiante:** UM setup, o de maior score robusto (0,4 × próprio + 0,6 × mediana dos vizinhos) que cumpra todos os pressupostos em 2022–26.
* **Juiz:** 01/01/2018 a 31/12/2021, nunca usado em nenhuma ronda, spread de 0,025%.
* **O desafiante substitui a A2 se, no juiz:**
  * PF(desafiante) > PF(A2), **e**
  * perdas seguidas máximas(desafiante) ≤ perdas seguidas máximas(A2), **e**
  * DD(desafiante) ≤ max(20%, DD(A2)).
* Caso contrário, mantém-se a A2. O período 2018–21 não é calculado durante o loop.
