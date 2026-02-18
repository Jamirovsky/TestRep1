# Agente de Tarifas UPS/FedEx

Este repositório contém um **agente de leitura de tarifários** (Excel e PDF) para transportes UPS/FedEx.

O agente:
- lê vários ficheiros numa pasta;
- interpreta origem fixa e origem variável (3rd party shipment);
- normaliza dados de país destino, zona, peso e custo;
- devolve os serviços/preços disponíveis para **Origem + Destino + Peso**;
- permite uso em **CLI** e em **dashboard Streamlit**.

## Estrutura

- `src/shipping_agent/extractors.py`: leitura e normalização de Excel/PDF.
- `src/shipping_agent/engine.py`: motor de consulta dos serviços/preços.
- `src/shipping_agent/cli.py`: interface de linha de comando.
- `src/shipping_agent/dashboard.py`: dashboard Streamlit.
- `config/rate_templates.example.yaml`: exemplo de mapeamento por ficheiro.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## 1) Preparar a pasta com tarifários

Colocar ficheiros `.xlsx`, `.xls` e `.pdf` na pasta (ex.: `./data`).

> Dica: para ficheiros com estrutura diferente, crie um YAML com templates por nome de ficheiro.

Exemplo (`config/rate_templates.yaml`):

```yaml
files:
  ups_portugal_export.xlsx:
    carrier: UPS
    currency: EUR
    service_hint: UPS Express Saver
    origin_type: fixed
    fixed_origin: PT

  fedex_3rd_party.pdf:
    carrier: FEDEX
    currency: EUR
    service_hint: FedEx International Priority
    origin_type: third_party
```

## 2) Usar via CLI

### Ler e exportar tabela normalizada

```bash
python -m shipping_agent.cli ./data --config ./config/rate_templates.yaml --export ./output/rates_normalized.xlsx
```

### Consultar serviços/preços

```bash
python -m shipping_agent.cli ./data \
  --config ./config/rate_templates.yaml \
  --origin PT \
  --destination DE \
  --weight 2.4
```

## 3) Usar via Dashboard

```bash
streamlit run src/shipping_agent/dashboard.py
```

No dashboard, indicar:
1. Pasta com ficheiros.
2. Config YAML (opcional).
3. País de origem.
4. País de destino.
5. Peso.

Resultado: tabela com todos os serviços e preços disponíveis.

## Lógica implementada

- O extrator tenta identificar automaticamente colunas equivalentes a:
  - destino (`destination/country/destino`),
  - zona (`zone/zona`),
  - peso (`weight/peso/kg`),
  - preço (`price/cost/rate/tarifa/preço`).
- Em ficheiros `third_party`, a origem pode ficar como `*` (qualquer origem) ou por linha.
- A consulta devolve o **primeiro escalão de peso >= peso pedido** para cada serviço.

## Limitações e próximos passos

- PDFs muito complexos podem exigir template específico por ficheiro.
- Para cenários enterprise, pode ser útil:
  - guardar dados numa base SQL,
  - adicionar versionamento de tabelas por data de vigência,
  - criar validações de qualidade de dados.
