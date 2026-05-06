# Por Que MM52 Funciona para Análise de Commodities (e CBOT 30 Anos Vale a Pena)

## TL;DR

Análise de sazonalidade agrícola com **MM52** (média móvel de 52 semanas) cancela inflação por construção. Não precisa de deflação por CPI/IPCA. Isso permite comparar preço de soja/milho ao longo de **30 anos** sem brincar com taxas de câmbio ou índices de inflação — a razão entre dois preços no mesmo regime faz o trabalho. Aplicamos isso em Rondônia e encontramos padrões sólidos.

---

## O Problema Clássico em Economia Agrícola

Você está analisando preços de commodities. Olha para histórico de 30 anos. E aí?

**Opção 1:** Usar preços nominais (como estão).
- ✓ Fácil: pega dados do Yahoo Finance
- ✗ Problema: inflação mascara tudo. Preço de 1994 vs 2024 não é comparável

**Opção 2:** Deflacionar por CPI.
- ✓ Mais rigoroso
- ✗ Precisa decidir: CPI americano? IPCA? Ponderação? Defasagem de publicação?
- ✗ Adiciona dependências (mais uma API, mais uma fonte de erro)

**Opção 3 (boa):** Usar razão entre preços.
- ✓ Cancela inflação por construção
- ✓ Sem dependências adicionais
- ✓ Método padrão USDA/FAO — defensável academicamente

A gente usa **Opção 3**.

---

## Como Funciona MM52

Pegue o preço **nominal** da soja (como sai do Yahoo Finance):

```
Preço Efetivo = CBOT + Basis × PTAX × (conversão de unidades)
```

Depois calcule a média móvel **centrada** de 52 semanas (1 ano):

```
MM52(t) = média(Preço[t-26] até Preço[t+26])
```

Depois divida um pelo outro:

```
Índice Sazonal = Preço(t) / MM52(t)
```

**Pronto.** Agora você tem um número que:
- Compara mês X do ano Y vs mês X do ano Y+N
- Cancela tendência de curto prazo (MM52 filtra)
- Cancela inflação (é razão entre dois preços no mesmo regime)
- Não depende de deflador externo (CPI/IPCA)

Se Índice = 1,05 → esse mês é 5% **mais caro** que a média móvel de 1 ano.  
Se Índice = 0,95 → é 5% **mais barato**.

---

## Por Que Funciona: A Intuição

**Premissa:** inflação afeta o numerador e o denominador igualmente.

Se a inflação foi +8% ao ano em 2023:
- Preço nominal da soja sobe 8% (por inflação) + movimento real
- MM52 (ano passado) também sobe 8% (por inflação)
- Razão: cancela o 8%

Exemplo concreto:
```
Ano 2023, Abril:
  Preço = R$ 1.000/saca (nominal, já com inflação de 2023)
  MM52 = R$ 980/saca (média de 52 semanas atrás, também com inflação de 2023)
  Índice = 1.000 / 980 = 1.020
  
Resultado: "Abril 2023 foi 2% mais caro que a média móvel de 1 ano"
```

Esse "2% mais caro" é **sinal sazonal real**, não efeito inflacionário.

---

## A Limitação (Honesta)

MM52 cancela **boa parte** da inflação, não 100%.

- Se a inflação mudou entre dois anos (ex: 2015 foi 10%, 2023 foi 5%), há um pequeno efeito residual
- Mas para commodities com ciclo de 1 ano, esse efeito é minorado

**Solução para estudos rigorosos:** comparar apenas dentro de janelas de inflação estável. A gente usa **últimos 10 anos** (2014–2024) por isso — regime produtivo de Rondônia é homogêneo, inflação foi "meio caótica" mas média é comparável.

---

## Aplicação: Soja & Milho em Rondônia

Pegamos CBOT de soja (ZS) e milho (ZM) de 30 anos.  
Convertemos para preço efetivo em reais (+ PTAX + basis regional).  
Calculamos MM52 para os últimos 10 anos.

**Resultado para Soja:**
- **Melhor mês:** fevereiro–março (+3 a +5% vs média anual)
- **Pior mês:** julho–agosto (−2 a −3% vs média anual)
- **Spread:** ~7–8% entre melhor e pior
- **Desvio padrão:** ±2% (variação dentro de um mesmo mês é relevante)

**Resultado para Milho Safrinha:**
- **Melhor mês:** maio (pós-plantio, antes de entressafra)
- **Pior mês:** julho–agosto (pós-colheita, oferta máxima)
- **Spread:** ~5–6% (menor que soja, ciclo mais curto)

**Interpretação:** Se você planta milho em fevereiro e colhe em junho, historicamente você "pega" maio (melhor mês) — vantagem natural de timing da safrinha.

---

## Por Que Isso Importa para Trader/Produtor

1. **Timing de venda:** você sabe quais meses historicamente pagam mais
2. **Decisão de hedge:** se o risco cambial intra-safra é ±5%, e a sazonalidade é ±4%, talvez compense fixar câmbio e deixar preço solto (ou vice-versa)
3. **Comparação de safras:** "safra 2015 foi ruim por quê? Era preço baixo + mês ruim? Ou só câmbio desfavorável?"

---

## Reprodutibilidade: Código

Se você quer replicar isso:

```python
import pandas as pd
import yfinance as yf

# Baixa 30 anos de soja
soja = yf.download('ZSZ', start='1995-01-01')['Close']

# Calcula média móvel 52 semanas (centrada)
mm52 = soja.rolling(window=52, center=True, min_periods=26).mean()

# Índice sazonal
indice_sazonal = soja / mm52

# Agrupa por mês
indice_sazonal_mes = indice_sazonal.groupby(indice_sazonal.index.month).mean()

print(indice_sazonal_mes)
```

Nenhuma dependência externa. Dados públicos. Reprodutível.

---

## Comparação com Outras Abordagens

| Abordagem | Complexidade | Acurácia | Reprodutibilidade |
|-----------|-------------|----------|-------------------|
| **Preços nominais** | Baixa | ✗ (inflação mascara) | ✓ |
| **Deflação por CPI** | Alta | ✓ | ✗ (depende de fonte CPI) |
| **MM52 (razão)** | Baixa | ✓ | ✓ |

---

## Limitações & Quando NÃO Usar MM52

❌ Commodities com ciclo > 1 ano (ex: café, cacau — plantio e colheita em anos diferentes)  
❌ Períodos de inflação muito heterogênea (ex: Brasil 1990–2000, inflação de 3 dígitos)  
❌ Quando você quer previsão (MM52 mostra padrão histórico, não prediz)  
❌ Shocks geopolíticos (guerra, embargo — padrão sazonal quebra)

✓ Quando você quer: sazonalidade comparável ao longo de décadas, sem ajuste deflacionário.

---

## Dashboard Interativo (Código Aberto)

A gente implementou MM52 em um dashboard Streamlit:

**GitHub:** github.com/vnavarro87/soja-milho-ro  
**App:** [link Streamlit Cloud — inserir quando publicado]

Você pode:
- Ver sazonalidade de soja vs milho lado a lado
- Explorar por município (basis varia)
- Simular câmbio e preço
- Baixar dados para análise própria

Código é AGPL-3.0 (aberto). Dados são 100% públicos (CBOT via Yahoo Finance, PTAX via BCB).

---

## Conclusão

MM52 é simples, defensável, reprodutível. Não é bala de prata — mas para análise de sazonalidade de commodities agrícolas com ciclo de 1 ano, é o padrão da literatura (USDA, FAO) por uma razão.

Se você trabalha com soja/milho:
- Entenda a sazonalidade histórica (MM52)
- Combine com risco cambial (quanto o dólar se move entre plantio e colheita)
- Combine com custos regionais (variam por município)
- Aí sim você tem visibilidade real de risco de margem

Não é "previsão" — é "contexto histórico bem estruturado."

---

## Referências

- USDA — Commodity Seasonality Analysis
- CONAB — Acompanhamento da Safra Brasileira
- Banco Central do Brasil — SGS (série PTAX)
- Yahoo Finance (CBOT histórico)
- Código completo: github.com/vnavarro87/soja-milho-ro

---

**Vinicius Navarro**  
Trader de dólar (WDO/B3) · Análise de risco agrícola · Rondônia  
[LinkedIn / GitHub links — inserir quando publicar]

---

## Notas para Publicação

- [ ] Inserir screenshot do gráfico de sazonalidade (aba "Sazonalidade e Hedge" do app)
- [ ] Inserir screenshot do gráfico comparativo soja vs milho
- [ ] Inserir link do app quando for deployed (Streamlit Cloud)
- [ ] Ajustar tom para plataforma (Medium = mais formal; LinkedIn = mais conversacional)
- [ ] Adicionar call-to-action no final ("compartilhe seus achados", "cite se usar", etc)
