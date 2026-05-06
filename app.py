import os
import json
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from coleta_mercado import coletar as _coletar_cotacoes

st.set_page_config(page_title="Soja e Milho de Rondônia — Preço, Câmbio e Risco", layout="wide")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .disclaimer {
        background-color: #2b2f3e; color: #d0d4dc;
        padding: 10px 14px; border-radius: 6px;
        border-left: 3px solid #00d26a;
        font-size: 13px; margin-bottom: 16px;
    }
    .context-box {
        background-color: #1e2130; border-radius: 10px;
        padding: 14px 16px; border-left: 4px solid #00d26a;
        font-size: 14px; color: #d0d4dc; margin-bottom: 16px;
    }
    </style>
""", unsafe_allow_html=True)

# --- CONSTANTES DE MERCADO ---
# Conversão tonelada -> bushel (peso oficial CBOT)
BUSHELS_POR_TONELADA = {"Soja": 36.7437, "Milho": 39.3680}

# Custos médios de produção (R$/ha) — Custo Operacional Total (COT) da CONAB
# Referências:
# - Soja: Cerejeiras/RO — safra 2024/25 — Acompanhamento da Safra Brasileira
# - Milho 2ª safra: Cone Sul/RO — safra 2024/25
# Fonte: CONAB - Custos de Produção Agrícola (conab.gov.br/info-agro/custos-de-producao)
# Atualização recomendada: a cada nova publicação mensal da CONAB.
CUSTO_HA_DEFAULT = {"Soja": 6012.0, "Milho": 4180.0}

# Basis Brasil — deságio típico do produtor em relação à CBOT (em US$/bushel).
# Reflete frete até o porto, qualidade e prazos. Para Rondônia, escoamento via
# Arco Norte tende a ter basis mais negativo que o Sul/MT por gargalo logístico
# do Madeira em estiagem. Defaults calibrados pela média 2023–25 de:
# - USDA FAS — Brazil Oilseeds and Products Annual (GAIN report)
# - CONAB — Acompanhamento da Safra Brasileira (módulo Logística)
# - ABIOVE — Boletim de Comércio Exterior
BASIS_DEFAULT_USD = {"Soja": -1.20, "Milho": -0.50}

_MESES_ABREV_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def fmt_mes_pt(d):
    """Formata data como 'Mai/2026' usando abreviações PT-BR (não depende de locale)."""
    return f"{_MESES_ABREV_PT[d.month]}/{d.year}"


CULTURAS = {
    "Soja": {
        "ticker_col": "Soja_USD_bushel",
        "qtd_col":    "Soja_Qtd_T",
        "area_col":   "Soja_AreaPlant_Ha",
        "prod_col":   "Soja_Prod_KgHa",
        "valor_col":  "Soja_Valor_Mil",
        "contexto": (
            "Cotada na Bolsa de Chicago em US$/bu. RO produz 2,2 Mi t/ano, "
            "com escoamento via Arco Norte (Porto Velho/RO → Itacoatiara/AM → Santarém/PA)."
        ),
    },
    "Milho": {
        "ticker_col": "Milho_USD_bushel",
        "qtd_col":    "Milho_Qtd_T",
        "area_col":   "Milho_AreaPlant_Ha",
        "prod_col":   "Milho_Prod_KgHa",
        "valor_col":  "Milho_Valor_Mil",
        "contexto": (
            "Cotado na Bolsa de Chicago em US$/bu. RO cultiva milho em sistema safrinha, "
            "logo após a colheita da soja, com produtividade média acima de 4.000 kg/ha."
        ),
    },
}


@st.cache_data
def carregar_producao():
    pasta = os.path.dirname(__file__)
    df = pd.read_csv(os.path.join(pasta, "dados_agro_ro_master.csv"))
    for col in df.columns:
        if col != "Municipio":
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    with open(os.path.join(pasta, "mapa_ro.json"), encoding="utf-8") as f:
        geojson = json.load(f)
    return df, geojson


@st.cache_data(ttl=3600)  # 1h cache para cotações
def carregar_cotacoes():
    pasta = os.path.dirname(__file__)
    arq = os.path.join(pasta, "cotacoes_historico.parquet")
    if not os.path.exists(arq):
        return pd.DataFrame()
    return pd.read_parquet(arq)


# --- GEO: centroides municipais e distância ao porto de Porto Velho ---
def _extrair_centroide(geometry):
    """Centroide aproximado pela média das coordenadas do anel externo.
    Para municípios de RO (área pequena), erro vs centroide geográfico real é < 5km."""
    if geometry["type"] == "Polygon":
        coords = geometry["coordinates"][0]
    elif geometry["type"] == "MultiPolygon":
        # Usa o maior polígono (ilhas/exclaves marginais não enviesam)
        maior = max(geometry["coordinates"], key=lambda p: len(p[0]))
        coords = maior[0]
    else:
        return None
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# Hubs de transbordo para escoamento de soja/milho do Centro-Oeste/Norte.
# Modelo aditivo: custo_total_BRL_t = km × tarifa_rod + custo_fixo_pos_hub
# custo_fixo_pos_hub: trecho pós-hub até o porto de exportação, modal específico.
# Fontes dos custos fixos:
# - PVH: hidrovia Madeira → Itacoatiara/Santarém — ANTAQ/HBSA, range R$70-110/t (2024)
# - Rondonópolis: ferrovia Rumo → Santos — IMEA/Rumo Relatório Tarifário 2024, R$140-180/t
# - Miritituba: barcaças Tapajós → Vila do Conde — estimativa ESALQ-LOG; dado primário pendente
HUBS_LOGISTICOS = {
    "Porto Velho (Arco Norte)": {
        "coord": (-8.7619, -63.9039),
        "custo_fixo_brl_t": 90.0,
        "rota": "rodovia → hidrovia Madeira → Itacoatiara/Santarém → exportação",
        "operadores": "Hermasa/Amaggi, Cargill",
        "fonte": "ANTAQ/HBSA — midpoint R$70-110/t (2024)",
    },
    "Rondonópolis (ferrovia → Santos)": {
        "coord": (-16.4673, -54.6372),
        "custo_fixo_brl_t": 160.0,
        "rota": "rodovia → ferrovia Rumo → Santos",
        "operadores": "Rumo Logística",
        "fonte": "IMEA/Rumo Relatório Tarifário 2024 — midpoint R$140-180/t",
    },
    "Miritituba (Tapajós)": {
        "coord": (-4.2825, -55.9853),
        "custo_fixo_brl_t": 100.0,
        "rota": "BR-163 → barcaças Tapajós → Vila do Conde/Belém",
        "operadores": "Cargill, Bunge, Hidrovias do Brasil",
        "fonte": "Estimativa ESALQ-LOG; dado primário pendente — revisão futura",
    },
}


@st.cache_data
def calcular_distancias_aos_hubs(_geojson):
    """Para cada município, retorna km até cada hub (Haversine).
    Cacheado: roda uma única vez por sessão.
    Retorno: {municipio: {hub_nome: km}}."""
    centroides = {}
    for feat in _geojson["features"]:
        nome = feat["properties"]["name"]
        c = _extrair_centroide(feat["geometry"])
        if c is not None:
            centroides[nome] = c

    return {
        mun: {
            nome_hub: _haversine_km(c[0], c[1], h["coord"][0], h["coord"][1])
            for nome_hub, h in HUBS_LOGISTICOS.items()
        }
        for mun, c in centroides.items()
    }


def escolher_hub(distancias_por_hub, tarifa_rod_brl_t_por_100km, dolar, bushels_t):
    """Para um município, escolhe o hub que minimiza o custo logístico total.
    Modelo aditivo: custo_brl_t = km × tarifa_rod + custo_fixo_pos_hub
    Convertido para US$/bu via dólar e bushels/t.
    Retorna (nome_hub, km_até_esse_hub, custo_total_usd_bu)."""
    melhor = None
    for hub_nome, km in distancias_por_hub.items():
        h = HUBS_LOGISTICOS[hub_nome]
        custo_brl_t = km * (tarifa_rod_brl_t_por_100km / 100.0) + h["custo_fixo_brl_t"]
        custo_usd_bu = custo_brl_t / (dolar * bushels_t)
        if melhor is None or custo_usd_bu < melhor[2]:
            melhor = (hub_nome, km, custo_usd_bu)
    return melhor


df_prod, geojson = carregar_producao()
df_cot = carregar_cotacoes()
hubs_municipios = calcular_distancias_aos_hubs(geojson)

# Extrai dólar atual antes da sidebar (necessário para converter R$/t → US$/bu no roteamento)
_serie_dolar_pre = df_cot["Dolar_PTAX"].dropna() if not df_cot.empty and "Dolar_PTAX" in df_cot.columns else pd.Series(dtype=float)
dolar_atual = float(_serie_dolar_pre.iloc[-1]) if not _serie_dolar_pre.empty else 5.80

# cultura_sel precisa existir antes da sidebar para alimentar as leituras de session_state
cultura_sel = st.session_state.get("cultura_sel", list(CULTURAS.keys())[0])

# Lê valores dos controles de simulação do session_state (definidos em Aba 2)
# Garante que sidebar e KPIs usem o valor mais recente mesmo antes de Aba 2 renderizar
_basis_key = f"basis_{cultura_sel}"
basis_usd = st.session_state.get(_basis_key, BASIS_DEFAULT_USD[cultura_sel])
perfil_pct = st.session_state.get("perfil_pct", 100)
perfil_label = (
    "Médio" if perfil_pct == 100
    else f"{'Acima' if perfil_pct > 100 else 'Abaixo'} da média ({perfil_pct}%)"
)
fator = perfil_pct / 100

# --- SIDEBAR ---
with st.sidebar:
    st.title("Soja e Milho de Rondônia")
    st.caption("Preço, câmbio e risco — soja e milho de RO na perspectiva do mercado internacional.")

    if st.button("Atualizar cotações", help="Busca as cotações mais recentes da CBOT e do Banco Central. Leva ~30 segundos."):
        with st.spinner("Buscando cotações atualizadas..."):
            try:
                _coletar_cotacoes()
                st.cache_data.clear()
                st.success("Cotações atualizadas.")
                st.rerun()
            except Exception as _e:
                st.error(f"Erro ao atualizar: {_e}")

    st.markdown("---")
    cultura_sel = st.selectbox("Cultura:", list(CULTURAS.keys()), key="cultura_sel")
    cfg = CULTURAS[cultura_sel]

    st.markdown("---")
    st.caption("Perfil do produtor e deságio: ajuste na aba **Simulador de Receita**.")

    basis_geo = st.checkbox(
        "Ajustar deságio pela distância ao terminal logístico",
        value=False,
        help=(
            "Quando ativo, cada município é roteado para o terminal logístico de "
            "MENOR CUSTO entre três opções: Porto Velho (Arco Norte), "
            "Rondonópolis (ferrovia → Santos) e Miritituba (Tapajós). "
            "O custo considera frete rodoviário até o terminal mais o custo fixo do "
            "corredor pós-terminal (hidrovia, ferrovia ou barcaças). "
            "O deságio é ajustado pelo custo total de escoamento de cada município."
        ),
    )
    # Pré-computa o roteamento (independente do toggle, usado no expander)
    rota_municipal = {}  # {mun: (hub, km, custo_usd_bu)}
    if basis_geo and hubs_municipios:
        tarifa_rod = st.slider(
            "Tarifa rodoviária",
            min_value=5.0, max_value=30.0, value=15.0, step=1.0,
            format="R$ %.0f/t por 100 km",
            help=(
                "Custo marginal de frete rodoviário de grãos. "
                "Default R$15/t por 100 km — calibrado pela tarifa ANTT 2024: "
                "~R$160/t para Vilhena→Rondonópolis (~1.050 km). "
                "Quanto maior, mais o modelo pune municípios distantes do hub."
            ),
        )
        bushels_t = BUSHELS_POR_TONELADA[cultura_sel]

        # Para cada município: escolhe o hub de menor custo total (frete rod + custo fixo pós-hub)
        for mun in df_prod["Municipio"]:
            dists = hubs_municipios.get(mun, {})
            if dists:
                rota_municipal[mun] = escolher_hub(dists, tarifa_rod, dolar_atual, bushels_t)

        # basis municipal = basis_base − custo_logístico_até_hub
        basis_municipios = pd.Series({
            mun: basis_usd - rota_municipal.get(mun, (None, 0, 0))[2]
            for mun in df_prod["Municipio"]
        })

        with st.expander("Como cada município está sendo roteado", expanded=False):
            st.caption(
                "**Como funciona:** o modelo escolhe o terminal logístico que minimiza o custo total "
                "(distância × tarifa de frete + custo fixo do corredor). "
                "Hidrovia tende a perder em distâncias longas; ferrovia compensa a distância maior."
            )
            from collections import Counter
            rotas = Counter(r[0] for r in rota_municipal.values() if r)
            total = sum(rotas.values())
            st.caption("**Distribuição de municípios por terminal escolhido:**")
            for hub_nome, n in sorted(rotas.items(), key=lambda x: -x[1]):
                st.caption(f"• {hub_nome}: {n} municípios ({n/total*100:.0f}%)")

            df_h = pd.DataFrame([
                {"Municipio": m, "km": r[1], "hub": r[0], "basis": basis_municipios[m]}
                for m, r in rota_municipal.items()
            ]).sort_values("km")
            st.caption("---")
            st.caption("**Menor deságio de distância (mais perto do terminal):**")
            for _, r in df_h.head(3).iterrows():
                st.caption(f"• {r['Municipio']}: {r['km']:.0f} km via {r['hub'].split(' (')[0]} · deságio US$ {r['basis']:+.2f}/bu")
            st.caption("**Maior deságio de distância (mais longe do terminal):**")
            for _, r in df_h.tail(3).iterrows():
                st.caption(f"• {r['Municipio']}: {r['km']:.0f} km via {r['hub'].split(' (')[0]} · deságio US$ {r['basis']:+.2f}/bu")
    else:
        basis_municipios = pd.Series(
            {mun: basis_usd for mun in df_prod["Municipio"]}
        )

    st.markdown("---")
    st.subheader("Fontes")
    st.caption("""
    - **Produção municipal:** IBGE/PAM 2023 (tabela 1612)
    - **Cotações Soja/Milho:** Bolsa de Chicago via Yahoo Finance (semanal, histórico máximo)
    - **Câmbio:** PTAX oficial — Banco Central do Brasil (SGS série 1, desde 2000)
    - **Fertilizantes:** Índice IPA-OG FGV via BCB (SGS série 7456, desde 1995)
    """)
    st.caption("Veja `METODOLOGIA.md` para detalhes técnicos e limitações.")

# --- HEADER ---
st.title("Soja e Milho de Rondônia — Preço, Câmbio e Risco")
st.markdown(
    '<div class="disclaimer">'
    "Análise da produção agrícola de RO sob a perspectiva do mercado: "
    "preço internacional (Chicago), câmbio e simulação de cenários. "
    "Cotações atualizadas a cada hora durante o expediente da bolsa."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="disclaimer" style="border-left-color:#ffbd45;">'
    "<b>Sobre a abordagem analítica:</b> as métricas são calculadas a nível municipal "
    "— média ponderada de produção, área e produtividade. Esta é uma visão estratégica "
    "e regional, útil para cooperativas, traders, seguradoras e formuladores de política. "
    "<b>Não reflete o produtor individual:</b> dentro de cada município existem "
    "produtores acima e abaixo da média, com estruturas de custo e produtividade próprias. "
    "Para análise individual seriam necessários dados que não são públicos (CPF/CNPJ).<br><br>"
    "<b>Sobre o preço Chicago:</b> é a cotação internacional de referência. "
    "O produtor brasileiro não vende direto à CBOT — vende a uma trading "
    "(Cargill, Bunge, ADM, Amaggi, Cofco, Louis Dreyfus) ou cooperativa, "
    "que precifica o contrato como CBOT − basis. O preço efetivo na fazenda é sempre "
    "menor que a cotação de Chicago — a diferença é o basis (frete + qualidade + prazo + margem comercial)."
    "</div>",
    unsafe_allow_html=True,
)

# --- KPIs DE MERCADO ---
if not df_cot.empty and cfg["ticker_col"] in df_cot.columns:
    serie_commodity = df_cot[cfg["ticker_col"]].dropna()
    serie_dolar = df_cot["Dolar_PTAX"].dropna() if "Dolar_PTAX" in df_cot.columns else pd.Series(dtype=float)

    preco_atual = float(serie_commodity.iloc[-1])
    preco_12m = float(serie_commodity.iloc[-52]) if len(serie_commodity) > 52 else float(serie_commodity.iloc[0])
    var_12m = (preco_atual / preco_12m - 1) * 100

    dolar_atual = float(serie_dolar.iloc[-1]) if not serie_dolar.empty else 5.0
    dolar_12m = float(serie_dolar.iloc[-52]) if len(serie_dolar) > 52 else dolar_atual
    var_dolar = (dolar_atual / dolar_12m - 1) * 100

    # CBOT está em centavos/bushel. Converte para US$/bushel e aplica basis.
    preco_cbot_usd = preco_atual / 100
    preco_efetivo_usd = preco_cbot_usd + basis_usd  # basis é negativo => reduz
    bushels_t = BUSHELS_POR_TONELADA[cultura_sel]
    preco_brl_t = preco_efetivo_usd * bushels_t * dolar_atual
    saca_60kg = preco_brl_t * 0.06

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        f"{cultura_sel} — Bolsa de Chicago",
        f"US$ {preco_cbot_usd:,.2f}/bu",
        f"{var_12m:+.1f}% 12m",
        help=(
            "Cotação de referência internacional negociada na Bolsa de Chicago. "
            f"1 bushel de {cultura_sel.lower()} = {BUSHELS_POR_TONELADA[cultura_sel]:.1f} kg. "
            "O produtor brasileiro recebe menos que este valor — a diferença é o deságio (ver sidebar)."
        ),
    )
    k2.metric(
        "Câmbio (R$/US$)",
        f"R$ {dolar_atual:,.2f}",
        f"{var_dolar:+.1f}% 12m",
        help="PTAX — câmbio oficial divulgado pelo Banco Central ao final de cada dia útil (SGS série 1). Referência para liquidação de contratos cambiais.",
    )
    k3.metric(
        f"Preço ao produtor — R$/saca",
        f"R$ {saca_60kg:,.2f}",
        help=(
            f"Saca de 60 kg. Calculado: cotação Chicago US$ {preco_cbot_usd:.2f}/bu "
            f"com deságio de US$ {basis_usd:+.2f}/bu, convertido pelo câmbio R$ {dolar_atual:.2f}."
        ),
    )
    k4.metric(f"Preço ao produtor — R$/t", f"R$ {preco_brl_t:,.0f}")
else:
    st.warning("Cotações indisponíveis. Execute `python coleta_mercado.py` para atualizar.")
    st.stop()

st.markdown(
    f'<div class="context-box"><b>{cultura_sel}:</b> {cfg["contexto"]}</div>',
    unsafe_allow_html=True,
)

# --- ABAS ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Preços e Câmbio", "Simulador de Receita", "Risco Cambial",
    "Cenários Combinados", "Sazonalidade e Hedge",
])

# --- ABA 1: COTAÇÕES × CÂMBIO ---
with tab1:
    # Janelas limitadas a 10 anos para dados nominais sem deflação.
    # Períodos mais longos exigiriam deflação por CPI americano (CBOT) e IPCA (BRL),
    # o que não está implementado nesta versão. Dados de sazonalidade e hedge
    # usam o histórico completo (~30 anos) porque trabalham com comparações relativas.
    anos_opcoes = {"5 anos": 5, "10 anos": 10}
    janela_sel = st.radio(
        "Período do histórico:",
        options=list(anos_opcoes.keys()),
        index=0,
        horizontal=True,
        key="janela_historico",
    )
    anos_janela = anos_opcoes[janela_sel]
    corte = pd.Timestamp.now() - pd.DateOffset(years=anos_janela)

    serie_commodity_plot = serie_commodity[serie_commodity.index >= corte]
    serie_dolar_plot     = serie_dolar[serie_dolar.index >= corte]

    periodo_str = (
        f"{fmt_mes_pt(serie_commodity_plot.index.min())} "
        f"a {fmt_mes_pt(serie_commodity_plot.index.max())}"
    )
    st.subheader(f"Histórico: {cultura_sel} e câmbio — {janela_sel}")

    _hover_dates_commodity = [fmt_mes_pt(d) for d in serie_commodity_plot.index]
    _hover_dates_dolar = [fmt_mes_pt(d) for d in serie_dolar_plot.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=serie_commodity_plot.index, y=serie_commodity_plot.values,
            name=f"{cultura_sel} — Chicago (US$/bu)", line=dict(color="#00d26a", width=2),
            customdata=_hover_dates_commodity,
            hovertemplate=f"<b>%{{customdata}}</b><br>{cultura_sel}: %{{y:.2f}} US$/bu<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=serie_dolar_plot.index, y=serie_dolar_plot.values,
            name="Dólar PTAX (R$)", line=dict(color="#ffbd45", width=2, dash="dot"),
            customdata=_hover_dates_dolar,
            hovertemplate="<b>%{customdata}</b><br>Dólar PTAX: R$ %{y:.2f}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_xaxes(title_text="")
    fig.update_yaxes(title_text=f"{cultura_sel} — US$/bushel (×100)", secondary_y=False, color="#00d26a")
    fig.update_yaxes(title_text="Dólar PTAX — R$", secondary_y=True, color="#ffbd45")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin={"t": 50, "b": 30, "l": 0, "r": 0},
        height=480,
        hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
    )
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})

    st.caption(
        f"Eixo esquerdo (verde): preço negociado na Bolsa de Chicago em centavos de dólar por bushel. "
        f"Eixo direito (amarelo): câmbio oficial PTAX (R$/US$) — Banco Central do Brasil, SGS série 1. "
        f"Período: {periodo_str}. "
        f"Valores nominais — sem ajuste por inflação (CPI americano para CBOT; IPCA para câmbio). "
        f"Esta série serve como referência de contexto de mercado. "
        f"O produtor recebe e paga custos em valores nominais — a análise de se o preço atual "
        f"cobre o custo está na aba Risco Cambial. "
        f"Para comparação de poder de compra ao longo do tempo, use o Índice de Poder de Compra "
        f"(seção abaixo), que trabalha com razão entre preços e cancela grande parte do efeito inflacionário."
    )

    # --- ÍNDICE DE PODER DE COMPRA ---
    if "IPA_Fertilizante_Idx" in df_cot.columns:
        st.markdown("---")
        st.subheader(f"Índice de Poder de Compra do Produtor — {cultura_sel}")

        st.markdown(
            '<div class="context-box">'
            f"<b>O que mostra:</b> evolução do preço efetivo da saca de {cultura_sel.lower()} "
            "em RO comparada ao preço dos fertilizantes. Ambos normalizados em "
            f"<b>base 100</b>. Quando a curva <b>cai</b>, o produtor está empobrecendo em termos reais "
            "— mesmo que a saca esteja subindo nominalmente, o fertilizante sobe mais. "
            "Métrica clássica de relação de troca em economia agrícola."
            "</div>",
            unsafe_allow_html=True,
        )

        # Histórico do preço efetivo da saca
        ticker_col = cfg["ticker_col"]
        df_hist = df_cot[[ticker_col, "Dolar_PTAX", "IPA_Fertilizante_Idx"]].dropna().copy()
        bt = BUSHELS_POR_TONELADA[cultura_sel]
        df_hist["preco_BRL_saca"] = (df_hist[ticker_col] / 100 + basis_usd) * bt * df_hist["Dolar_PTAX"] * 0.06

        # Normaliza ambos em base 100 no primeiro ponto comum
        base_saca = df_hist["preco_BRL_saca"].iloc[0]
        base_fert = df_hist["IPA_Fertilizante_Idx"].iloc[0]
        df_hist["Saca_Idx"] = df_hist["preco_BRL_saca"] / base_saca * 100
        df_hist["Fert_Idx"] = df_hist["IPA_Fertilizante_Idx"] / base_fert * 100
        df_hist["Poder_Compra"] = df_hist["Saca_Idx"] / df_hist["Fert_Idx"] * 100

        # KPIs
        pc_atual = float(df_hist["Poder_Compra"].iloc[-1])
        pc_12m = float(df_hist["Poder_Compra"].iloc[-52]) if len(df_hist) > 52 else float(df_hist["Poder_Compra"].iloc[0])
        pc_pico = float(df_hist["Poder_Compra"].max())
        pc_min = float(df_hist["Poder_Compra"].min())
        data_inicio = fmt_mes_pt(df_hist.index.min())

        rk1, rk2, rk3, rk4 = st.columns(4)
        rk1.metric(
            "Poder de compra atual",
            f"{pc_atual:.0f}",
            f"{((pc_atual / pc_12m - 1) * 100):+.1f}% 12m",
            help=f"Base 100 = {data_inicio}. Acima de 100 = ganhou poder real desde a base. Abaixo = perdeu.",
        )
        _periodo_pc = f"{fmt_mes_pt(df_hist.index.min())}–{fmt_mes_pt(df_hist.index.max())}"
        rk2.metric("Pico histórico", f"{pc_pico:.0f}",
                   help=f"Melhor momento de poder de compra no período {_periodo_pc}.")
        rk3.metric("Mínimo histórico", f"{pc_min:.0f}",
                   help=f"Pior momento — maior aperto sobre o produtor no período {_periodo_pc}.")
        rk4.metric(
            f"Saca {cultura_sel} (R$/saca)",
            f"R$ {df_hist['preco_BRL_saca'].iloc[-1]:,.2f}",
            help="Preço efetivo atual (cotação Chicago + deságio × câmbio)",
        )

        # Curva única: Poder de Compra (razão cancela inflação por construção).
        # As séries individuais Saca_Idx e Fert_Idx ficam ocultas — a partir de
        # base 100 em ano antigo, ambas crescem em escala que esmaga o sinal de PC.
        # Quem quiser ver as componentes pode expandir abaixo.
        _hover_dates_rt = [fmt_mes_pt(d) for d in df_hist.index]
        fig_rt = go.Figure()
        fig_rt.add_trace(
            go.Scatter(
                x=df_hist.index, y=df_hist["Poder_Compra"],
                line=dict(color="#ffbd45", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(255, 189, 69, 0.08)",
                name="Poder de compra (saca ÷ fertilizante)",
                customdata=_hover_dates_rt,
                hovertemplate="<b>%{customdata}</b><br>Poder de compra: %{y:.0f}<extra></extra>",
            )
        )
        fig_rt.add_hline(
            y=100, line_dash="dash", line_color="white", line_width=1,
            annotation_text=f"Base 100 = {data_inicio}",
            annotation_position="bottom right",
            annotation_font_color="white",
        )
        fig_rt.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="white",
            xaxis_title="",
            yaxis_title=f"Poder de compra (base 100 = {data_inicio})",
            margin={"t": 20, "b": 0, "l": 0, "r": 0},
            height=380,
            showlegend=False,
            hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        )
        st.plotly_chart(fig_rt, width='stretch', config={'displayModeBar': False})

        st.caption(
            f"Poder de compra = (índice da saca) ÷ (índice do fertilizante) × 100. "
            f"Base 100 em {data_inicio}. "
            f"Acima de 100: produtor ganhou poder de compra real desde a base; abaixo: perdeu. "
            f"Por ser razão entre dois preços, a métrica cancela boa parte do efeito inflacionário "
            f"e permite comparação ao longo de toda a série histórica. "
            f"Índice de fertilizantes: FGV/BCB (IPA-OG, série 7456). "
            f"Calculado com deságio de US$ {basis_usd:+.2f}/bu."
        )

        with st.expander("Ver componentes (saca e fertilizante separados)", expanded=False):
            fig_comp = go.Figure()
            fig_comp.add_trace(go.Scatter(
                x=df_hist.index, y=df_hist["Saca_Idx"],
                line=dict(color="#00d26a", width=2),
                name=f"Saca {cultura_sel}",
                customdata=_hover_dates_rt,
                hovertemplate="<b>%{customdata}</b><br>Saca: %{y:.0f}<extra></extra>",
            ))
            fig_comp.add_trace(go.Scatter(
                x=df_hist.index, y=df_hist["Fert_Idx"],
                line=dict(color="#ff4b4b", width=2, dash="dot"),
                name="Fertilizantes (IPA-OG / FGV)",
                customdata=_hover_dates_rt,
                hovertemplate="<b>%{customdata}</b><br>Fert.: %{y:.0f}<extra></extra>",
            ))
            fig_comp.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font_color="white",
                xaxis_title="",
                yaxis_title=f"Índice (base 100 = {data_inicio})",
                margin={"t": 10, "b": 60, "l": 0, "r": 0},
                height=320,
                legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="right", x=1),
                hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
            )
            st.plotly_chart(fig_comp, width='stretch', config={'displayModeBar': False})
            st.caption(
                "As duas curvas em base 100 acumulam efeito inflacionário ao longo de "
                "décadas — daí a razão (curva principal acima) ser a forma correta de comparar."
            )
    else:
        st.info("Coluna `IPA_Fertilizante_Idx` ausente. Execute `python coleta_mercado.py` para atualizar.")

# --- ABA 2: SIMULADOR DE RECEITA ---
with tab2:
    st.subheader(f"Simulador de Receita — {cultura_sel}")

    df_prod_filt = df_prod[df_prod[cfg["qtd_col"]] > 0].copy()
    municipios_disp = sorted(df_prod_filt["Municipio"].tolist())

    escopo_sim = st.radio(
        "Escopo:", ["Município", "Estado de Rondônia"], horizontal=True, key="escopo_sim",
        help="Município: receita e métricas por município selecionado. Estado de Rondônia: agregado de todos os municípios produtores.",
    )

    col_input, col_output = st.columns([1, 2])

    with col_input:
        if escopo_sim == "Município":
            mun_sim = st.selectbox("Município:", municipios_disp)
        else:
            mun_sim = None
            st.caption("Agregado de todos os municípios produtores de Rondônia.")

        st.markdown("**Perfil do produtor**")
        perfil_pct = st.slider(
            "Produtividade vs. média municipal",
            min_value=60, max_value=140, value=100, step=10,
            format="%d%%", key="perfil_pct",
            help="100% = produtor médio do município. 80% = abaixo da média típica. 120% = acima da média.",
        )
        perfil_label = (
            "Médio" if perfil_pct == 100
            else f"{'Acima' if perfil_pct > 100 else 'Abaixo'} da média ({perfil_pct}%)"
        )
        fator = perfil_pct / 100

        st.markdown("**Deságio ao produtor**")
        st.caption(
            "Diferença entre o preço de Chicago e o que o produtor recebe na fazenda — "
            "inclui frete, qualidade e prazo. Negativo é o normal."
        )
        basis_usd = st.slider(
            f"Deságio — {cultura_sel}",
            min_value=-3.0, max_value=0.5,
            value=BASIS_DEFAULT_USD[cultura_sel], step=0.05,
            format="US$ %+.2f/bu", key=_basis_key,
            help=(
                "Mais negativo = produtor recebe ainda menos que Chicago. "
                "Menos negativo = logística mais barata ou prêmio de qualidade. "
                f"Referência RO: US$ {BASIS_DEFAULT_USD[cultura_sel]:+.2f}/bu — "
                "média 2023–25 (USDA GAIN, CONAB Logística, ABIOVE)."
            ),
        )

        st.markdown("**Cenário de mercado**")
        preco_sim_cbot_usd = st.slider(
            f"Preço {cultura_sel} (Chicago)",
            min_value=float(serie_commodity.min() * 0.7) / 100,
            max_value=float(serie_commodity.max() * 1.3) / 100,
            value=float(preco_atual) / 100,
            step=0.05,
            format="US$ %.2f/bu",
            help=(
                "Cotação internacional na bolsa de Chicago. "
                "Mexa para simular o que aconteceria se o preço subisse ou caísse "
                "em relação ao valor de hoje."
            ),
        )
        dolar_sim = st.slider(
            "Dólar comercial",
            min_value=float(serie_dolar.min() * 0.85),
            max_value=float(serie_dolar.max() * 1.15),
            value=float(dolar_atual),
            step=0.05,
            format="R$ %.2f",
            help=(
                "Cotação do dólar usada no cenário. "
                "Mexa para simular: dólar mais alto significa mais reais por dólar de venda."
            ),
        )
        # Preço efetivo — município ou média ponderada do estado
        if escopo_sim == "Município":
            basis_mun_sim = float(basis_municipios.get(mun_sim, basis_usd))
        else:
            _prod_sim = df_prod_filt[cfg["qtd_col"]] * fator
            _prod_sim_total = float(_prod_sim.sum())
            _basis_serie_sim = df_prod_filt["Municipio"].map(basis_municipios).fillna(basis_usd)
            basis_mun_sim = float((_prod_sim * _basis_serie_sim).sum() / _prod_sim_total) if _prod_sim_total > 0 else basis_usd

        preco_sim_efetivo = preco_sim_cbot_usd + basis_mun_sim

        if escopo_sim == "Município":
            if basis_geo:
                rota = rota_municipal.get(mun_sim)
                if rota:
                    hub_nome, km_mun_sim, _ = rota
                    hub_curto = hub_nome.split(" (")[0]
                    st.caption(
                        f"Preço que o produtor recebe: **US$ {preco_sim_efetivo:.2f}/bu** "
                        f"(Chicago US$ {preco_sim_cbot_usd:.2f} + deságio deste município "
                        f"US$ {basis_mun_sim:+.2f} · escoa via {hub_curto}, {km_mun_sim:.0f} km)"
                    )
                else:
                    st.caption(f"Preço que o produtor recebe: US$ {preco_sim_efetivo:.2f}/bu (Chicago + deságio)")
            else:
                st.caption(
                    f"Preço que o produtor recebe: **US$ {preco_sim_efetivo:.2f}/bu** "
                    f"(Chicago US$ {preco_sim_cbot_usd:.2f} + deságio US$ {basis_mun_sim:+.2f})"
                )
        else:
            st.caption(
                f"Preço médio ponderado ao produtor: **US$ {preco_sim_efetivo:.2f}/bu** "
                f"(Chicago US$ {preco_sim_cbot_usd:.2f} + deságio médio US$ {basis_mun_sim:+.2f})"
            )

    with col_output:
        if escopo_sim == "Município":
            mun_row = df_prod_filt[df_prod_filt["Municipio"] == mun_sim].iloc[0]
            producao_t = float(mun_row[cfg["qtd_col"]])
            area_ha = float(mun_row[cfg["area_col"]]) if cfg["area_col"] in mun_row else 0
            prod_kgha = float(mun_row[cfg["prod_col"]])
            prod_kgha_perfil = prod_kgha * fator
            receita_ha = (prod_kgha_perfil / 1000) * BUSHELS_POR_TONELADA[cultura_sel] * preco_sim_efetivo * dolar_sim
            receita_saca = receita_ha * 0.06 / (prod_kgha_perfil / 1000) if prod_kgha_perfil > 0 else 0
            receita_brl = producao_t * fator * BUSHELS_POR_TONELADA[cultura_sel] * preco_sim_efetivo * dolar_sim
            receita_usd = receita_brl / dolar_sim

            st.markdown(f"**Perfil do produtor: {perfil_label}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Receita por hectare", f"R$ {receita_ha:,.0f}/ha",
                      help="Receita gerada por hectare no perfil produtivo selecionado")
            c2.metric("Equivalente em sacas 60kg/ha", f"{prod_kgha_perfil/60:,.1f} sc/ha")
            c3.metric("Receita por saca", f"R$ {receita_saca:,.2f}")

            st.markdown("**Total do município — perfil selecionado:**")
            d1, d2, d3 = st.columns(3)
            d1.metric("Receita total", f"R$ {receita_brl/1e6:,.2f} Mi")
            d2.metric("Em dólares", f"US$ {receita_usd/1e6:,.2f} Mi")
            d3.metric("Produtividade aplicada", f"{prod_kgha_perfil:,.0f} kg/ha",
                      f"vs média municipal {prod_kgha:,.0f} kg/ha")
        else:
            _area_ro = float(df_prod_filt[cfg["area_col"]].sum())
            _prod_ro_t = float((df_prod_filt[cfg["qtd_col"]] * fator).sum())
            _prod_kgha_medio = (_prod_ro_t / _area_ro * 1000) if _area_ro > 0 else 0
            _receita_ro_brl = _prod_ro_t * BUSHELS_POR_TONELADA[cultura_sel] * preco_sim_efetivo * dolar_sim
            _receita_ro_usd = _receita_ro_brl / dolar_sim

            st.markdown(f"**Estado de Rondônia — perfil: {perfil_label}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Receita total estimada", f"R$ {_receita_ro_brl/1e9:,.2f} Bi")
            c2.metric("Em dólares", f"US$ {_receita_ro_usd/1e9:,.2f} Bi")
            c3.metric("Produção total aplicada", f"{_prod_ro_t/1e6:,.2f} Mi t")

            d1, d2, d3 = st.columns(3)
            d1.metric("Área plantada", f"{_area_ro/1e3:,.0f} mil ha")
            d2.metric("Produtividade média", f"{_prod_kgha_medio:,.0f} kg/ha")
            d3.metric("Municípios produtores", f"{len(df_prod_filt)}")

    st.markdown("---")
    _cenario_atual = (
        abs(preco_sim_cbot_usd - preco_atual / 100) < 0.01
        and abs(dolar_sim - dolar_atual) < 0.01
    )
    if _cenario_atual:
        st.subheader("Receita estimada por município — cenário atual de mercado")
    else:
        st.subheader("Receita estimada por município — cenário simulado")
        st.markdown(
            f'<div class="disclaimer">'
            f"Cenário aplicado: Chicago US$ {preco_sim_cbot_usd:.2f}/bu "
            f"({'acima' if preco_sim_cbot_usd > preco_atual / 100 else 'abaixo'} do atual "
            f"US$ {preco_atual / 100:.2f}) · "
            f"Dólar R$ {dolar_sim:.2f} "
            f"({'acima' if dolar_sim > dolar_atual else 'abaixo'} do atual R$ {dolar_atual:.2f})"
            f"</div>",
            unsafe_allow_html=True,
        )

    df_mapa = df_prod_filt.copy()
    # Cada município usa seu próprio basis (uniforme se basis_geo desligado, variável se ligado)
    df_mapa["preco_efetivo_usd"] = (
        preco_sim_cbot_usd
        + df_mapa["Municipio"].map(basis_municipios).fillna(basis_usd)
    )
    df_mapa["Receita_BRL_Mi"] = (
        df_mapa[cfg["qtd_col"]] * fator
        * BUSHELS_POR_TONELADA[cultura_sel]
        * df_mapa["preco_efetivo_usd"]
        * dolar_sim
        / 1e6
    )

    fig_mapa = px.choropleth_map(
        df_mapa, geojson=geojson, locations="Municipio",
        featureidkey="properties.name",
        color="Receita_BRL_Mi",
        color_continuous_scale="Viridis",
        map_style="carto-darkmatter", zoom=5.6,
        center={"lat": -10.9, "lon": -62.8},
        opacity=0.7, hover_name="Municipio",
        labels={"Receita_BRL_Mi": "Receita (R$ Mi)"},
    )
    fig_mapa.update_traces(
        hovertemplate="<b>%{hovertext}</b><br>Receita estimada: R$ %{z:,.0f} Mi<extra></extra>"
    )
    fig_mapa.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        coloraxis_colorbar=dict(tickformat=",.0f"),
    )
    st.plotly_chart(fig_mapa, width='stretch', config={'displayModeBar': False})

    basis_label = (
        f"deságio variável por município (base US$ {basis_usd:+.2f}, ajustado por distância ao terminal)"
        if basis_geo else f"deságio US$ {basis_usd:+.2f}"
    )
    st.caption(
        f"O que olhar aqui: cada município pintado pela receita estimada no cenário simulado acima. "
        f"Cores mais claras = receita maior. **Cenário aplicado:** Chicago US$ {preco_sim_cbot_usd:.2f}/bu, "
        f"{basis_label}, dólar R$ {dolar_sim:.2f}. "
        f"Receita não inclui custos — para ver margem, ver aba *Risco Cambial*."
    )

    # --- DEPENDÊNCIA: % do PIB Agro do município selecionado ---
    if "PIB_Agro_Mil" in df_prod.columns and escopo_sim == "Município":
        st.markdown("---")
        st.subheader(f"Dependência de {cultura_sel} em {mun_sim}")

        df_exp = df_prod.copy()
        df_exp["preco_efetivo_usd"] = (
            preco_sim_cbot_usd
            + df_exp["Municipio"].map(basis_municipios).fillna(basis_usd)
        )
        df_exp["Receita_BRL_Mi"] = (
            df_exp[cfg["qtd_col"]] * fator
            * BUSHELS_POR_TONELADA[cultura_sel]
            * df_exp["preco_efetivo_usd"]
            * dolar_sim
            / 1e6
        )
        df_exp["Exposicao_Pct"] = np.where(
            df_exp["PIB_Agro_Mil"] > 0,
            (df_exp["Receita_BRL_Mi"] * 1000 / df_exp["PIB_Agro_Mil"]) * 100,
            0.0,
        )

        df_prod_ativos = df_exp[df_exp[cfg["qtd_col"]] > 0]
        media_exp_ro = df_prod_ativos["Exposicao_Pct"].mean()

        mun_exp_row = df_exp[df_exp["Municipio"] == mun_sim]
        if not mun_exp_row.empty:
            exp_pct = float(mun_exp_row["Exposicao_Pct"].iloc[0])
            receita_mun = float(mun_exp_row["Receita_BRL_Mi"].iloc[0])
            pib_mun = float(mun_exp_row["PIB_Agro_Mil"].iloc[0])
            ranking_sorted = df_prod_ativos.sort_values("Exposicao_Pct", ascending=False).reset_index(drop=True)
            rank_idx = ranking_sorted[ranking_sorted["Municipio"] == mun_sim].index
            rank_pos = int(rank_idx[0]) + 1 if len(rank_idx) > 0 else None
            total_muns = len(ranking_sorted)

            c_e1, c_e2, c_e3 = st.columns(3)
            c_e1.metric(
                "Exposição ao preço",
                f"{exp_pct:.1f}% do PIB Agro",
                f"{exp_pct - media_exp_ro:+.1f}pp vs. média RO ({media_exp_ro:.1f}%)",
                help=(
                    f"Percentual do PIB Agropecuário de {mun_sim} representado pela "
                    f"receita estimada de {cultura_sel.lower()} no cenário atual. "
                    "Quanto maior, mais vulnerável o município a uma queda de preço."
                ),
            )
            c_e2.metric(
                f"Receita estimada — {cultura_sel}",
                f"R$ {receita_mun:,.1f} Mi",
                help=f"No cenário atual do simulador. PIB Agro do município: R$ {pib_mun/1000:,.0f} Mi (IBGE).",
            )
            if rank_pos:
                c_e3.metric(
                    "Ranking de exposição em RO",
                    f"{rank_pos}º de {total_muns}",
                    help="Posição entre os municípios produtores de RO, do mais ao menos exposto.",
                )

            if exp_pct >= 70:
                st.markdown(
                    f'<div class="disclaimer" style="border-left-color:#ff4b4b;">'
                    f"<b>Alta concentração:</b> {cultura_sel} representa {exp_pct:.1f}% do PIB Agro de {mun_sim}. "
                    f"Um choque de −20% no preço reduziria o PIB Agropecuário local em cerca de "
                    f"<b>{exp_pct * 0.20:.1f}%</b>."
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("**10 municípios mais expostos em RO**")
        top10 = df_prod_ativos.sort_values("Exposicao_Pct", ascending=True).tail(10)
        top10["cor"] = top10["Municipio"].apply(lambda m: "#ff4b4b" if m == mun_sim else "#00d26a")
        fig_top10 = px.bar(
            top10, x="Exposicao_Pct", y="Municipio",
            orientation="h", color="cor", color_discrete_map="identity",
            labels={"Exposicao_Pct": "% do PIB Agro", "Municipio": ""},
        )
        fig_top10.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="white", showlegend=False,
            height=320, margin={"t": 10, "b": 0, "l": 0, "r": 0},
            hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        )
        st.plotly_chart(fig_top10, width='stretch', config={'displayModeBar': False})
        st.caption(
            f"Exposição = receita estimada de {cultura_sel.lower()} ÷ PIB Agropecuário municipal × 100. "
            f"Destaque em vermelho: {mun_sim}. "
            f"Fonte PIB Agro: IBGE — Produto Interno Bruto dos Municípios. "
            f"Cenário aplicado: o mesmo do simulador acima."
        )

# --- ABA 3: RISCO CAMBIAL ---
with tab3:
    st.subheader(f"Câmbio mínimo para não ter prejuízo — {cultura_sel}")

    if cultura_sel == "Milho":
        st.markdown(
            '<div class="disclaimer">'
            "<b>Milho 2ª safra (safrinha):</b> o custo de referência abaixo "
            "(R$4.180/ha, Custo Operacional Total — COT — CONAB 2024/25) inclui arrendamento da terra "
            "e preparo de solo que, na prática, já foram pagos pela soja cultivada antes no mesmo campo. "
            "A decisão de plantar a safrinha envolve apenas os custos específicos da 2ª safra — "
            "sementes, fertilizantes, defensivos e operações mecanizadas próprias do milho. "
            "Use o slider para simular o custo que melhor representa essa realidade."
            "</div>",
            unsafe_allow_html=True,
        )

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        custo_ha = st.slider(
            f"Custo de produção — {cultura_sel}",
            min_value=2000.0, max_value=10000.0,
            value=CUSTO_HA_DEFAULT[cultura_sel], step=100.0,
            format="R$ %.0f/ha",
            help=(
                f"Default: custo operacional total (COT) CONAB para "
                f"{'Cerejeiras/RO' if cultura_sel == 'Soja' else 'Cone Sul/RO milho safrinha'}, "
                f"safra 2024/25. Inclui insumos, operações mecanizadas, mão de obra e "
                f"arrendamento. NÃO inclui frete (já considerado no deságio). "
                f"Fonte: CONAB - Custos de Produção Agrícola."
            )
        )
        st.caption(
            f"**Referência CONAB:** R$ {CUSTO_HA_DEFAULT[cultura_sel]:,.0f}/ha "
            f"({'Cerejeiras/RO' if cultura_sel == 'Soja' else 'Cone Sul/RO'} safra 2024/25)"
        )
    with col_c2:
        choque_frete = st.slider(
            "Choque de frete adicional",
            min_value=0.0, max_value=2000.0,
            value=0.0, step=50.0,
            format="R$ %.0f/ha",
            help="Em zero: modelo padrão (basis cobre frete). Positivo: simula choque "
                 "logístico (alta do diesel, fechamento de via, gargalo no Arco Norte). "
                 "Útil para testar resiliência da margem em cenários adversos."
        )
        st.caption(
            f"**Custo total aplicado:** R$ {custo_ha + choque_frete:,.0f}/ha"
            + (" *(custo + choque)*" if choque_frete > 0 else "")
        )

    custo_total_ha = custo_ha + choque_frete

    df_be = df_prod[(df_prod[cfg["qtd_col"]] > 0) & (df_prod[cfg["area_col"]] > 0)].copy()
    df_be["Custo_Total_BRL"] = df_be[cfg["area_col"]] * custo_total_ha
    # Aplica perfil de produtividade na receita; basis municipal entra aqui
    df_be["preco_efetivo_usd"] = (
        preco_cbot_usd
        + df_be["Municipio"].map(basis_municipios).fillna(basis_usd)
    )
    df_be["Receita_USD"] = (
        df_be[cfg["qtd_col"]] * fator
        * BUSHELS_POR_TONELADA[cultura_sel] * df_be["preco_efetivo_usd"]
    )
    # Break-even: Custo = Receita_USD × Dólar  =>  Dólar = Custo / Receita_USD
    df_be["Dolar_Breakeven"] = df_be["Custo_Total_BRL"] / df_be["Receita_USD"]
    df_be["Margem_Atual_BRL_Mi"] = (
        df_be["Receita_USD"] * dolar_atual - df_be["Custo_Total_BRL"]
    ) / 1e6

    media_be = df_be["Dolar_Breakeven"].mean()
    pior = df_be.loc[df_be["Dolar_Breakeven"].idxmax()]
    melhor = df_be.loc[df_be["Dolar_Breakeven"].idxmin()]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Câmbio mínimo médio", f"R$ {media_be:,.2f}")
    c2.metric("Câmbio atual", f"R$ {dolar_atual:,.2f}",
              f"{((dolar_atual - media_be) / media_be * 100):+.1f}% vs câmbio mínimo")
    c3.metric("Município mais resiliente", melhor["Municipio"],
              f"câmbio mínimo R$ {melhor['Dolar_Breakeven']:.2f}")
    c4.metric("Município mais vulnerável", pior["Municipio"],
              f"câmbio mínimo R$ {pior['Dolar_Breakeven']:.2f}")

    st.markdown("---")
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown("**Dólar break-even por município**")
        df_be_sorted = df_be.sort_values("Dolar_Breakeven")
        df_be_sorted["cor"] = df_be_sorted["Dolar_Breakeven"].apply(
            lambda v: "#00d26a" if v <= dolar_atual else "#ff4b4b"
        )
        fig_be = px.bar(
            df_be_sorted, x="Dolar_Breakeven", y="Municipio",
            orientation="h", color="cor", color_discrete_map="identity",
            labels={"Dolar_Breakeven": "Câmbio mínimo (R$/US$)", "Municipio": ""},
        )
        fig_be.add_vline(
            x=dolar_atual, line_dash="dash", line_color="white",
            annotation_text=f"Câmbio atual R$ {dolar_atual:.2f}",
            annotation_position="top right",
            annotation_font_color="white",
        )
        fig_be.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="white", showlegend=False,
            height=600,
            margin={"t": 20, "b": 0, "l": 0, "r": 0},
            hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        )
        st.plotly_chart(fig_be, width='stretch', config={'displayModeBar': False})

    with col_g2:
        st.markdown("**Margem estimada no cenário atual (R$ Mi)**")
        df_marg = df_be.sort_values("Margem_Atual_BRL_Mi", ascending=True).tail(20)
        df_marg["cor_marg"] = df_marg["Margem_Atual_BRL_Mi"].apply(
            lambda v: "#00d26a" if v >= 0 else "#ff4b4b"
        )
        fig_m = px.bar(
            df_marg, x="Margem_Atual_BRL_Mi", y="Municipio",
            orientation="h", color="cor_marg", color_discrete_map="identity",
            labels={"Margem_Atual_BRL_Mi": "Margem (R$ Mi)", "Municipio": ""},
        )
        fig_m.add_vline(x=0, line_color="white", line_width=1)
        fig_m.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="white", showlegend=False,
            height=600,
            margin={"t": 20, "b": 0, "l": 0, "r": 0},
            hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        )
        st.plotly_chart(fig_m, width='stretch', config={'displayModeBar': False})

    custo_str = f"R$ {custo_ha:,.0f}/ha"
    if choque_frete > 0:
        custo_str += f" + choque de frete R$ {choque_frete:,.0f}/ha = R$ {custo_total_ha:,.0f}/ha"

    basis_caption = (
        f"Deságio: variável por município (base US$ {basis_usd:+.2f}, ajuste por distância ao terminal)"
        if basis_geo
        else f"Deságio: US$ {basis_usd:+.2f}/bu (uniforme) · Preço ao produtor: US$ {preco_efetivo_usd:.2f}/bu"
    )
    st.caption(
        f"Câmbio mínimo = custo total do município ÷ receita esperada em dólares (preço Chicago + deságio). "
        f"Verde: município com câmbio mínimo abaixo do câmbio atual (margem positiva). "
        f"Vermelho: câmbio mínimo acima do câmbio atual (prejuízo no cenário atual). "
        f"**Perfil aplicado:** {perfil_label} · "
        f"Custo: {custo_str} · Chicago: US$ {preco_cbot_usd:.2f}/bu · {basis_caption}."
    )

# --- ABA 4: RISCO HISTÓRICO ---
with tab4:
    _periodo_hist_str = (
        f"{fmt_mes_pt(df_cot.index.min())} a {fmt_mes_pt(df_cot.index.max())}"
    )
    st.subheader(f"Risco Histórico — {cultura_sel} ({_periodo_hist_str})")

    st.markdown(
        '<div class="context-box">'
        f"<b>O que mostra:</b> cada ponto é uma semana entre {_periodo_hist_str}, posicionada pelo "
        "<b>preço em Chicago</b> (eixo X) e pelo <b>câmbio</b> (eixo Y). "
        "<span style='color:#00d26a;font-weight:600'>Verde</span> = o produtor teria tido margem positiva naquela semana. "
        "<span style='color:#ff4b4b;font-weight:600'>Vermelho</span> = prejuízo. "
        "A curva tracejada é o <b>break-even</b> — acima dela o câmbio cobre o custo; abaixo, não. "
        "A estrela amarela é o cenário atual."
        "</div>",
        unsafe_allow_html=True,
    )

    df_ms_base = df_prod[(df_prod[cfg["qtd_col"]] > 0) & (df_prod[cfg["area_col"]] > 0)].copy()
    municipios_ms = sorted(df_ms_base["Municipio"].tolist())

    if cultura_sel == "Milho":
        st.markdown(
            '<div class="disclaimer">'
            "<b>Milho 2ª safra (safrinha):</b> o custo de referência abaixo "
            "(R$4.180/ha, Custo Operacional Total — COT — CONAB 2024/25) inclui arrendamento da terra "
            "e preparo de solo que, na prática, já foram pagos pela soja cultivada antes no mesmo campo. "
            "A decisão de plantar a safrinha envolve apenas os custos específicos da 2ª safra — "
            "sementes, fertilizantes, defensivos e operações mecanizadas próprias do milho. "
            "Use o slider para simular o custo que melhor representa essa realidade."
            "</div>",
            unsafe_allow_html=True,
        )

    col_ms1, col_ms2, col_ms3 = st.columns([1, 1, 1])
    with col_ms1:
        escopo_ms = st.radio(
            "Escopo:", ["Município", "Estado de Rondônia"], horizontal=True, key="escopo_ms",
            help="Município: margem por hectare usando produtividade local. Estado de Rondônia: média ponderada de todos os municípios produtores.",
        )
    with col_ms2:
        if escopo_ms == "Município":
            mun_ms = st.selectbox("Município:", municipios_ms, key="mun_ms")
        else:
            mun_ms = None
            st.caption("Média ponderada pela produção de todos os municípios produtores de Rondônia.")
    with col_ms3:
        custo_ha_ms = st.slider(
            f"Custo de produção — {cultura_sel}",
            min_value=2000.0, max_value=10000.0,
            value=CUSTO_HA_DEFAULT[cultura_sel], step=100.0,
            format="R$ %.0f/ha", key="custo_ms",
            help=f"Default CONAB: R$ {CUSTO_HA_DEFAULT[cultura_sel]:,.0f}/ha (COT safra 2024/25).",
        )

    # --- PARÂMETROS DE BREAK-EVEN ---
    bushels_t = BUSHELS_POR_TONELADA[cultura_sel]
    ticker_col_ms = cfg["ticker_col"]

    if escopo_ms == "Município":
        mun_row_ms = df_ms_base[df_ms_base["Municipio"] == mun_ms].iloc[0]
        prod_t_ha_ms = float(mun_row_ms[cfg["prod_col"]]) * fator / 1000
        basis_ms = float(basis_municipios.get(mun_ms, basis_usd))
        rota_ms = rota_municipal.get(mun_ms)
        if basis_geo and rota_ms:
            hub_nome_ms, km_ms, _ = rota_ms
            basis_legenda = f"deságio US$ {basis_ms:+.2f}/bu ({km_ms:.0f} km via {hub_nome_ms.split(' (')[0]})"
        else:
            basis_legenda = f"deságio US$ {basis_ms:+.2f}/bu"
        legenda_extra = f"Município: {mun_ms} · {prod_t_ha_ms*1000:,.0f} kg/ha ({perfil_label}) · {basis_legenda}"
    else:
        prod_aplicada_ms = df_ms_base[cfg["qtd_col"]] * fator
        prod_total_t_ms = float(prod_aplicada_ms.sum())
        area_total_ha_ms = float(df_ms_base[cfg["area_col"]].sum())
        prod_t_ha_ms = prod_total_t_ms / area_total_ha_ms if area_total_ha_ms > 0 else 0
        basis_mun_serie_ms = df_ms_base["Municipio"].map(basis_municipios).fillna(basis_usd)
        basis_ms = float((prod_aplicada_ms * basis_mun_serie_ms).sum() / prod_total_t_ms) if prod_total_t_ms > 0 else basis_usd
        basis_legenda = f"deságio ponderado US$ {basis_ms:+.2f}/bu" if basis_geo else f"deságio US$ {basis_ms:+.2f}/bu"
        legenda_extra = f"Rondônia — todos os municípios produtores · {prod_t_ha_ms*1000:,.0f} kg/ha médio ({perfil_label}) · {basis_legenda}"

    # --- DADOS HISTÓRICOS ---
    df_scatter = df_cot[[ticker_col_ms, "Dolar_PTAX"]].dropna().copy()
    df_scatter["cbot_usd"] = df_scatter[ticker_col_ms] / 100
    df_scatter["margem_ha"] = (
        prod_t_ha_ms * bushels_t * (df_scatter["cbot_usd"] + basis_ms) * df_scatter["Dolar_PTAX"]
        - custo_ha_ms
    )
    df_scatter["lucro"] = df_scatter["margem_ha"] >= 0
    n_lucro_hist = int(df_scatter["lucro"].sum())
    n_total_hist = len(df_scatter)
    pct_lucro_hist = n_lucro_hist / n_total_hist * 100 if n_total_hist > 0 else 0
    margem_atual_ha = (
        prod_t_ha_ms * bushels_t * (preco_cbot_usd + basis_ms) * dolar_atual - custo_ha_ms
    )

    # --- CURVA DE BREAK-EVEN ---
    _cbot_min = df_scatter["cbot_usd"].min() * 0.85
    _cbot_max = df_scatter["cbot_usd"].max() * 1.15
    _cbot_curve = np.linspace(_cbot_min, _cbot_max, 300)
    _denom = prod_t_ha_ms * bushels_t * (_cbot_curve + basis_ms)
    _dolar_be = np.where(_denom > 0, custo_ha_ms / _denom, np.nan)
    _dolar_min_hist = df_scatter["Dolar_PTAX"].min() * 0.85
    _dolar_max_hist = df_scatter["Dolar_PTAX"].max() * 1.15
    _mask_be = (_dolar_be >= _dolar_min_hist) & (_dolar_be <= _dolar_max_hist)

    # --- FIGURA ---
    fig_scatter = go.Figure()

    for _lucro_val, _cor, _nome in [(False, "#ff4b4b", "Prejuízo"), (True, "#00d26a", "Lucro")]:
        _df_sub = df_scatter[df_scatter["lucro"] == _lucro_val]
        if len(_df_sub) > 0:
            fig_scatter.add_trace(go.Scatter(
                x=_df_sub["cbot_usd"],
                y=_df_sub["Dolar_PTAX"],
                mode="markers",
                marker=dict(color=_cor, size=6, opacity=0.6),
                name=_nome,
                customdata=list(zip(
                    [str(d.date()) for d in _df_sub.index],
                    _df_sub["margem_ha"].round(0),
                )),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Chicago: US$ %{x:.2f}/bu<br>"
                    "Câmbio: R$ %{y:.2f}<br>"
                    "Margem estimada: R$ %{customdata[1]:,.0f}/ha<extra></extra>"
                ),
            ))

    if _mask_be.any():
        fig_scatter.add_trace(go.Scatter(
            x=_cbot_curve[_mask_be],
            y=_dolar_be[_mask_be],
            mode="lines",
            line=dict(color="white", width=2, dash="dash"),
            name="Break-even",
            hoverinfo="skip",
        ))

    fig_scatter.add_trace(go.Scatter(
        x=[preco_cbot_usd],
        y=[dolar_atual],
        mode="markers",
        marker=dict(color="#ffbd45", size=16, symbol="star", line=dict(color="white", width=1)),
        name="Cenário atual",
        hovertemplate=(
            f"<b>Cenário atual</b><br>"
            f"Chicago: US$ {preco_cbot_usd:.2f}/bu<br>"
            f"Câmbio: R$ {dolar_atual:.2f}<br>"
            f"Margem: R$ {margem_atual_ha:,.0f}/ha<extra></extra>"
        ),
    ))

    fig_scatter.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        xaxis_title=f"{cultura_sel} — preço em Chicago (US$/bu)",
        yaxis_title="Câmbio (R$/US$)",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        height=500,
        margin={"t": 10, "b": 60, "l": 0, "r": 0},
        hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
    )
    st.plotly_chart(fig_scatter, width='stretch', config={'displayModeBar': False})

    # --- KPIs ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Semanas com lucro",
        f"{n_lucro_hist} de {n_total_hist}",
        f"{pct_lucro_hist:.0f}% do período",
        help=f"Quantas semanas no período histórico ({_periodo_hist_str}) teriam resultado em margem positiva com o custo configurado.",
    )
    m2.metric(
        "Margem no cenário atual",
        f"R$ {margem_atual_ha:,.0f}/ha",
        help="Preço e câmbio atuais, com custo e deságio configurados.",
    )
    m3.metric(
        "Melhor semana histórica",
        f"R$ {df_scatter['margem_ha'].max():,.0f}/ha",
        help=f"Semana com maior margem no período {_periodo_hist_str}.",
    )
    m4.metric(
        "Pior semana histórica",
        f"R$ {df_scatter['margem_ha'].min():,.0f}/ha",
        help=f"Semana com menor margem no período {_periodo_hist_str}.",
    )

    # --- NARRATIVA ---
    if pct_lucro_hist >= 70:
        _frase1 = (
            f"<b>{pct_lucro_hist:.0f}%</b> das {n_total_hist} semanas analisadas resultariam em "
            f"margem positiva com o custo atual — histórico de resiliência neste nível de custo."
        )
    elif pct_lucro_hist >= 40:
        _frase1 = (
            f"<b>{pct_lucro_hist:.0f}%</b> das {n_total_hist} semanas analisadas resultariam em margem positiva — "
            f"alternância entre lucro e prejuízo indica sensibilidade alta a variações de preço e câmbio."
        )
    else:
        _frase1 = (
            f"Apenas <b>{pct_lucro_hist:.0f}%</b> das {n_total_hist} semanas analisadas resultariam em "
            f"margem positiva — o custo atual está acima do que o mercado histórico sustenta na maior parte do tempo."
        )

    _frase2 = (
        f"O cenário atual (★) está na zona de {'lucro' if margem_atual_ha >= 0 else 'prejuízo'} "
        f"— margem de <b>R$ {margem_atual_ha:,.0f}/ha</b>."
    )

    _frase_safrinha = ""
    if cultura_sel == "Milho":
        _frase_safrinha = (
            "<br><br><b>Por que o produtor planta mesmo com custo operacional completo negativo?</b> "
            "O milho 2ª safra ocupa o mesmo campo logo após a colheita da soja. "
            "Arrendamento e preparo de solo já foram pagos pela soja — "
            "a decisão de plantar envolve apenas os custos específicos da 2ª safra. "
            "Ajuste o slider de custo acima para simular esse cenário."
        )

    st.markdown(
        f'<div class="context-box">{_frase1}<br><br>{_frase2}{_frase_safrinha}</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        f"{legenda_extra} · Custo: R$ {custo_ha_ms:,.0f}/ha · "
        f"Curva tracejada = break-even (acima = câmbio cobre o custo; abaixo = prejuízo). "
        f"Estrela amarela = cenário atual. {n_total_hist} semanas analisadas."
    )

# --- ABA 5: SAZONALIDADE E VARIAÇÃO CAMBIAL INTRA-SAFRA ---
with tab5:
    st.subheader(f"Sazonalidade e Variação Cambial Intra-Safra — {cultura_sel}")

    # --- DADOS BASE ---
    _bt     = BUSHELS_POR_TONELADA[cultura_sel]
    _ticker = cfg["ticker_col"]

    # Janela de 10 anos: regime produtivo recente (Centro-Oeste/Norte dominante,
    # safrinha consolidada). Histórico mais antigo mistura regimes diferentes
    # de produção e logística — não é comparável diretamente.
    JANELA_ANOS_SZ = 10
    corte_sz = pd.Timestamp.now() - pd.DateOffset(years=JANELA_ANOS_SZ)

    df_sz_full = df_cot[[_ticker, "Dolar_PTAX"]].dropna().copy()
    df_sz = df_sz_full[df_sz_full.index >= corte_sz].copy()
    df_sz["preco_saca"] = (df_sz[_ticker] / 100 + basis_usd) * _bt * df_sz["Dolar_PTAX"] * 0.06
    df_sz["mes"] = df_sz.index.month
    df_sz["ano"] = df_sz.index.year
    n_anos = df_sz["ano"].nunique()
    anos_unicos = sorted(df_sz["ano"].unique())
    periodo_sz_str = (
        f"{fmt_mes_pt(df_sz.index.min())} a {fmt_mes_pt(df_sz.index.max())}"
    )

    MESES_PT = {
        1: "Janeiro",   2: "Fevereiro", 3: "Março",
        4: "Abril",     5: "Maio",      6: "Junho",
        7: "Julho",     8: "Agosto",    9: "Setembro",
        10: "Outubro",  11: "Novembro", 12: "Dezembro",
    }

    st.markdown(
        f'<div class="context-box">'
        f"<b>O que mostra:</b> duas análises complementares construídas sobre {periodo_sz_str} "
        f"de dados públicos de CBOT (Yahoo Finance) e PTAX (Banco Central — SGS série 1). "
        f"<b>(1) Índice sazonal</b> identifica em quais meses o preço efetivo recebido em "
        f"Rondônia historicamente fica acima ou abaixo da média anual — "
        f"método-padrão da economia agrícola que cancela o efeito da inflação por construção. "
        f"<b>(2) Variação cambial intra-safra</b> mostra, safra a safra, quanto o câmbio se moveu "
        f"entre o mês de plantio e o mês de colheita — um sinal de risco, não simulação de hedge."
        f"</div>",
        unsafe_allow_html=True,
    )

    # ================================================================
    # PARTE 1 — ÍNDICE SAZONAL (preço relativo à média móvel anual)
    # ================================================================
    st.markdown("### Índice sazonal — preço relativo à média anual")

    # Para cada observação, calcula a média móvel centrada de 52 semanas (~1 ano).
    # Índice sazonal = preço_t / MM52_t. Cancela inflação porque é razão dentro
    # do mesmo regime de preços. Acima de 1,00 = mês historicamente premiado;
    # abaixo de 1,00 = mês historicamente descontado.
    serie_preco = df_sz["preco_saca"].copy()
    mm52 = serie_preco.rolling(window=52, center=True, min_periods=26).mean()
    df_sz["indice_sazonal"] = (serie_preco / mm52)
    df_sz_idx = df_sz.dropna(subset=["indice_sazonal"])

    sz_stats = df_sz_idx.groupby("mes")["indice_sazonal"].agg(["mean", "std", "count"]).reset_index()
    sz_stats["mes_label"] = sz_stats["mes"].map(MESES_PT)
    sz_stats["upper"] = sz_stats["mean"] + sz_stats["std"]
    sz_stats["lower"] = sz_stats["mean"] - sz_stats["std"]
    sz_stats["delta_pct"] = (sz_stats["mean"] - 1.0) * 100

    melhor_mes = sz_stats.loc[sz_stats["mean"].idxmax()]
    pior_mes   = sz_stats.loc[sz_stats["mean"].idxmin()]

    fig_sz = go.Figure()

    fig_sz.add_trace(go.Scatter(
        x=list(sz_stats["mes_label"]) + list(sz_stats["mes_label"])[::-1],
        y=list(sz_stats["upper"]) + list(sz_stats["lower"])[::-1],
        fill="toself",
        fillcolor="rgba(0, 210, 106, 0.10)",
        line=dict(color="rgba(0,0,0,0)"),
        hoverinfo="skip",
        name="Dispersão (±1σ)",
        showlegend=True,
    ))

    fig_sz.add_trace(go.Scatter(
        x=sz_stats["mes_label"],
        y=sz_stats["mean"],
        mode="lines+markers",
        line=dict(color="#00d26a", width=2.5),
        marker=dict(size=9, color="#00d26a", line=dict(color="white", width=1.5)),
        name="Índice sazonal médio",
        customdata=np.array(sz_stats["delta_pct"]).reshape(-1, 1),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Índice: %{y:.2f}<br>"
            "vs média anual: %{customdata[0]:+.1f}%<extra></extra>"
        ),
    ))

    fig_sz.add_hline(
        y=1.0, line_dash="dash", line_color="#ffbd45", line_width=1.5,
        annotation_text="Média anual = 1,00",
        annotation_position="top right",
        annotation_font=dict(color="#ffbd45", size=11),
    )

    fig_sz.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        yaxis=dict(title="Índice sazonal (preço ÷ média móvel anual)", tickformat=".2f",
                   gridcolor="#2b2f3e"),
        xaxis=dict(title="", gridcolor="#2b2f3e"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="right", x=1),
        margin={"t": 40, "b": 60, "l": 0, "r": 0},
        height=380,
        hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
    )
    st.plotly_chart(fig_sz, width='stretch', config={'displayModeBar': False})

    delta_melhor_pct = (melhor_mes["mean"] - 1.0) * 100
    delta_pior_pct   = (pior_mes["mean"] - 1.0) * 100
    spread_pct       = (melhor_mes["mean"] / pior_mes["mean"] - 1.0) * 100

    st.markdown(
        f'<div class="context-box">'
        f"<b>Leitura:</b> nos últimos {n_anos} anos ({periodo_sz_str}), "
        f"<b>{melhor_mes['mes_label']}</b> foi o mês com maior preço relativo "
        f"({delta_melhor_pct:+.1f}% vs. média anual em torno dele), "
        f"e <b>{pior_mes['mes_label']}</b> foi o mês com menor preço relativo "
        f"({delta_pior_pct:+.1f}%). "
        f"O spread entre o melhor e o pior mês é de aproximadamente <b>{spread_pct:.1f}%</b>. "
        f"O sinal sazonal não é determinístico — a banda sombreada (±1 desvio padrão) mostra "
        f"que dentro do mesmo mês a dispersão entre safras é relevante. "
        f"Use isto como contexto histórico, não como previsão."
        f"</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        f"Método: para cada observação semanal, calcula-se o índice = preço_efetivo ÷ "
        f"média móvel centrada de 52 semanas. A média mensal desse índice cancela a "
        f"tendência inflacionária por construção (razão entre dois valores no mesmo regime de preços) — "
        f"é a abordagem-padrão da literatura de economia agrícola para sazonalidade de commodities. "
        f"Janela: últimos {JANELA_ANOS_SZ} anos para refletir o regime produtivo atual de Rondônia "
        f"(Cone Sul/Vilhena dominante, safrinha de milho consolidada). "
        f"Fórmula do preço efetivo: (CBOT ÷ 100 + basis US$ {basis_usd:+.2f}/bu) × {_bt:.4f} bu/t × PTAX × 0,06. "
        f"Fontes: CBOT via Yahoo Finance ({_ticker}); PTAX via Banco Central, SGS série 1."
    )

    # ================================================================
    # PARTE 2 — VARIAÇÃO CAMBIAL INTRA-SAFRA (não é hedge real)
    # ================================================================
    st.markdown("---")
    st.markdown("### Variação cambial entre plantio e colheita")

    CICLO_CULTURA = {
        "Soja":  {"mes_plantio": 9,  "mes_colheita": 2,
                  "desc_plantio": "Setembro", "desc_colheita": "Fevereiro",
                  "contexto": "plantio em setembro e colheita em fevereiro — ciclo padrão de Rondônia"},
        "Milho": {"mes_plantio": 2,  "mes_colheita": 6,
                  "desc_plantio": "Fevereiro", "desc_colheita": "Junho",
                  "contexto": "safrinha semeada em fevereiro logo após a colheita da soja, colhida em junho"},
    }
    ciclo = CICLO_CULTURA[cultura_sel]
    mes_plantio  = ciclo["mes_plantio"]
    mes_colheita = ciclo["mes_colheita"]

    st.markdown(
        f'<div class="context-box" style="border-left-color:#ffbd45;">'
        f"<b>Importante — esta análise NÃO simula hedge cambial real.</b> "
        f"Hedge real (NDF, futuro de dólar B3) trava o <b>câmbio futuro (forward)</b>, que embute "
        f"o diferencial de juros entre Selic e Fed Funds — historicamente positivo, ou seja, "
        f"o forward fica acima do PTAX spot. O que esta seção mostra é mais simples: "
        f"a <b>variação observada do PTAX entre o mês de plantio e o mês de colheita</b> de cada safra. "
        f"É um indicador de magnitude do risco cambial intra-safra, não simulação de operação financeira. "
        f"Para análise real de instrumentos de proteção, use cotações de NDF/futuro junto a uma mesa de hedge."
        f"</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        f"Contexto produtivo: a {cultura_sel.lower()} de Rondônia tem {ciclo['contexto']}. "
        f"Como o grão é precificado em dólar e o produtor recebe em reais, o movimento do "
        f"câmbio entre {ciclo['desc_plantio']} e {ciclo['desc_colheita']} altera diretamente "
        f"a receita em reais da safra."
    )

    resultados_intra = []
    for ano in anos_unicos:
        ano_plantio = ano if mes_colheita > mes_plantio else ano - 1
        df_plant = df_sz[(df_sz["ano"] == ano_plantio) & (df_sz["mes"] == mes_plantio)]
        df_colh  = df_sz[(df_sz["ano"] == ano) & (df_sz["mes"] == mes_colheita)]
        if df_plant.empty or df_colh.empty:
            continue

        ptax_plantio  = float(df_plant["Dolar_PTAX"].mean())
        ptax_colheita = float(df_colh["Dolar_PTAX"].mean())
        var_pct       = (ptax_colheita / ptax_plantio - 1.0) * 100

        resultados_intra.append({
            "ano_label": str(ano),
            "ptax_plantio": ptax_plantio,
            "ptax_colheita": ptax_colheita,
            "var_pct": var_pct,
        })

    if resultados_intra:
        df_h = pd.DataFrame(resultados_intra)
        n_alta  = int((df_h["var_pct"] > 0).sum())
        n_baixa = int((df_h["var_pct"] < 0).sum())
        n_tot   = len(df_h)
        pct_alta = n_alta / n_tot * 100 if n_tot > 0 else 0
        var_media = df_h["var_pct"].mean()
        var_abs_media = df_h["var_pct"].abs().mean()

        # Barras: variação % do PTAX entre plantio e colheita
        df_h["cor"] = df_h["var_pct"].apply(lambda v: "#00d26a" if v > 0 else "#ff4b4b")

        fig_v = go.Figure()
        fig_v.add_trace(go.Bar(
            x=df_h["ano_label"],
            y=df_h["var_pct"],
            marker_color=df_h["cor"],
            customdata=df_h[["ptax_plantio", "ptax_colheita"]].values,
            hovertemplate=(
                "<b>Safra %{x}</b><br>"
                f"PTAX em {ciclo['desc_plantio']}: R$ %{{customdata[0]:.2f}}<br>"
                f"PTAX em {ciclo['desc_colheita']}: R$ %{{customdata[1]:.2f}}<br>"
                "Variação: <b>%{y:+.1f}%</b><extra></extra>"
            ),
            name="Variação PTAX intra-safra",
            showlegend=False,
        ))

        fig_v.add_hline(y=0, line_color="white", line_width=1)

        fig_v.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="white",
            yaxis=dict(title="Variação % do PTAX (colheita ÷ plantio − 1)",
                       tickformat="+.1f", ticksuffix="%", gridcolor="#2b2f3e"),
            xaxis=dict(title="Safra (ano da colheita)"),
            margin={"t": 30, "b": 0, "l": 0, "r": 0},
            height=360,
            bargap=0.25,
            hoverlabel=dict(bgcolor="#1e2130", bordercolor="#00d26a", font=dict(color="#ffffff")),
        )
        st.plotly_chart(fig_v, width='stretch', config={'displayModeBar': False})

        st.markdown(
            f'<div class="context-box" style="border-left-color:#808495;">'
            f"<b>Leitura:</b> em {n_alta} de {n_tot} safras analisadas ({pct_alta:.0f}%), "
            f"o câmbio <b>subiu</b> entre {ciclo['desc_plantio']} e {ciclo['desc_colheita']} — "
            f"quem manteve a receita em dólar (sem fixar câmbio antes) recebeu mais reais. "
            f"Nas outras {n_baixa} safras, o câmbio caiu no período. "
            f"A variação média (com sinal) foi de <b>{var_media:+.1f}%</b>; "
            f"a variação absoluta média foi de <b>{var_abs_media:.1f}%</b>, "
            f"que é o tamanho típico do risco cambial intra-safra para esta cultura. "
            f"Este número justifica por que produtores com dívida ou custo fixo elevado "
            f"buscam instrumentos de fixação cambial — não para ganhar em média, "
            f"mas para reduzir variância e poder honrar compromissos."
            f"</div>",
            unsafe_allow_html=True,
        )

        v1, v2, v3, v4 = st.columns(4)
        v1.metric("Safras analisadas", f"{n_tot}",
                  help=f"Anos com dados de PTAX em {ciclo['desc_plantio']} e {ciclo['desc_colheita']}.")
        v2.metric("Câmbio subiu", f"{n_alta} safras ({pct_alta:.0f}%)",
                  help="Anos em que o PTAX médio do mês de colheita foi maior que o do mês de plantio.")
        v3.metric("Variação média", f"{var_media:+.1f}%",
                  help="Média (com sinal) das variações % do PTAX entre plantio e colheita.")
        v4.metric("Variação típica", f"±{var_abs_media:.1f}%",
                  help="Média absoluta das variações — magnitude do risco cambial por safra.")

        st.caption(
            f"Método: variação % = PTAX médio em {ciclo['desc_colheita']} ÷ PTAX médio em "
            f"{ciclo['desc_plantio']} − 1, calculada para cada safra. "
            f"O preço CBOT não entra neste gráfico — a análise isola exclusivamente o componente cambial. "
            f"Janela: últimos {JANELA_ANOS_SZ} anos. "
            f"Fontes: PTAX — Banco Central, SGS série 1; CBOT — Yahoo Finance."
        )
    else:
        st.info("Dados históricos insuficientes para o ciclo desta cultura na janela selecionada. "
                "Execute `python coleta_mercado.py` para atualizar.")

# --- RODAPÉ ---
st.markdown("---")
st.caption(
    "Dados de produção: IBGE/PAM 2023 (tabela 1612) via API SIDRA. "
    "Cotações: Bolsa de Chicago e câmbio via Yahoo Finance. "
    "Custo de produção é referencial e não capta variações regionais — ajuste o slider conforme contexto. "
    "Veja METODOLOGIA.md para detalhes técnicos."
)
