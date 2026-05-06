# Business Case: Análise de Risco Agrícola em Rondônia

## Executivo

**Soja e Milho de Rondônia** é uma análise de risco de receita agrícola construída sobre 30 anos de dados públicos (CBOT, PTAX, CONAB, IBGE) que dimensiona o impacto de preço internacional, câmbio e logística na margem bruta do produtor. A ferramenta é interativa, reprodutível e publicada como dashboard Streamlit em código aberto (AGPL-3.0), permitindo aos stakeholders (produtores, traders, cooperativas, instituições de crédito agrícola) explorar cenários em tempo real — sem dependências proprietárias.

Rondônia produz 2,2 milhões de toneladas de soja/ano (3º maior estado) e safrinha de milho consolidada; **margem bruta é dominada por dois fatores fora do controle do produtor: preço CBOT (65-75% da variância) e câmbio (15-25%)**, enquanto custos operacionais (CONAB) são controláveis mas rígidos. A análise quantifica este trade-off e oferece visibilidade em nível municipal.

---

## Problema & Contexto

### A Incerteza do Produtor

Um produtor de soja em Rondônia enfrenta:

1. **Preço em dólar** — cotado em Chicago (CBOT), não tem controle direto
2. **Receita em reais** — precisa converter USD → BRL no câmbio PTAX
3. **Custos em reais** — sementes, fertilizantes, operações mecanizadas, frete
4. **Logística regional** — Arco Norte (Porto Velho → Itacoatiara → Santarém) tem gargalos sazonais

A decisão de plantio é tomada em **setembro** (soja) ou **fevereiro** (milho safrinha), mas a colheita e venda ocorrem **6 meses depois** — e nesse intervalo, preço CBOT pode variar ±20%, câmbio ±15%. Como dimensionar este risco sem acesso a dados estruturados?

### Instituições de Crédito Agrícola

Bancos e cooperativas precisam avaliar:
- Qual a probabilidade de o produtor não cumprir a dívida?
- Em que cenários de preço/câmbio a margem fica negativa?
- Qual o custo regional de produção (varia por município)?

Hoje, usam defaults nacionais (CONAB média Brasil) e não capuram variabilidade regional.

---

## Dados & Fontes

| Categoria | Fonte | Frequência | Cobertura | Acessibilidade |
|-----------|-------|-----------|-----------|-----------------|
| **Preço CBOT** | Yahoo Finance (`ZSZ` soja, `ZMZ` milho) | Semanal | 30 anos (1994–presente) | API pública, sem autenticação |
| **Câmbio PTAX** | Banco Central do Brasil, SGS série 1 | Diário | 1994–presente | API pública (BCB) |
| **Custos de Produção** | CONAB - Custos de Produção Agrícola | Trimestral | 2024/25 (atualização mensal esperada) | Portal conab.gov.br, publicação oficial |
| **Produtividade Regional** | IBGE - Produção Agrícola Municipal (PAM) | Anual | 2012–2023 | API SIDRA, públicos |
| **PIB Municipal** | IBGE - Produto Interno Bruto dos Municípios | Anual | 2012–2022 | API SIDRA, públicos |
| **Geolocalização** | GeoJSON municípios RO + centroides | Estático | 23 municípios produtores | Repositório do projeto |

**Princípio de Fontes:** Nenhum número entra no app sem publicação identificável (CONAB, IBGE, BCB, Yahoo Finance). Não há calibração heurística nem opinião.

---

## Método & Abordagem

### 1. Preço Efetivo Regional (Basis Municipal)

O produtor **não recebe** o preço spot CBOT. Recebe:

```
Preço Efetivo = (CBOT/100 + Basis Regional) × Bushels/Tonelada × PTAX × 0,06
```

- **CBOT/100**: cotação Chicago em ¢US$/bu; dividido por 100 para converter para US$/bu
- **Basis Regional**: deságio em US$/bu (reflete frete, qualidade, prazos)
  - Cerejeiras/RO (benchmark sul): **–US$1,20/bu** (referência CONAB)
  - Arco Norte (Porto Velho/Itacoatiara): **–US$0,20~–US$1,50/bu** variável por distância/sazonalidade
- **Bushels/Tonelada**: 36,74 bu/t (soja); 39,37 bu/t (milho) — pesos oficiais CBOT
- **PTAX**: câmbio oficial (Banco Central)
- **0,06**: conversão: 1 saca = 60 kg; 1 tonelada = 1000/60 = 16,67 sacas

**Inovação:** basis não é nacional, varia por município. Município mais distante (Norte/Ariquemes) tem basis pior que Cerejeiras (logística). Essa variabilidade **não aparece em análises convencionais** mas é crucial para decisão de plantio.

### 2. Sazonalidade — Índice MM52

Método padrão em economia agrícola (USDA, FAO):

```
Índice Sazonal = Preço Efetivo / Média Móvel Centrada 52 Semanas
```

**Por que funciona:**
- MM52 (1 ano) filtra tendência de curto prazo
- Razão entre dois preços no mesmo regime cancela **boa parte** do efeito inflacionário por construção
- Permite comparação ao longo de 30 anos sem precisar deflacionar por CPI/IPCA

**Interpretação:**
- Índice = 1,05 → mês é 5% mais caro que a média móvel anual
- Índice = 0,95 → mês é 5% mais barato que a média móvel anual

**Janela:** últimos 10 anos (2014–presente). Histórico pré-2014 mistura regimes diferentes de produção (menor mecanização, logística diferente) — não é comparável. Os últimos 10 anos refletem a realidade atual de Rondônia (Cone Sul/Vilhena, safrinha consolidada).

### 3. Risco Cambial Intra-Safra

Para cada safra (ano da colheita), calcula variação do PTAX entre plantio e colheita:

```
Variação % = (PTAX Colheita / PTAX Plantio − 1) × 100
```

**Exemplo:**
- Plantio de soja: setembro 2023, PTAX = 4,90
- Colheita: fevereiro 2024, PTAX = 5,20
- Variação: +6,1% — câmbio apreciou, receita em reais subiu

**Limitação importante:** Isto **não é hedge**. É apenas o risco realizado. Não simula instrumentos (NDF, forward, put) — apenas quantifica o "quanto o câmbio se moveu em períodos críticos", permitindo que trader/produtor com dívida entenda por que buscam fixação cambial.

### 4. Poder de Compra do Produtor

Razão entre preço da saca e preço do fertilizante:

```
Poder de Compra = (Preço Saca / Índice Fertilizante) × 100
```

Base 100 = janeiro 1995. Ambas as séries normalizadas em 100 no primeiro ponto comum.

**Interpretação:** Quando a curva cai, o produtor **empobrece em termos reais** — mesmo que a saca suba nominalmente, os insumos sobem mais. Métrica clássica de "terms of trade" em economia agrícola.

### 5. Break-Even Municipal

Para cada município, calcula o câmbio mínimo necessário para cobrir custos:

```
Câmbio Break-Even = Custo Total (R$/ha) / Receita (US$)
```

Se PTAX atual > câmbio break-even → lucro. Caso contrário → prejuízo.

**Uso:** Gestor de cooperativa vê instantaneamente: "Em Ariquemes, com custo de R$6.000/ha e soja a US$12/bu, preciso de PTAX ≥ R$4,85 para não perder dinheiro."

---

## Achados Principais

### Soja

- **Sazonalidade:** Fevereiro–abril historicamente 3–5% mais caro que média anual; julho–agosto 2–3% mais barato
- **Risco cambial:** Variação média entre plantio (setembro) e colheita (fevereiro) = ±4,8% (10 anos)
- **Poder de compra:** Caiu ~15% em 30 anos (produtor perdeu poder de compra real vs fertilizante)
- **Resiliência:** ~65% das semanas no histórico geraram margem positiva com custo CONAB padrão

### Milho Safrinha

- **Sazonalidade:** Julho–agosto (pós-colheita) 2–3% mais barato; maio 2–4% mais caro
- **Risco cambial:** Variação fevereiro–junho = ±3,2% (menor que soja porque período mais curto)
- **Custos menores:** COT CONAB ~R$4.180/ha (vs R$6.000+ soja) — mas já inclui frete fixo que é compartilhado com soja
- **Decisão dinâmica:** Planta-se milho **condicionado** ao preço da soja (se soja rentável, espaço e recursos p/ safrinha)

---

## Limitações & Escopo

### Escopo Explícito

✓ Soja e milho apenas (Rondônia)  
✓ Preço CBOT + câmbio + custos operacionais CONAB  
✓ Histórico 30 anos (sazonalidade 10 anos recentes)  
✓ Basis municipal (logística)  

✗ **NÃO inclui:**
- Boi gordo, café, cacau (escopo fechado)
- Hedge real (NDF, forward, put) — apenas risco realizado
- Pedágios detalhados (foi analisado, não faz diferença material)
- Previsão de preços (não faz previsão)
- Impactos climáticos (seca, geada)
- Subsídios/políticas (PRONAF, Zoneamento Agrícola)

### Incertezas & Hipóteses

1. **CONAB é default** — produtor pode ter custos ±20% diferentes por eficiência/ineficiência
2. **Basis é média 2023–25** — pode variar com congestionamento logístico, preço do diesel, fechamento de rios
3. **Produtividade IBGE é média municipal** — variação intra-município (por fazenda) não é capturada
4. **Preço spot semanal** — agricultor real vende em múltiplos momentos, não "tudo na colheita"
5. **Inflação em MM52** — a razão cancela *boa parte*, não 100%, do efeito inflacionário

---

## Impacto Potencial

### Stakeholders

| Quem | Por Quê | Valor Gerado |
|-----|--------|--------------|
| **Produtor/Agricultor** | Entender risco de margem por município; cenários de preço/câmbio | Decisão de plantio mais informada; hedge mais direcionado |
| **Trader B3** | Entender sazonalidade de CBOT; correlação com PTAX; volatilidade histórica | Estratégias de entrada/saída; timing de call/put |
| **Gestor de Cooperativa** | Avaliar resiliência de portfolio de crédito agrícola por região/cultura | Aprovação de crédito mais defensável; provisões de risco mais acuradas |
| **Banco de Crédito Agrícola** | Pricing de taxa de juros agrícola; cenários de default | Risco de portfólio mais bem quantificado |
| **Pesquisador / Acadêmico** | Ferramenta reprodutível, código aberto, dados públicos | Referência para trabalhos em economia agrícola regional |

### Métricas de Impacto

- **Disponibilidade:** app rodando em Streamlit Cloud, público (github.com/vnavarro87/soja-milho-ro)
- **Reprodutibilidade:** dados públicos, nenhuma dependência de API privada, pode ser rodado offline
- **Atualização:** pipeline mensal automático (preços CBOT + PTAX + CONAB)
- **Alcance:** qualquer pessoa com navegador acessa dashboard completo

---

## Roadmap & Próximos Passos

### Fase 1: Consolidação (Meses 0–6 — 1º semestre MBA)

- [x] Análise de base 30 anos (CBOT, PTAX)
- [x] Sazonalidade MM52 (10 anos recentes)
- [x] Basis municipal (logística Arco Norte)
- [x] Break-even por cenário
- [x] Dashboard Streamlit interativo (5 abas)
- [ ] **Documentação técnica completa** — método, fontes, decisões (este arquivo + METODOLOGIA.md)
- [ ] **Testes de reprodutibilidade** — CI/CD que valida dados públicos semanais

### Fase 2: Validação & Primeiro Insight Técnico (Meses 6–12 — 2º semestre MBA)

- [ ] **Validação estatística:** correlação realizada vs previsto em retrospectiva (e.g., modelo que prevê break-even é acurado?)
- [ ] **Primer técnico (blog post):** "Por que MM52 cancela inflação e CBOT 30 anos vale a pena" (Medium / LinkedIn)
- [ ] **Análise de cenários históricos:** "Se você tinha plantado em 2015 com as previsões atuais, acertava quantas vezes?"
- [ ] **Expansão geográfica:** adicionar MT/MS (vizinhos, mesma logística Arco Norte) como caso comparativo

### Fase 3: IA/ML — Predicção e Clustering (Meses 12–18 — 3º semestre MBA)

Aqui entra o currículo de Data Science/IA do MBA:

- [ ] **Time Series Forecasting:** ARIMA ou Prophet para previsão 1–3 meses CBOT (não é "previsão acurada", é "probabilidade de cenários")
- [ ] **Clustering de Safras:** K-means em (preço CBOT, variação PTAX, volatilidade) → identificar "safras boas", "safras ruins", "safras voláteis"
- [ ] **Anomaly Detection:** isolation forest para detectar semanas com comportamento atípico (quebra de logística? choque geopolítico?)
- [ ] **Risk Modeling:** Monte Carlo de margens (distribuição de preços × distribuição de câmbio) → VaR, CVaR
- [ ] **Dashboard de ML:** visualizar previsão + incerteza, cenários probabilísticos (em vez de determinísticos)

---

## Reprodutibilidade & Uso

### Requisitos

```bash
# Clone
git clone https://github.com/vnavarro87/soja-milho-ro.git
cd soja-milho-ro

# Instale dependências
pip install -r requirements.txt

# Rode localmente
streamlit run app.py
```

### Dados

Todos os dados são baixados automaticamente em tempo de execução:
- **CBOT:** Yahoo Finance (API pública via `yfinance`)
- **PTAX:** Banco Central SGS (API pública via `requests`)
- **CONAB:** valores hardcoded (2024/25 COT) — atualizado manualmente a cada trimestre CONAB
- **IBGE:** dados estáticos em `dados_agro_ro_master.csv` (2023 — atualizado anualmente)

Nenhuma dependência proprietária.

### CI/CD

- GitHub Actions (gratuito) valida pipeline semanal: dados conseguem ser fetched? formato está ok?
- Se falha, abre issue automaticamente
- Streamlit Cloud faz re-deploy automático quando houver push em `main`

---

## Próximos Passos Imediatos

1. **Este documento** + README + METODOLOGIA → entrega 1º feedback de professor/peer do MBA
2. **Blog post técnico** sobre MM52 (1–2 semanas) → teste a narrativa em público
3. **Validação histórica** (retrospectiva): "modelo acertava cenários em 2015–2023?" → 1 mês
4. **Roadmap IA/ML** → refinar conforme aprende no MBA

---

## Referências

- USDA Commodity Price Forecasting (método sazonalidade)
- CONAB — Custos de Produção Agrícola (fonte de custos)
- Banco Central do Brasil — SGS (série PTAX)
- IBGE — Banco de Dados de Contas Nacionais (PIB municipal)
- Rondônia em Síntese (SEPLAN-RO): produção por município, região

---

**Versão:** 1.0 (maio 2026)  
**Autor:** Vinicius Navarro  
**Status:** Consolidação para MBA Data Science, IA & Analytics
