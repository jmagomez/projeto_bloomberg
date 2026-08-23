# Pipeline ETL de Ações — "Sua Própria Bloomberg"

Pipeline de dados que coleta cotações diárias de uma ação da B3 (PETR4), trata os dados e os publica em um dashboard estático, além de carregá-los em um banco SQLite na arquitetura medalhão (raw → silver → gold).

📊 **Dashboard:** https://jmagomez.github.io/projeto_bloomberg/

## Estrutura

```
projeto_bloomberg/
├── scripts/
│   ├── yahoo_chart.py        # cliente do Yahoo Finance + validação de atualidade
│   ├── update_dashboard.py   # gera data.js (stats + séries diária, semanal e proventos)
│   ├── emit_summary.py       # resumo do último pregão para o e-mail da rotina
│   ├── extract_petr4.py      # (ETL) baixa cotações da Alpha Vantage -> data/raw/*.json
│   ├── transform_petr4.py    # (ETL) limpa e padroniza -> data/silver/*.csv
│   ├── load_petr4.py         # (ETL) carrega no SQLite -> data/gold/petr4.db
│   ├── query_petr4.py        # (ETL) consulta o banco e imprime análises
│   └── run_etl_pipeline.py   # (ETL) extract -> transform -> load -> query
├── tests/                    # testes sem rede das agregações e da validação
├── data/
│   ├── raw/     # dados brutos (JSON) — inclui um arquivo de exemplo
│   ├── silver/  # dados tratados (CSV)
│   └── gold/    # banco de dados (SQLite)
├── data.js      # payload do dashboard, gerado pela rotina
├── index.html   # dashboard interativo (GitHub Pages)
└── requirements*.txt
```

## O dashboard e sua rotina

`scripts/update_dashboard.py` baixa a série diária da PETR4 desde 2010 no Yahoo
Finance (preço e proventos), calcula os indicadores e escreve `data.js`. O
GitHub Actions roda a rotina **todo dia útil às 18:30 de Brasília**, depois do
fechamento e do after-market da B3, commita o `data.js` e envia um e-mail com o
resumo do pregão.

### Por que a rotina se recusa a publicar dado defasado

Em 22/08/2026 o endpoint do Yahoo respondeu HTTP 200 com a série terminando em
20/08 (quinta), embora o pregão de 21/08 (sexta) já estivesse fechado havia
horas. A rotina antiga publicou assim mesmo, e o dashboard ficou uma semana
exibindo o penúltimo pregão.

A rotina atual compara duas informações que vêm na **própria resposta** do
Yahoo:

| campo | significa |
| --- | --- |
| `meta.regularMarketTime` | qual foi o último pregão, na visão da fonte |
| último item de `timestamp` | qual foi o último pregão realmente entregue |

Se o segundo for anterior ao primeiro, a série está defasada. A rotina então
reconsulta (`query1`/`query2` e uma janela curta, que têm caches independentes)
e, se o pregão continuar faltando, **falha o job sem escrever nada** — o
dashboard mantém o último dado íntegro e um e-mail de alerta é enviado. Uma
segunda trava impede que o novo `data.js` termine antes, ou tenha menos
pregões, do que o já publicado.

Nenhum calendário de feriados é necessário: `regularMarketTime` já responde
"qual foi o último pregão" mesmo em feriados e emendas. Nenhum preço é
estimado, interpolado ou completado — se a fonte não entregar, a rotina falha.

O dashboard também exibe um aviso quando os dados carregados são mais antigos
do que os dias úteis já decorridos, para o caso de a própria rotina ter parado
de rodar.

## Como rodar

Instale as dependências:

```bash
pip install -r requirements.txt              # pipeline ETL completo
pip install -r requirements-dashboard.txt    # só a rotina do dashboard
```

### Atualizar o dashboard localmente

```bash
python scripts/update_dashboard.py
```

Códigos de saída: `0` sucesso · `2` dados defasados (nada foi escrito) ·
`3` fonte indisponível.

### Pipeline ETL (Alpha Vantage)

1. **(Opcional) Para coletar dados novos**, obtenha uma chave gratuita da
   [Alpha Vantage](https://www.alphavantage.co/support/#api-key), copie
   `.env.example` para `.env` e preencha `ALPHA_VANTAGE_API_KEY`. Depois:
   ```bash
   cd scripts && python run_etl_pipeline.py
   ```

2. **Para testar sem chave de API**, o projeto já inclui um arquivo de dados
   brutos de exemplo em `data/raw/`. Basta rodar a partir do transform:
   ```bash
   python scripts/transform_petr4.py
   python scripts/load_petr4.py
   python scripts/query_petr4.py
   ```

### Testes

```bash
pip install -r requirements-dev.txt
pytest        # nenhum teste acessa a rede
ruff check .
```

## Estrutura do `data.js`

```js
window.PETR4 = {
  stats: { last_date, last_close, prev_close, day_change_pct, day_open,
           day_high, day_low, day_volume_M, ret_annual_pct, div_yield_ttm_pct,
           vol_pct, vol_annual_pct, avg_vol_M, updated_utc, ... },
  D:   { d, o, h, l, c, v, e },   // últimos ~520 pregões (candles diários)
  W:   { d, o, h, l, c, v, e },   // séries semanais desde 2010
  DIV: { y, v }                   // proventos por ano (R$/ação)
}
```

## Secrets usados pela rotina

| secret | uso |
| --- | --- |
| `MAIL_USERNAME` | conta Gmail remetente do resumo diário |
| `MAIL_PASSWORD` | senha de app do Gmail |

Sem esses secrets a rotina continua atualizando o dashboard; só não envia
e-mail (e registra um aviso no log).

---

Os preços de fechamento não são ajustados por proventos: o indicador "Retorno
no período" soma separadamente os dividendos e JCP pagos por ação. Este projeto
é um exercício de engenharia de dados e **não é recomendação de investimento**.
