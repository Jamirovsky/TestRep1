from __future__ import annotations

from pathlib import Path

import streamlit as st

from shipping_agent.engine import ShippingRateEngine
from shipping_agent.models import Query


st.set_page_config(page_title="UPS/FedEx Shipping Agent", layout="wide")
st.title("Agente de Tarifas UPS/FedEx")
st.caption("Carrega ficheiros PDF/Excel de transportadoras e compara serviços e preços.")

folder_input = st.text_input("Pasta com ficheiros", value="./data")
config_input = st.text_input("Config YAML (opcional)", value="./config/rate_templates.yaml")

if st.button("Ler ficheiros"):
    folder = Path(folder_input)
    config = Path(config_input)

    if not folder.exists() or not folder.is_dir():
        st.error("A pasta indicada não existe.")
    else:
        engine = ShippingRateEngine.from_folder(folder=folder, config_path=config if config.exists() else None)
        st.session_state["engine"] = engine
        st.success(f"Tarifas carregadas: {len(engine.rates)}")

engine: ShippingRateEngine | None = st.session_state.get("engine")

if engine is not None and not engine.df.empty:
    c1, c2, c3 = st.columns(3)
    with c1:
        origin = st.selectbox("País de origem", options=engine.available_origins())
    with c2:
        destination = st.selectbox("País de destino", options=engine.available_destinations())
    with c3:
        weight = st.number_input("Peso (kg)", min_value=0.01, value=1.0, step=0.25)

    if st.button("Pesquisar serviços"):
        result = engine.query(Query(origin_country=origin, destination_country=destination, weight_kg=weight))
        if result.empty:
            st.warning("Sem resultados para os filtros escolhidos.")
        else:
            st.dataframe(
                result[
                    [
                        "carrier",
                        "service",
                        "origin_country",
                        "destination_country",
                        "weight_kg",
                        "price",
                        "currency",
                        "zone",
                        "origin_type",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    st.subheader("Tabela normalizada")
    st.dataframe(engine.df, use_container_width=True, hide_index=True)

else:
    st.info("Clique em 'Ler ficheiros' para inicializar o motor.")
