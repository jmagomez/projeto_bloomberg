# Pipeline ETL de Ações — "Sua Própria Bloomberg"

Pipeline de dados que coleta cotações diárias de uma ação da B3 (PETR4), trata os dados e os publica em um dashboard estático, além de carregá-los em um banco SQLite na arquitetura medalhão (raw → silver → gold).

📊 **Dashboard:** https://jmagomez.github.io/projeto_bloomberg/

## Estrutura

```
projeto_bloomberg/
├── scripts/
│   ├── yahoo_chart.py        # cliente do Yahoo Finance + validação de atualidade
│   ├── update_dashboard.py   # gera data.js (stats, drawdown e séries diária, semanal, mensal, proventos e Ibovespa)
│   ├── emit_summary.py       # resumo do último pregão para o e-mail da rotina
│   ├── extract_petr4.py      # (ETL) baixa cotações da Alpha Vantage -> data/raw/*.json
│   ├── transform_petr4.py    # (ETL) limpa e padroniza -> data/silver/*.csv
│   ├── load_petr4.py         # (ETL) carrega no SQLite -> data/gold/petr4.db
│   ├── query_petr4.py        # (ETL) consulta o banco e imprime análises
│   └── run_etl_pipeline.py   # (ETL) extract -> transform -> load -> query
├── tests/                    # testes sem rede das agregações e da validação
├── data/
│   ├── raw/     # dados brutos (JSON) — inclui um arquivo de exemplo
│   ├── silver/  # dados tratados (CSV) — gerado, fora do controle de versão
│   └── gold/    # banco de dados (SQLite) — gerado, fora do controle de versão
├── data.js      # payload do dashboard, gerado pela rotina
├── index.html   # dashboard interativo (GitHub Pages)
└── requirements*.txt
```

## O dashboard e sua rotina

`scripts/update_dashboard.py` baixa a série diária da PETR4 desde 2010 no Yahoo
Finance (preço e proventos), busca o Ibovespa (`^BVSP`) para a comparação,
calcula os indicadores e escreve `data.js`. O GitHub Actions roda a rotina
**todo dia útil às 18:47 de Brasília**, depois do fechamento e do after-market
da B3, commita o `data.js` e envia um e-mail com o resumo do pregão.

Há uma segunda janela, de **repescagem às 08:13 de Brasília** (terça a sábado).
Se a rodada da véspera já publicou, ela não encontra mudança em `data.js` e
termina sem commitar nada; se a fonte estava incompleta à noite, o pregão entra
na manhã seguinte em vez de esperar o próximo dia útil.

Os minutos são deliberadamente estranhos. `:00` e `:30` são os horários mais
disputados na fila do GitHub Actions e o enfileiramento aqui chegou a atrasar a
rodada em quase seis horas — o run agendado para 21:30 UTC só começou às 03:13
UTC do dia seguinte.

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
reconsulta (`query1`/`query2` e uma janela curta, que têm caches independentes).
Se o pregão continuar faltando **e a coleta não avançar em relação ao que já
está publicado**, o job falha sem escrever nada — o dashboard mantém o último
dado íntegro e um e-mail de alerta é enviado. Se a coleta avançou mas ainda
deve um pregão, o avanço é publicado com a pendência sinalizada em
`stats.pending_session`, e o dashboard mostra o aviso. Uma segunda trava impede
que o novo `data.js` termine antes, ou tenha menos pregões, do que o já
publicado.

Nenhum calendário de feriados é necessário: `regularMarketTime` já responde
"qual foi o último pregão" mesmo em feriados e emendas.

### O segundo incidente: a barra com `close` nulo (28/08/2026)

Nos dias 28 e 29/08 a rotina falhou (runs #16 e #17). A causa não foi série
truncada: o Yahoo passou a servir a barra do pregão com `open`, `high`, `low` e
`volume` preenchidos e `close` (e `adjclose`) **nulos**, e assim ficou por mais
de 24 horas. A barra caía fora na extração, a série ficava um pregão atrás do
que o próprio `meta.regularMarketTime` reportava, e a trava acima — corretamente
— se recusava a publicar. Só que nenhum retry resolve um defeito persistente da
fonte.

O fechamento estava na mesma resposta, em `meta.regularMarketPrice`, ao lado de
`regularMarketDayHigh/Low/Volume` que batiam com a própria barra.
`recupera_fechamento_do_meta()` usa esse valor, e **só** quando todas estas
condições valem ao mesmo tempo:

- o pregão já terminou (`regularMarketTime` ≥ fim do horário regular);
- a barra faltante é a **última** da série — buraco no meio nunca é preenchido;
- ela é a barra do pregão que o `meta` reporta;
- `open`, `high` e `low` da barra estão preenchidos;
- o preço cai **dentro** da faixa `[low, high]` da própria barra.

Fora disso, nada é recomposto. Nenhum preço é estimado, interpolado ou
extrapolado em nenhum caminho do código. Quando o fechamento vem por essa via, o
`data.js` registra `stats.close_source = "meta"` e o rodapé do dashboard diz de
onde o número veio.

O dashboard também exibe um aviso quando os dados carregados são mais antigos
do que os dias úteis já decorridos, para o caso de a própria rotina ter parado
de rodar.

## Como rodar

Instale as dependências:

```bash
pip install -r requirements.txt              # pipeline ETL completo
pip install -r requirements-dashboard.txt    # só a rotina do dashboard
pip install -r requirements-dev.txt          # lint e testes
```

As versões são **fixadas com `==`**. Com `>=`, o pip instalava sempre a mais
recente e não havia como saber em que versão a rotina rodou num dia específico —
uma quebra a montante chegaria sem aviso, direto em produção. Com o pin, cada
atualização vira um PR do Dependabot (agrupado, semanal) que passa pelo CI antes
de entrar.

### Atualizar o dashboard localmente

```bash
python scripts/update_dashboard.py
```

Códigos de saída: `0` sucesso (inclusive publicação parcial com pendência
sinalizada) · `2` a fonte deve um pregão e a coleta não avança além do que já
está publicado — nada foi escrito · `3` fonte indisponível.

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
           vol_pct, vol_annual_pct, avg_vol_M, updated_utc,
           // drawdown
           max_drawdown_pct, max_drawdown_de, max_drawdown_ate,
           max_drawdown_recuperado, drawdown_atual_pct, ath_close, ath_date,
           // procedência do dado
           pending_session,   // pregão que a fonte deve, ou null
           close_source,      // "chart" (barra) ou "meta" (regularMarketPrice)
           ... },
  D:   { d, o, h, l, c, v, e },   // últimos ~520 pregões (candles diários)
  W:   { d, o, h, l, c, v, e },   // séries semanais desde 2010
  M:   { d, r },                  // retorno % mês a mês, para o heatmap
  DIV: { y, v },                  // proventos por ano (R$/ação)
  REF: { D, W }                   // Ibovespa alinhado às datas de D e W
}
```

`M` omite o primeiro mês da série: não há fechamento anterior que sirva de base,
e uma base parcial daria um número não comparável com os demais.

`REF` só existe quando a coleta do Ibovespa deu certo — ela nunca derruba a
rotina. Sem o bloco, o painel de comparação simplesmente não aparece no
dashboard. O alinhamento repete o último valor conhecido do índice nas datas em
que ele não negociou; **não interpola**, e deixa `null` antes do primeiro dado.

## O dashboard

Além dos candles diários e semanais, suporte/resistência, tendência, médias
móveis, RSI e proventos, o dashboard traz:

- **volume diário** em barras, sincronizado com a janela do gráfico de preço;
- **drawdown** — a série do recuo desde o topo, mais a pior queda histórica
  (com as datas de pico, fundo e recuperação) e o drawdown atual;
- **heatmap de retornos mensais** (ano × mês), como tabela de verdade, com a
  intensidade da cor proporcional à magnitude do retorno;
- **PETR4 × Ibovespa em base 100**, com janelas de 1, 2, 5 e 10 anos ou a série
  inteira.

As cores foram escolhidas com simulação de daltonismo: o par azul/roxo usado
antes nas médias móveis ficava a ΔE 2,7 sob deuteranopia — praticamente
indistinguível — e foi trocado por azul/amarelo, que fica a ΔE 16,0 no pior caso
simulado.

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
