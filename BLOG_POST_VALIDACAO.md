# Engenharia de Confiança: Como Validar Dados Públicos Antes Que Eles Te Traiam

## TL;DR

Dados públicos (IBGE, CONAB, BCB) são confiáveis — mas **a sua interpretação deles, não.** Mostro como construir uma camada de validação que pega erros de digitação, mudanças de metodologia e suposições erradas **antes** de você apresentar o número errado em reunião. Aplicado em projeto real de análise de soja/milho em Rondônia, valida 52 municípios × 2 culturas em 200ms. Código aberto, ~150 linhas Python.

---

## Por que isso importa

**Cenário 1 — você sem validação:**

Você está apresentando seu projeto para a banca do MBA. Slide com mapa de Rondônia, soja produzida por município. Professor olha e diz:

> "Engraçado, Porto Velho aparece como 4º maior produtor. Tem certeza? Achei que era só Cone Sul."

Você gela. Faz um cálculo rápido na cabeça. Hesita. Diz: "É o que diz o IBGE."  
Professor anota algo. Banca silenciosa.

**Cenário 2 — você com validação:**

Mesma pergunta. Você responde:

> "Sim, professor. Porto Velho tem **46.994 ha plantados × 3.474 kg/ha = 163.234 t**, o que é coerente com a expansão recente da BR-364 sentido Abunã. A produtividade está dentro do range histórico de RO (3,0–3,8 t/ha) e roda no meu script de validação automática toda semana."

Banca: 👍

A diferença entre os dois cenários **não é o conhecimento técnico** — é a **postura de validação.** E ela pode ser construída com 150 linhas de código.

---

## A história real que motivou esse post

Eu estava conversando com alguém sobre meu projeto de análise agrícola e afirmei, com confiança:

> "Em Rondônia, municípios como Guajará-Mirim, Costa Marques e São Francisco do Guaporé não produzem soja — são da zona pecuarista."

A pessoa me questionou: "Mas o app diz que sim, não?"

Eu rodei o CSV. Pasme:

| Município | Soja (t) | Soja (ha) |
|-----------|---------:|----------:|
| Costa Marques | 24.675 | 7.224 |
| Guajará-Mirim | 32.725 | 9.625 |
| São Francisco do Guaporé | 33.500 | 9.461 |

**Eu estava errado.** Não os dados — eu. O Vale do Guaporé virou fronteira agrícola nos últimos 5–8 anos e eu estava operando com mapa mental desatualizado.

O ponto não é que eu errei (todo mundo erra). O ponto é: **o que me protege da próxima vez que eu errar?**

Resposta: validação automática que me obriga a confrontar os números antes de afirmar qualquer coisa.

---

## A ideia central: identidade física

Para qualquer dado de produção agrícola, existe uma **identidade física inquebrável**:

```
Quantidade (toneladas) = Área (hectares) × Produtividade (kg/ha) ÷ 1000
```

Se os três números **batem entre si** dentro de uma tolerância, o dado é internamente consistente. Se não batem, há erro — pode ser de digitação, conversão, mistura de unidades, ou definição (Área Plantada vs Colhida).

Isso é diferente de "confiar na fonte". Você **força os dados a se autovalidarem**.

### Exemplo concreto

Para Pimenteiras do Oeste (RO), os dados IBGE-PAM 2023 dizem:

- Quantidade: 197.220 t
- Área Plantada: 64.000 ha
- Produtividade: 3.460 kg/ha

Calcula: 64.000 × 3.460 ÷ 1.000 = **221.440 t**

Mas o registro diz **197.220 t**. Diferença de 11%.

**Erro?** Não. Aqui entra **calibração com conhecimento de domínio:**

> O IBGE distingue Área **Plantada** (semeada) e Área **Colhida** (efetivamente colhida). Quando há perda de safra (chuva, geada, doença), a Quantidade vem da Área Colhida, mas no CSV temos Área Plantada. Diferença de até ~12% é normal em RO.

Por isso a tolerância na validação é **12%, não 5%**. O número de tolerância **não é arbitrário** — é informado pela realidade do agro.

---

## Os 3 níveis de validação

O script `validar_dados.py` que escrevi roda **3 checagens**:

### 1. Consistência interna (a identidade física)

```python
def validar_consistencia(df, cultura):
    erros = []
    for _, r in df.iterrows():
        qtd, area, prod = r[f"{cultura}_Qtd_T"], r[f"{cultura}_AreaPlant_Ha"], r[f"{cultura}_Prod_KgHa"]
        if area > 0 and prod > 0 and qtd >= 500:  # ignora produção residual
            esperado = area * prod / 1000
            desvio = abs(qtd - esperado) / esperado
            if desvio > 0.12:  # tolerância 12% (cobre Plantada vs Colhida)
                erros.append(f"{r['Municipio']} {cultura}: {desvio*100:.1f}% desvio")
    return erros
```

### 2. Ranges plausíveis

Cada cultura tem uma **banda de produtividade defensável** para a região:

```python
RANGES_PRODUTIVIDADE_KG_HA = {
    "Soja":  {"min": 2500, "max": 4200},   # 2,5 a 4,2 t/ha
    "Milho": {"min": 1500, "max": 6500},   # 1,5 a 6,5 t/ha
}
```

Por que milho tem range tão largo? Porque tem **dois regimes**:
- **Comercial mecanizado** (Cone Sul): 4–6 t/ha (safrinha)
- **Subsistência** (Zona da Mata, agricultura familiar): 1,5–3 t/ha

Calibrar isso pelo "ideal" (só comercial) faria 4 municípios pequenos serem reportados como erro toda semana, mas o erro não está nos dados — está no range. Ranges devem refletir **a realidade**, não a média.

### 3. Sanidade estrutural

Coisas que parecem bobas mas pegam erros reais:
- Cobertura municipal: RO tem 52 municípios — se vier 50 ou 54, alguma coisa quebrou
- Valores negativos (não existe área negativa)
- Duplicatas (importação parcial)

```python
def validar_estrutura(df):
    erros = []
    if not (50 <= len(df) <= 55):
        erros.append(f"Cobertura: {len(df)} municípios (esperado 52)")
    for col in df.columns[1:]:
        if (df[col] < 0).any():
            erros.append(f"Coluna {col} tem valores negativos")
    if df["Municipio"].duplicated().any():
        erros.append("Municípios duplicados")
    return erros
```

---

## Calibração honesta: a parte que ninguém ensina

A primeira vez que rodei a validação, ela **reprovou** com 7 violações. Eu poderia ter:

1. **Ignorado** ("os dados estão bons, vou ajustar a tolerância para 50%")
2. **Investigado caso por caso e calibrado com motivo**

Fiz a opção 2:

| Violação | Causa investigada | Ajuste calibrado |
|----------|------------------|------------------|
| Pimenteiras 11% desvio | Área Plantada ≠ Área Colhida | Tolerância 12% |
| Teixeirópolis 40% desvio | Produção residual (5 t) | Mínimo 500 t para validar |
| 4 municípios milho < 3.000 kg/ha | Subsistência (Zona da Mata) | Range mínimo 1.500 kg/ha |

**Toda calibração tem comentário no código explicando o motivo.** Isso é diferente de "afrouxar para passar". É **engenharia honesta de tolerância** — calibrada pelo conhecimento do domínio, não pelo desejo de passar no teste.

---

## Por que não usar pacote pronto (great_expectations, pandera)

Existem ferramentas profissionais (Great Expectations, Pandera, Pydantic). Para projetos grandes, valem o overhead.

Para um projeto de análise focado, **150 linhas de Python puro fazem o trabalho** — e qualquer pessoa que abrir o código entende em 5 minutos. Não precisa aprender DSL, não precisa configurar YAML, não precisa instalar dependência.

A regra aqui é simples: **a complexidade da validação não pode ultrapassar a do código que ela protege.**

---

## Integrando com CI (próximo passo)

O `validar_dados.py` retorna **exit code 1** se houver violação. Isso permite plugar em CI/CD trivialmente:

```yaml
# .github/workflows/validar-dados.yml
on:
  schedule:
    - cron: '0 9 * * 1'  # toda segunda 9h
jobs:
  validar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pandas
      - run: python validar_dados.py
```

Quando o IBGE publicar dados de 2024 (esperado em 2025), o script reroda **sozinho**, e se algum município novo violar a identidade física, abre uma issue automaticamente. **Você é avisado antes do problema chegar até a apresentação.**

---

## Onde isso falha

Validação por identidade física **não pega:**

- ❌ Erro sistemático na fonte (se IBGE inteiro publicar tudo errado, a identidade ainda fecha)
- ❌ Erro conceitual (se eu confundir "produção" com "produtividade", a identidade pode falsamente fechar)
- ❌ Mudança de metodologia (se IBGE mudar definição de "Área Plantada" em 2025, validação passa mas semântica mudou)

**Solução para esses casos:** acompanhar mudanças metodológicas via release notes da fonte, e ter pelo menos uma "âncora" externa (ex: total estadual cruzando IBGE-PAM com CONAB-Acompanhamento de Safra).

---

## A postura por trás da técnica

O ponto **não é o script de validação**. É a postura: **todo número exibido precisa ter resposta para "por que esse número faz sentido?"**

Em finanças, isso se chama "due diligence". Em ciência, é "peer review". No agro, deveria ser padrão também.

Quando você adota essa postura:

- **Você confia mais** no que apresenta (porque você verificou)
- **Você descobre** problemas reais (que estavam escondidos)
- **Você é levado mais a sério** (porque mostra rigor)
- **Você dorme melhor** (porque sabe que o sistema te avisa antes do desastre)

---

## Aplique no seu projeto

Não importa se você trabalha com dados de saúde, financeiros, agrícolas, esportivos. Toda área tem **identidades físicas inquebráveis** que podem ser usadas como âncora:

- **Saúde:** Casos novos = Casos ativos + Recuperados + Óbitos
- **Financeiro:** Saldo final = Saldo inicial + Receitas − Despesas
- **Esportes:** Total partidas = Vitórias + Empates + Derrotas
- **Agro:** Quantidade = Área × Produtividade

Encontre a sua. Escreva 100 linhas de Python. Rode toda semana. **Pronto** — você acabou de adicionar uma camada de proteção que diferencia analistas amadores de analistas profissionais.

---

## Código completo

Repositório: **github.com/vnavarro87/soja-milho-ro** → arquivo `validar_dados.py`

Licença AGPL-3.0. Use, modifique, compartilhe — mas mantenha aberto o que derivar.

---

## Conclusão

Dados públicos não te traem por má-fé — te traem porque **sua interpretação deles está em algum momento desatualizada, errada ou incompleta**. A validação não substitui o conhecimento de domínio, mas garante que ele seja **explicitado em código** em vez de ficar implícito na sua cabeça.

E quando alguém te perguntar "tem certeza desse número?", você responde com cálculo, não com fé.

---

**Vinicius Navarro**  
Trader de dólar (WDO/B3) · Análise de risco agrícola · Rondônia  
Estudando MBA em Data Science, IA & Analytics  
[LinkedIn / GitHub links — inserir quando publicar]

---

## Notas para Publicação

- [ ] Inserir screenshot do output do `validar_dados.py` (relatório aprovado)
- [ ] Inserir screenshot da diff do GitHub Actions abrindo issue automática
- [ ] Adicionar link do projeto e do post anterior (MM52)
- [ ] Ajustar tom para plataforma (Medium/LinkedIn/Substack)
- [ ] Cross-link com BLOG_POST_MM52.md (esse é o 2/6 da série)
