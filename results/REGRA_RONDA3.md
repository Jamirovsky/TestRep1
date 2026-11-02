# Regra pré-declarada da ronda 3 (escrita às 23:47 UTC de 02/11/2026, ANTES de ver resultados)

Objetivo: melhorar a estratégia A (RSI extremo a favor da tendência, M15).

1. O loop (`search_r3_rsi.jsonl`) otimiza só com o backtest (07/01/2025 a 30/04/2026), com o mesmo score robusto das rondas anteriores.
2. No fim, a seleção robusta (vizinhança de parâmetros, também só com backtest) escolhe UM desafiante:
   o setup com maior score robusto que cumpra todos os pressupostos no backtest.
3. Juiz final: período 15/01/2022 a 06/01/2025, que nunca foi visto pela otimização nem pela estratégia A,
   com spread proporcional de 0,025% do preço (≈25 $ a 100 k$).
   O desafiante substitui a A se, nesse período:
   - tiver PF maior do que a A, e
   - tiver perdas seguidas máximas ≤ às da A, e
   - tiver DD máx ≤ 20%.
   Caso contrário, mantém-se a A.
4. O forward (mai a out/2026) é apenas informativo: já foi visto na ronda anterior.
