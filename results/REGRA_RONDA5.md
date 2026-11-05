# Regra pré-declarada da ronda 5 (escrita antes do loop, 05/11/2026)

Objetivo: adaptar 8 estratégias inspiradas no Chart Fanatics e em campeões do World Cup Trading
Championship (`scalping/strategies_yt.py`) aos pressupostos do cliente.

1. Loop (`scalping/search_yt.py`): otimiza cada família em 15/01/2022 a 03/11/2026, com spread de 0,025% e o mesmo score da ronda 4:
   * retorno anual médio + pior ano;
   * penalizações por pressupostos não cumpridos;
   * robustez a 1 minuto de atraso e a spread de 0,035%.
2. Seleção: por família, o desafiante é o setup com maior score robusto (0,4 × próprio + 0,6 × mediana dos vizinhos) que cumpra todos os pressupostos em 2022–26.
3. Juiz: 01/01/2018 a 31/12/2021, com spread de 0,025%. Para estas estratégias este período nunca foi usado em nenhuma escolha. Um desafiante "passa" se cumprir todos os pressupostos no juiz: trades > 100, WR > 57%, PF > 1,01, DD ≤ 20% e máximo de 2 perdas seguidas.
4. Um desafiante que passe só substitui a A2 se tiver PF maior do que a A2 tanto em 2018–21 (A2: 1,96) como em 2022–26 (A2: 1,83). Os que passam sem bater a A2 são reportados como candidatos a diversificação.
