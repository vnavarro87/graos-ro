# Soja e Milho de Rondônia — Apresentação Técnica

> Análise de risco de receita agrícola com dados públicos (CBOT, PTAX, CONAB, IBGE) — código aberto, reproduzível, deploy gratuito.

---

## TL;DR

Este app responde **uma pergunta concreta**: *"para o produtor de soja e milho em Rondônia, o cenário atual de mercado cobre o custo? Qual o risco?"*

Tudo que está no app é derivado de **dados públicos identificáveis** (sem heurística, sem opinião). A análise é **descritiva, não prescritiva** — não recomenda ações, descreve estado dos dados.

5 abas, 9 insights catalogados, 30 anos de histórico CBOT + PTAX, 23 municípios produtores, 4 níveis de validação automatizada de sanidade dos dados.

---

## Sumário

- [A pergunta que move o app](#a-pergunta-que-move-o-app)
- [Stack & princípios](#stack--princípios)
- [Walkthrough das 5 abas](#walkthrough-das-5-abas)
  - [Aba 1 — Preços e Câmbio](#aba-1--preços-e-câmbio)
  - [Aba 2 — Simulador de Receita](#aba-2--simulador-de-receita)
  - [Aba 3 — Risco Cambial](#aba-3--risco-cambial)
  - [Aba 4 — Cenários Históricos](#aba-4--cenários-históricos)
  - [Aba 5 — Sazonalidade e Variação Cambial Intra-Safra](#aba-5--sazonalidade-e-variação-cambial-intra-safra)
- [Catálogo de insights](#catálogo-de-insights)
- [Limitações honestas](#limitações-honestas)
- [Como usar em uma decisão real](#como-usar-em-uma-decisão-real)
- [Para quem isto é útil](#para-quem-isto-é-útil)

---

## A pergunta que move o app

O produtor de soja em Rondônia opera em **três regimes ao mesmo tempo:**

1. **Preço cotado em dólar** na bolsa de Chicago (CBOT) — não tem controle.
2. **Receita em reais** — depende do câmbio PTAX no dia da venda.
3. **Custos em reais** — sementes, fertilizantes, operações, frete, arrendamento.

A decisão de plantio é tomada em **setembro** (soja) ou **fevereiro** (milho safrinha). A colheita e a venda ocorrem **6 meses depois**. Nesse intervalo, CBOT pode variar ±20%, câmbio ±15%. **Como dimensionar esse risco sem acesso a dados estruturados?**

O app responde essa pergunta para **23 municípios produtores de Rondônia**, com escalonamento de cenários e validação contra 30 anos de histórico.

---

## Stack & princípios

### Stack

- **Python · Streamlit · Plotly**
- **yfinance** — cotações CBOT (Yahoo Finance)
- **BCB SGS** — PTAX série 1, IPA-OG fertilizantes série 7456
- **IBGE/SIDRA** — Produção Agrícola Municipal 2023 (tabelas 1612 e 1613)
- **CONAB** — Custo Operacional Total (COT) safra 2024/25

### Princípios consolidados (auditoria 3-ângulos: hater · banker · agronegócio)

- **Nada sem fonte** — toda métrica tem publicação identificável
- **Linguagem descritiva, não prescritiva** — descreve estado, não recomenda ação
- **Esforço enxuto** — features que não cabem em 1–3h ficam fora
- **Curadoria > expansão** — refinar antes de adicionar
- **Defensibilidade prática** — número desatualizado por scraping frágil é pior que valor fixo bem documentado
- **Coerência** — não contradiz decisões já justificadas em iteração anterior

---

## Walkthrough das 5 abas

### Aba 1 — Preços e Câmbio

**O que mostra:** histórico de cotação CBOT (verde) e PTAX (amarelo) sobrepostos. Janela ajustável (5 ou 10 anos).

**Insight central:** o produtor brasileiro recebe em reais, mas sua receita é função multiplicativa de **dois fatores fora do controle dele** — preço CBOT × câmbio. Ver os dois juntos historicamente já mostra que **o melhor ano para preço pode ser o pior para câmbio** e vice-versa.

**Sub-seção: Índice de Poder de Compra do Produtor**
Razão entre preço da saca (R$) e índice de fertilizantes (FGV/IPA-OG). Quando cai, o produtor empobrece em termos reais — mesmo que a saca esteja subindo nominalmente, o fertilizante sobe mais. Métrica clássica de "terms of trade" da economia agrícola.

> 📷 **Screenshot sugerido:** gráfico histórico 10 anos com linha verde + amarela tracejada, depois o índice de Poder de Compra mostrando queda real de longo prazo.

> 🔗 **Post relacionado:** [BLOG_POST_MM52](drafts/BLOG_POST_MM52.md) — explica por que razões cancelam inflação por construção (mesmo princípio aplicado aqui).

---

### Aba 2 — Simulador de Receita

**O que mostra:** sliders para CBOT e câmbio + mapa coroplético de receita estimada por município no cenário simulado.

**Insight central — basis municipal:** o produtor **não recebe** o preço spot CBOT. Recebe `(CBOT + basis) × bushels × dólar`, onde `basis` é o deságio até o porto (frete, qualidade, prazo). E o **basis varia por município** — Vilhena tem basis melhor que Pimenteiras porque Vilhena tem mais opções de hub logístico (Rondonópolis Rumo + Madeira). O toggle "basis variável por município" na sidebar mostra isso.

**Insight derivado — concentração geográfica:** o caption sob o mapa quantifica quanto do total estadual estimado vem dos top 5 municípios. Em soja, geralmente 60–70% — exposição alta a choque local (estiagem do Madeira, fechamento da BR-364).

**UX:** botão "↺ Voltar ao mercado atual" para resetar sliders depois de simular cenário extremo.

> 📷 **Screenshot sugerido:** mapa colorido com cenário simulado adverso (CBOT baixo + dólar baixo) — mostra municípios escurecendo para receita zero/baixa.

---

### Aba 3 — Risco Cambial

**O que mostra:** dois gráficos lado a lado por município —
- (esq.) **câmbio mínimo** para cobrir custo (break-even em R$/US$)
- (dir.) **margem absoluta** estimada no cenário atual (em R$ Mi)

Verde = positivo, vermelho = prejuízo. Slider de **choque de frete adicional** simula cenários adversos (seca no Madeira, alta de diesel).

**Insight central — Volume ≠ resiliência:**

> *O município que mais produz não é necessariamente o de maior margem por hectare. Dois fatores definem quem aguenta cenário adverso: produtividade (kg/ha) e basis logístico (deságio até o porto). O modelo aplica o mesmo custo CONAB a todos os municípios, então a margem por hectare varia só com receita: produtividade × (CBOT + basis) × câmbio.*

**Exemplo prático (auditado):** **Pimenteiras do Oeste** lidera em volume (197 mil t) mas tem produtividade de **3.460 kg/ha** — média. Está a **557 km do porto Madeira** — basis logístico mais negativo. No cenário neutro, fica próxima do break-even. **Chupinguaia, com 3.840 kg/ha (+11%), tem 145% mais margem por hectare.**

> 📷 **Screenshot sugerido:** as duas barras lado a lado, com Pimenteiras destacada em vermelho enquanto Chupinguaia/Cerejeiras em verde.

> 🔗 **Post potencial:** "O paradoxo do produtor #1" — desconstrói "ranking de volume" usando este exato caso.

---

### Aba 4 — Cenários Históricos

**Composta de duas seções:**

#### 4.1 Risco Histórico (scatter)

Cada ponto é uma semana entre Jan/1995 e hoje. Verde = produtor teria tido margem positiva naquela semana com o custo configurado. Vermelho = prejuízo. **Estrela amarela** = cenário atual posicionado no histórico.

**Insight central:** quantifica resiliência histórica. Por exemplo: *"com custo CONAB de R$ 6.012/ha, em 78% das semanas dos últimos 30 anos a soja teria gerado margem positiva no município X"*.

#### 4.2 Matriz de Sensibilidade Câmbio × CBOT

**Heatmap** com câmbio nas linhas e CBOT nas colunas. Cada célula = margem em R$/ha para aquela combinação. Borda branca destaca o cenário atual.

**Eixos auto-calibrados pelos últimos 10 anos** de PTAX (BCB) e CBOT (Yahoo Finance). Suplemento textual: "câmbio mínimo (break-even) por nível de CBOT".

**Insight central:** ferramenta de **mesa de crédito agro** (Itaú BBA, Rabobank, BTG Pactual Agro). Sliders mostram um cenário; **matriz mostra a paisagem completa de risco em uma única visualização**. Onde está a fronteira entre lucro e prejuízo? Quão sensível é a margem a cada R$ 0,10 no câmbio?

> 📷 **Screenshot sugerido:** heatmap completo + caption com "câmbio mínimo por CBOT" em destaque.

> 🔗 **Post potencial:** "Como uma matriz de sensibilidade resume um modelo de risco" — comparação com modo "slider único" tradicional.

---

### Aba 5 — Sazonalidade e Variação Cambial Intra-Safra

#### 5.1 Índice sazonal MM52

Para cada observação semanal, calcula `índice = preço efetivo ÷ média móvel centrada de 52 semanas`. A média mensal desse índice cancela a tendência inflacionária **por construção** (razão entre dois preços no mesmo regime).

Janela: últimos 10 anos. Exibe banda ±1σ para mostrar dispersão (não é determinístico).

**Insight central:** método-padrão de economia agrícola para sazonalidade de commodities. Permite responder: *"em quais meses o preço efetivo recebido em RO historicamente fica acima da média?"* — sem precisar deflacionar nada externo.

#### 5.2 Variação Cambial Intra-Safra

Para cada safra, mostra a variação % do PTAX entre o mês de plantio e o mês de colheita.

**Importante (limitação explícita):** isto **não é hedge**. É a variação realizada do câmbio no período crítico. Não simula NDF, forward ou put — apenas quantifica o tamanho típico do risco cambial intra-safra. A variação absoluta média é o que justifica produtores buscarem fixação cambial — não para ganhar em média, mas para reduzir variância.

> 📷 **Screenshot sugerido:** índice sazonal com banda de dispersão + barras de variação cambial safra a safra.

> 🔗 **Post relacionado:** [BLOG_POST_MM52](drafts/BLOG_POST_MM52.md).

---

## Catálogo de insights

Cada um pode virar post próprio, slide de carrossel, ou bloco de apresentação.

| # | Insight | Onde no app | Status |
|---|---------|-------------|--------|
| 1 | **MM52 cancela inflação por construção** — método padrão de sazonalidade | Aba 5 parte 1 | Draft pronto |
| 2 | **Engenharia de confiança** — identidade física `Qtd ≈ Área × Produtividade` valida dados públicos | `validate_data.py` | Draft pronto |
| 3 | **Volume ≠ resiliência** — Pimenteiras é #1 em volume mas frágil; Chupinguaia tem +145% margem/ha | Aba 3 caption | Confirmado, escrever |
| 4 | **Basis municipal** — logística do Arco Norte muda receita por município | Aba 2 sidebar toggle | Ideia |
| 5 | **Risco cambial intra-safra ≠ hedge** — quantificar magnitude, não simular instrumento | Aba 5 parte 2 | Ideia |
| 6 | **Matriz de Sensibilidade** — paisagem completa de risco vs slider único | Aba 4 parte 2 | Ideia |
| 7 | **Concentração geográfica** — top 5 municípios = X% da receita; choque local afeta o agregado | Aba 2 caption | Ideia |
| 8 | **Choque de frete** — simular fechamento BR-364 ou estiagem do Madeira | Aba 3 slider | Ideia |
| 9 | **Poder de compra** — saca/fertilizante revela perda real de longo prazo | Aba 1 sub-seção | Ideia |

**9 posts em 18 meses = ritmo de 1 a cada 2 meses.** Sustentável.

---

## Limitações honestas

O app não é uma calculadora financeira para decisão operacional. **Nunca foi.**

- ❌ **Não é simulação de hedge.** A análise de variação cambial intra-safra mostra magnitude do risco, não simula NDF/forward/put.
- ❌ **Não recomenda ação.** Não há "compre/venda/trave" no app. Só descrição de estado dos dados.
- ❌ **Custos uniformes.** O modelo aplica o mesmo COT CONAB (Cerejeiras p/ soja, Cone Sul p/ milho) a todos os municípios. Variações intra-RO existem mas não há fonte pública municipalizada.
- ❌ **Basis é estimativa setorial.** Defaults da média 2023–25 (USDA GAIN, CONAB Logística, ABIOVE). Trader real tem contratos privados melhores.
- ❌ **Defasagem nos dados.** PAM/IBGE 2023; PIB municipal IBGE só até 2021 (motivo pelo qual descartamos cruzamento com PIB Agro — viés temporal).
- ❌ **Yahoo Finance sem SLA** para CBOT — pode quebrar sem aviso. Substituto natural: Bloomberg/Refinitiv (pago).

**A honestidade dessas limitações é parte do projeto.** O que se ganha na análise é exatamente o que se ganha quando o método é defensável — não quando o resultado é acurado.

---

## Como usar em uma decisão real

> *Caso hipotético: produtor de Cerejeiras avaliando se planta safrinha de milho 2025/26.*

1. **Aba 1** → vê histórico CBOT do milho últimos 10 anos. Está em US\$ 4,50/bu hoje, abaixo da média de 5,20.
2. **Aba 2** → simula receita com CBOT US\$ 4,50 + dólar R\$ 5,30 + basis −0,50. Mapa mostra Cerejeiras gerando R\$ X Mi de receita. Caption alerta: top 5 municípios concentram 68% — Cerejeiras dependendo de oscilação de mercado.
3. **Aba 3** → vê seu município no break-even chart. Cerejeiras em verde — câmbio atual cobre custo. Mas com choque de frete simulado (R\$ +500/ha por estiagem do Madeira), entra em vermelho. Caption "Volume não é resiliência" reforça que isto é margem apertada, não inviabilidade.
4. **Aba 4** → no scatter histórico, vê estrela amarela (cenário atual) próxima da curva tracejada de break-even. Em 65% das semanas dos últimos 10 anos teria havido margem positiva nesse custo. Na matriz de sensibilidade, identifica que com CBOT US\$ 5 e dólar R\$ 5,50, sai com folga de ~R\$ 600/ha.
5. **Aba 5** → vê que historicamente maio é o mês mais "premiado" para venda de milho safrinha. Variação cambial entre fev (plantio) e jun (colheita) tem dispersão típica de ±3,2%.

**Conclusão prática (do produtor, não do app):** decisão de plantar ou não envolve mais variáveis (capital de giro, contrato de fornecimento, sequência da safra de soja). O app **dá contexto quantitativo** para a decisão — não a substitui.

---

## Para quem isto é útil

| Público | Por que | Como usa |
|---------|---------|----------|
| **Produtor / cooperativa** | Entender risco de margem por município; cenários de preço/câmbio | Decisão de plantio mais informada; hedge mais direcionado |
| **Trader B3** | Sazonalidade CBOT, correlação com PTAX, volatilidade histórica | Estratégias de entrada/saída; timing de call/put |
| **Gestor de cooperativa** | Resiliência de portfolio de crédito agrícola por região/cultura | Aprovação de crédito mais defensável |
| **Banco de crédito agrícola** | Pricing de taxa; cenários de default | Risco de portfólio melhor quantificado |
| **Pesquisador / acadêmico** | Ferramenta reprodutível, código aberto, dados públicos | Referência para trabalhos em economia agrícola regional |
| **Recrutador / banca MBA** | Avaliar maturidade técnica do autor | Vê escopo, validação, narrativa, código |

---

## Repositório e contato

- **Código:** [github.com/vnavarro87/soja-milho-ro](https://github.com/vnavarro87/soja-milho-ro)
- **Licença:** AGPL-3.0
- **Documentação técnica:** [METODOLOGIA.md](METODOLOGIA.md)
- **Business case:** [BUSINESS_CASE.md](BUSINESS_CASE.md)
- **Validação automatizada:** `python validar_dados.py`
- **Autor:** Vinicius Navarro · trader B3 · MBA em Data Science, IA & Analytics

---

*Última revisão: 2026-05-08. App em iteração ativa — mudanças significativas registradas no histórico do Git.*
