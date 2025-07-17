import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
from streamlit_autorefresh import st_autorefresh
from pytz import timezone  # <-- Adicionado para corrigir o fuso

# === Atualização automática a cada 2 minutos ===
st_autorefresh(interval=120 * 1000, key="auto_refresh")

# === Função para formatar data ===
def formatar_data(data_iso):
    try:
        return datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
    except Exception:
        return None

# === Carregar transações da API (sem cache) ===
def carregar_transacoes():
    with st.spinner("🔄 Carregando transações da API..."):
        url_managers = "https://tracker-api.avalieempresas.live/api/managers"
        url_base_tx = "https://tracker-api.avalieempresas.live/api/transactions/manager/"
        transacoes = []

        try:
            res_managers = requests.get(url_managers)
            res_managers.raise_for_status()
            managers = res_managers.json()
        except Exception as e:
            st.error(f"Erro ao carregar gerentes: {e}")
            return pd.DataFrame()

        for manager in managers:
            manager_id = manager.get("manager_id")
            manager_name = manager.get("name")
            page = 1

            while True:
            url = (
                f"{url_base_tx}{manager_id}?page={page}&limit=100"
                f"&startDate={data_inicio.strftime('%Y-%m-%d')}"
                f"&endDate={data_fim.strftime('%Y-%m-%d')}"
            )
            try:
                res_tx = requests.get(url)
                if res_tx.status_code != 200:
                    break

                data = res_tx.json()
                txs = data.get("transactions", [])
                if not txs:
                    break

                for tx in txs:
                    transacoes.append({
                        "Manager Name": manager_name,
                        "Manager ID": manager_id,
                        "Transaction ID": str(tx.get("id")),
                        "Client Name": tx.get("clientName", ""),
                        "Amount": tx.get("amount", 0.0),
                        "Created At": formatar_data(tx.get("createdAt")),
                        "Status": tx.get("status", ""),
                        "UTM Source": tx.get("utm_source", ""),
                        "Product Name": tx.get("productName", "")
                    })

                page += 1
            except Exception as e:
                st.warning(f"Erro ao carregar transações de {manager_name}: {e}")
                break

    df = pd.DataFrame(transacoes)
    df["Created At"] = pd.to_datetime(df["Created At"], errors="coerce").dt.strftime("%d/%m/%Y")
    return df

# === Validar range de datas ===
if isinstance(data_range, (list, tuple)) and len(data_range) == 2:
    data_inicio = pd.to_datetime(data_range[0])
    data_fim = pd.to_datetime(data_range[1])
    df = carregar_transacoes(data_inicio, data_fim)
else:
    st.warning("Por favor, selecione um intervalo de datas válido.")
    df = pd.DataFrame()

if df.empty:
    st.warning("Nenhuma transação foi encontrada.")
    st.stop()

# === Filtros laterais ===
st.sidebar.header("🔎 Filtros")
status = st.sidebar.multiselect("Status", options=df["Status"].dropna().unique(), default=df["Status"].dropna().unique())
gerentes = st.sidebar.multiselect("Gerente", options=df["Manager Name"].unique(), default=df["Manager Name"].unique())
produtos = st.sidebar.multiselect("Produto", options=df["Product Name"].unique(), default=df["Product Name"].unique())

# === Aplicar filtros ===
df_filtrado = df[
    df["Status"].isin(status) &
    df["Manager Name"].isin(gerentes) &
    df["Product Name"].isin(produtos)
]

# === Mostrar dados ===
st.subheader(f"📋 {len(df_filtrado)} transações encontradas")
st.dataframe(df_filtrado, use_container_width=True)

# === KPIs ===
total = df_filtrado["Amount"].sum()
st.metric("💰 Total movimentado", f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

col1, col2 = st.columns(2)
with col1:
    count_paid = df_filtrado[df_filtrado["Status"] == "paid"].shape[0]
    st.metric("🟢 Transações pagas", f"{count_paid} transações")
with col2:
    count_pending = df_filtrado[df_filtrado["Status"] == "pending"].shape[0]
    st.metric("🟡 Transações pendentes", f"{count_pending} transações")

# === Botão de exportação ===
st.download_button(
    label="⬇️ Baixar dados filtrados (CSV)",
    data=df_filtrado.to_csv(index=False).encode("utf-8"),
    file_name="transacoes_filtradas.csv",
    mime="text/csv"
)
