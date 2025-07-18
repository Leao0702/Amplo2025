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
status = st.sidebar.multiselect("Status", options=df["Status"].dropna().unique(), default=df["Status"].dropna().unique())
gerentes = st.sidebar.multiselect("Gerente", options=df["Manager Name"].unique(), default=df["Manager Name"].unique())
produtos = st.sidebar.multiselect("Produto", options=df["Product Name"].unique(), default=df["Product Name"].unique())

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

# === KPIs
total = df_filtrado["Amount"].sum()
st.metric("💰 Total movimentado", f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

col1, col2 = st.columns(2)
with col1:
    count_paid = df_filtrado[df_filtrado["Status"] == "paid"].shape[0]
    st.metric("🟢 Transações pagas", f"{count_paid} transações")
with col2:
    count_pending = df_filtrado[df_filtrado["Status"] == "pending"].shape[0]
    st.metric("🟡 Transações pendentes", f"{count_pending} transações")

# === Exportar CSV ===
st.download_button(
    label="⬇️ Baixar dados filtrados (CSV)",
    data=df_filtrado.to_csv(index=False).encode("utf-8"),
    file_name="transacoes_filtradas.csv",
    mime="text/csv"
)

# === Enviar dados para planilhas dos gerentes ===
creds = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
gc = gspread.authorize(Credentials.from_service_account_info(creds))

try:
    planilha_mapeamento = gc.open_by_url(
        "https://docs.google.com/spreadsheets/d/1ml33FVYisBfge4W9sONi7qwMMq2QLLuWF0CHsBrGGj0/edit#gid=0"
    )
    aba_mapeamento = planilha_mapeamento.sheet1
    mapeamento_raw = aba_mapeamento.get_all_values()[3:]  # A partir da linha 4
except Exception as e:
    st.error(f"❌ Erro ao abrir a planilha de mapeamento: {e}")
    st.stop()

mapeamento = {
    linha[0].strip(): linha[1].strip()
    for linha in mapeamento_raw
    if len(linha) >= 2 and linha[0].strip() and linha[1].strip()
}

# === DEBUG opcional ===
st.sidebar.write("👥 Gerentes encontrados na planilha:")
st.sidebar.write(list(mapeamento.keys()))

for gerente, grupo in df.groupby("Manager Name"):
    gerente_nome = gerente.strip()

    if gerente_nome not in mapeamento:
        st.warning(f"⚠️ Gerente '{gerente_nome}' não está na planilha de mapeamento.")
        continue

    planilha_id = mapeamento[gerente_nome]

    try:
        planilha_gerente = gc.open_by_key(planilha_id)
    except Exception as e:
        st.error(f"❌ Não foi possível abrir a planilha do gerente '{gerente_nome}': {e}")
        continue

    nome_mes = datetime.now().strftime("%B").capitalize()

    try:
        aba_mes = planilha_gerente.worksheet(nome_mes)
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Aba '{nome_mes}' não existe na planilha de {gerente_nome}.")
        continue

    linhas = []
    for idx, row in grupo.iterrows():
        try:
            utm = row.get("UTM Source", "").strip()
            produto = row.get("Product Name", "").strip()
            data = row.get("Created At", "").strip()
            valor = str(row.get("Amount", "")).replace(".", ",")

            if not utm or not produto or not data or not valor:
                st.warning(f"⚠️ Linha ignorada por campos vazios para '{gerente_nome}': {row.to_dict()}")
                continue

            nova_linha = [""] * 13
            nova_linha[0] = utm
            nova_linha[1] = produto
            nova_linha[12] = data
            nova_linha.append(valor)
            linhas.append(nova_linha)
        except Exception as e:
            st.error(f"❌ Erro ao processar linha: {e}")

    if linhas:
        try:
            aba_mes.append_rows(linhas, value_input_option="USER_ENTERED")
            st.success(f"✅ {len(linhas)} linhas enviadas para a planilha de '{gerente_nome}'.")
        except Exception as e:
            st.error(f"❌ Erro ao enviar dados para '{gerente_nome}': {e}")
    else:
        st.warning(f"⚠️ Nenhuma linha válida para enviar para '{gerente_nome}'.")
