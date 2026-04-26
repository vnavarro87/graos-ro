# Grãos de Rondônia — Preço, Câmbio e Risco

Soja e milho são cotados em Chicago, em dólar, em bushel. O fazendeiro de Rondônia recebe em reais, por saca, numa fazenda a centenas de quilômetros do porto. A diferença entre esses dois mundos — o **basis** — determina se a safra dá lucro ou não.

Quis entender como esse deságio funciona na prática: o que muda entre municípios, qual câmbio transforma uma safra boa em prejuízo, e como visualizar isso de forma que faça sentido para quem toma a decisão.

## Decisões de design

**PTAX em vez do dólar comercial do Yahoo Finance**
O PTAX é a referência oficial do Banco Central para liquidação de contratos cambiais — é o câmbio que o contrato usa, não o que aparece na tela do celular. Usar Yahoo Finance aqui seria conveniente mas tecnicamente incorreto para análise de risco.

**Basis calibrado por fontes públicas, não real-time**
O basis real depende de contratos privados entre tradings e produtores — não é público. A alternativa foi calibrar com médias de USDA FAS, CONAB e ABIOVE: defensável, auditável, e honesto sobre o que é estimativa.

**Scatter histórico + curva de break-even em vez de heatmap**
O heatmap original mostrava dados mas não respondia a pergunta: "em quantas semanas dos últimos 5 anos o produtor teria operado no prejuízo?". O scatter com a curva de break-even responde diretamente — e posiciona o momento atual no contexto histórico.

**Distância geodésica (Haversine) para basis variável por município**
Distância rodoviária real exigiria roteirização com dados que ou são privados ou exigem infraestrutura fora do escopo. Haversine é boa aproximação para análise de portfólio; para pricing operacional, não substitui.

**yfinance como fonte de cotações CBOT**
É wrapper não-oficial sem SLA de continuidade — pode ser interrompido sem aviso. Escolhido pela cobertura dos contratos CBOT sem custo; substituto natural seria a API da Bloomberg ou Refinitiv.

## Stack

- **Python** + **Streamlit** + **Plotly**
- **yfinance** — cotações CBOT
- **BCB SGS** — PTAX (série 1) e IPA-OG Fertilizantes (série 7456)
- **IBGE/SIDRA** — produção municipal PAM 2023

## Como rodar

```bash
git clone https://github.com/vnavarro87/graos-ro.git
cd graos-ro
pip install -r requirements.txt
streamlit run app.py
```

O parquet com cotações já está no repo. Para atualizar antes de rodar:

```bash
python coleta_mercado.py
```

Ou use o botão "Atualizar cotações" na sidebar do app.

## Estrutura

```
graos_ro/
├── app.py                       # Aplicação Streamlit
├── coleta_mercado.py            # ETL de cotações (yfinance + BCB)
├── dados_agro_ro_master.csv     # Produção municipal (IBGE/PAM 2023)
├── mapa_ro.json                 # Geometria municipal (IBGE 2022)
├── cotacoes_historico.parquet   # Histórico de cotações (cache local)
├── METODOLOGIA.md               # Fontes, fórmulas e limitações
├── requirements.txt
└── README.md
```

## Limitações conhecidas

- **Basis por município é aproximação.** Usa distância em linha reta ao hub logístico mais próximo. Se eu refizesse, usaria dados de frete ANTT por trecho — mais preciso, mas dependeria de coleta manual periódica que não automatizei.

- **Custo de produção uniforme entre municípios.** O COT da CONAB é referência de Cerejeiras. Variações regionais de preço de terra e mão de obra existem mas não têm fonte pública municipalizada disponível.

- **Cotações com até 15 min de defasagem** (Yahoo Finance) e PTAX divulgado só ao final do dia útil. Adequado para análise de cenário; não para decisão de comercialização em tempo real.

- **Dados de produção com defasagem de ~1 ano.** PAM 2023 é o último ano fechado. Não há forma de atualizar isso antes do IBGE publicar o ciclo seguinte.

Detalhamento completo em [METODOLOGIA.md](METODOLOGIA.md).

## Sobre

Este é o segundo projeto de uma série sobre o agronegócio de Rondônia. O primeiro — [Lavouras RO](https://github.com/vnavarro87/lavouras-ro) — mapeou o que o estado produz e onde. Este responde a pergunta seguinte: quanto vale essa produção, e por que o município muda o preço que o produtor recebe?

Implementação acelerada com uso de Claude Code como copiloto. Definição do problema, escolha de fontes, decisões de arquitetura, validações de integridade e tratamento de edge cases conduzidos por mim.

## Limitações de escopo

Este projeto cobre soja e milho em RO com dados públicos disponíveis. Análise de hedge cambial, sazonalidade histórica e cruzamento com custos regionais são tratados como projetos separados.

## Licença

Copyright (C) 2026 Vinicius Navarro.

Este projeto está licenciado sob a [GNU Affero General Public License v3.0](LICENSE). Em resumo: você pode usar, estudar, modificar e redistribuir, mas qualquer trabalho derivado — inclusive uso como serviço de rede — precisa ser disponibilizado sob a mesma licença. Para licenciamento comercial sob outros termos, entre em contato.
