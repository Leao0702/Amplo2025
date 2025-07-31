import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
from streamlit_autorefresh import st_autorefresh
from pytz import timezone
import gspread
from google.oauth2.service_account import Credentials
import json

# === Atualização automática a cada 2 minutos ===
st_autorefresh(interval=120 * 1000, key="auto_refresh")

# === Função para formatar data ===
def formatar_data(data_iso):
    try:
        return datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
    except Exception:
        return None

# === Função de multiselect com opção 'Selecionar todos' ===
def multiselect_com_todos(label, opcoes):
    destaque = "👉 SELECIONAR TODOS"
    opcoes_modificadas = [destaque] + list(opcoes)
    selecao = st.sidebar.multiselect(
        label,
        options=opcoes_modificadas,
        default=[destaque],
        format_func=lambda x: f"✅ {x}" if x == destaque else x
    )
    return list(opcoes) if destaque in selecao else selecao

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
                url = f"{url_base_tx}{manager_id}?page={page}&limit=100&startDate=2000-01-01"
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
        df["Created At"] = pd.to_datetime(df["Created At"], errors="coerce").dt.tz_localize(None).dt.strftime("%d/%m/%Y")
        return df

# === Configuração da página ===
st.set_page_config(page_title="Painel de Transações", layout="wide")
st.title("📊 Painel de Transações Amplo - API em Tempo Real")

# === Timestamp de atualização com fuso de Brasília ===
br_tz = timezone("America/Sao_Paulo")
hora_atual = datetime.now(br_tz).strftime('%H:%M:%S')
st.sidebar.markdown(f"⏰ Última atualização: {hora_atual}")

# === Carregar dados ===
df = carregar_transacoes()
if df.empty:
    st.warning("Nenhuma transação foi encontrada.")
    st.stop()

# === Filtros ===
st.sidebar.header("🔎 Filtros")

status = multiselect_com_todos("Status", df["Status"].dropna().unique())
gerentes = multiselect_com_todos("Gerente", df["Manager Name"].dropna().unique())
produtos = multiselect_com_todos("Produto", df["Product Name"].dropna().unique())

# === Range padrão do mês atual ===
hoje = date.today()
primeiro_dia = hoje.replace(day=1)
if hoje.month == 12:
    proximo_mes = hoje.replace(year=hoje.year + 1, month=1, day=1)
else:
    proximo_mes = hoje.replace(month=hoje.month + 1, day=1)
ultimo_dia = proximo_mes - pd.Timedelta(days=1)

data_range = st.sidebar.date_input("Período de Criação", [primeiro_dia, ultimo_dia])

# === Aplicar filtros ===
if isinstance(data_range, (list, tuple)) and len(data_range) == 2:
    data_inicio = pd.to_datetime(data_range[0]).strftime("%d/%m/%Y")
    data_fim = pd.to_datetime(data_range[1]).strftime("%d/%m/%Y")
    df_filtrado = df[
        df["Status"].isin(status) &
        df["Manager Name"].isin(gerentes) &
        df["Product Name"].isin(produtos) &
        df["Created At"].between(data_inicio, data_fim)
    ]
else:
    st.warning("Por favor, selecione um intervalo de datas válido.")
    df_filtrado = df[0:0]

# === Mostrar dados ===
st.subheader(f"📋 {len(df_filtrado)} transações encontradas")
st.dataframe(df_filtrado, use_container_width=True)

# === KPIs ===
total = df_filtrado["Amount"].sum()
count_paid = df_filtrado[df_filtrado["Status"] == "paid"].shape[0]
count_pending = df_filtrado[df_filtrado["Status"] == "pending"].shape[0]
total_considerado = count_paid + count_pending
percentual_conversao = (count_paid / total_considerado * 100) if total_considerado > 0 else 0

col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
with col1:
    st.metric("💰 Total movimentado", f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
with col2:
    st.markdown("<span style='color: green;'>🟢 Transações pagas</span>", unsafe_allow_html=True)
    st.subheader(f"{count_paid} transações")
with col3:
    st.markdown("<span style='color: goldenrod;'>🟡 Transações pendentes</span>", unsafe_allow_html=True)
    st.subheader(f"{count_pending} transações")
with col4:
    st.metric("📈 % de conversão em vendas", f"{percentual_conversao:.2f}%")

# === Exportar CSV ===
st.download_button(
    label="⬇️ Baixar dados filtrados (CSV)",
    data=df_filtrado.to_csv(index=False).encode("utf-8"),
    file_name="transacoes_filtradas.csv",
    mime="text/csv"
)

# === Enviar TODAS as transações para uma planilha geral ===
try:
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)

    planilha_geral = gc.open_by_url("https://docs.google.com/spreadsheets/d/1PqWsh2MEET7AG2oN71HxmAb9AqutkBHpnitP1jTMvT0/edit?gid=0")
    aba = planilha_geral.sheet1

    aba.clear()
    cabecalhos = df.columns.tolist()
    aba.append_row(cabecalhos)
    dados = df.values.tolist()

    if dados:
        aba.append_rows(dados, value_input_option="USER_ENTERED")
        st.success(f"✅ {len(dados)} transações enviadas para a planilha geral.")
    else:
        st.warning("⚠️ Nenhuma transação para enviar.")
except Exception as e:
    st.error(f"❌ Erro ao enviar dados para a planilha geral: {e}")
