# Pipeline ETL de Ações — "Sua Própria Bloomberg"

Pipeline de dados que coleta cotações diárias de uma ação da B3 (PETR4), trata os dados e os publica em um dashboard estático, além de carregá-los em um banco SQLite na arquitetura medalhão (raw → silver → gold).

📊 **Dashboard:** https://jmagomez.github.io/projeto_bloomberg/

## Estrutura

```
projeto_bloomberg/
├── scripts/
│   ├── yahoo_chart.py        # cliente do Yahoo Finance + validação de atualidade
│   ├── analitica.py          # cálculos financeiros puros (beta, correlação, retorno total, vol)
│   ├── noticias.py           # coleta e acervo de manchetes datadas
│   ├── update_dashboard.py   # gera data.js (stats, drawdown e séries diária, semanal, mensal, proventos, Brent, ON/PN, ADR, risco e Ibovespa)
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
├── noticias.json # acervo de manchetes, acumulado uma rodada por vez
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

### O terceiro incidente: a barra zerada (31/08/2026)

O Yahoo entregou a barra do pregão com `open`, `high`, `low` e `volume` iguais a
**`0`** — não `null` — e o fechamento correto. A peneira de então só testava
`None`, os zeros passaram inteiros, e o `data.js` publicou abertura, máxima,
mínima e volume zerados. Pior: como zero passou a ser o menor valor da série
desde 2010, o cartão "Mínima" do dashboard foi ao ar exibindo **R$ 0,00**.

Três travas, em camadas independentes:

1. `preco_possivel()` só aceita número finito e maior que zero. `barra_coerente()`
   recusa máxima abaixo da mínima. A barra que falhar em qualquer um dos dois é
   descartada inteira.
2. A barra descartada **não é reinventada**. O `meta` traz
   `regularMarketDayHigh/Low/Volume` mas **não** traz a abertura — não há de
   onde tirar esse campo sem inventá-lo. A série fica sem aquele pregão, a
   pendência é sinalizada, e a repescagem da manhã pega a barra consolidada.
3. `confere_precos_possiveis()` reexamina o **payload pronto** e recusa qualquer
   preço ≤ 0 em `stats`, `D` ou `W`. Por olhar o resultado e não o caminho, essa
   trava vale também para código que venha a ser acrescentado depois.

Uma nota sobre a primeira versão dessa correção, que também exigia abertura e
fechamento dentro da faixa `[low, high]`: rodada contra a série inteira, ela
reprovava **2014-04-02** — pregão real, 66 M de volume, em que o Yahoo publica
`close` 15,56 contra `low` 15,70. Defeito antigo do histórico da fonte, não
barra suja. A trava de regressão barrou a publicação antes que o buraco entrasse
no `data.js`, e a checagem foi afrouxada para só o que é absurdo em qualquer
leitura. Inconsistência leve agora rende `::warning::` no log, sem remover nem
corrigir nada.

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
  REF: { D, W },                  // Ibovespa alinhado às datas de D e W

  // --- blocos analíticos, em resolução semanal ---
  TR:    { d, preco, total, yd, y },      // retorno total x preço; yield TTM
  BRENT: { d, p, b, md, corr, beta },     // PETR4 x Brent em R$; corr/beta móveis
  PARES: { d, onpn, adr },                // PETR3÷PETR4; prêmio do ADR (%)
  RISCO: { d, v21, v63, v252,             // vol. realizada anualizada por prazo
           md, corr_ref, beta_ref },      // corr/beta móveis contra o Ibovespa
  SESSAO: { d, o, h, l, c, v, prev, var_pct,
            gap_pct, intradia_pct, fecha_em, vol_vs_mediana, amplitude_vs_atr,
            atr_fatores: { ... },         // decomposição do dia (ver abaixo)
            noticias: [{h, t, v, u}] },   // manchetes daquele pregão
  SESSOES: [{ d, c, var, gap, intra, vol, // triagem dos últimos 30 pregões
              res, z, ref, com,           // resíduo e movimento dos fatores
              n: [{h, t, v, u}] }]        // manchetes daquele dia
}
```

### Metodologia dos blocos analíticos

Estão em `scripts/analitica.py`, que é código puro — sem rede, sem estado, e
testado com números conferíveis à mão. Quatro decisões valem ser lidas antes de
usar os números:

**Retornos logarítmicos** em correlação, beta e volatilidade; aritméticos em
tudo que se compara com um extrato. Log é aditivo no tempo, o que faz a
volatilidade escalar por `√252` sem viés.

**Nada é interpolado.** Os pares usados em correlação e beta são só as datas em
que **as duas** séries negociaram. Repetir o último valor conhecido produziria
retorno zero num dia em que o ativo de fato andou, e retorno zero artificial
derruba correlação e beta. O preenchimento por repetição existe, mas só para
desenhar linha em gráfico — nunca para alimentar estatística.

**Janela incompleta não é publicada.** Correlação de 60 pregões precisa de 60
pregões; antes disso o valor é `null` e o gráfico não desenha. Beta com 8
observações é ruído com casas decimais.

**As séries longas saem amostradas por semana** (a última observação de cada
uma). Amostrar não é suavizar: nenhum valor é recalculado ou misturado com o
vizinho, e cada ponto publicado existiu naquele pregão. Em resolução diária
esses blocos dobrariam o `data.js` sem mudar nada do que se vê.

Sobre o **ADR**: cada ADR da Petrobras representa 2 ações, mas a rotina não
confia nessa constante — mede a razão implícita nos próprios preços e só publica
o painel se as duas baterem, para que um reagrupamento futuro não faça o painel
mentir em silêncio. E o prêmio deve ser lido com cuidado: o ADR negocia em Nova
York cerca de duas horas depois do fechamento da B3, então parte do desvio é
notícia que chegou depois, não arbitragem aberta.

### O pregão do dia, e até onde dá para falar de causa

O painel do último pregão tenta responder à pergunta que o leitor faz primeiro —
*por que a ação andou hoje?* — separando o que é aritmética do que é
julgamento.

**A parte aritmética.** `atribuicao_do_dia()` regride os retornos logarítmicos
da PETR4 sobre **Ibovespa e Brent em reais ao mesmo tempo**, e decompõe o
retorno do dia em quatro parcelas que somam exatamente o total: contribuição do
índice, contribuição do petróleo, intercepto da janela e resíduo.

São dois fatores numa regressão múltipla, e não dois betas univariados somados,
porque índice e petróleo são correlacionados entre si — somar betas univariados
conta o mesmo movimento duas vezes e produz uma "explicação" que passa de 100%
do dia sem que nada de errado apareça na conta. Há teste cobrindo exatamente
esse caso.

O modelo é estimado nos **120 pregões anteriores** ao dia analisado, nunca
incluindo o próprio dia: incluí-lo faria o modelo se ajustar ao movimento que se
quer explicar, encolhendo o resíduo artificialmente.

**Onde a causalidade se resolve, ou não.** O resíduo é reportado em desvios-padrão
dos resíduos da própria janela (`z_residuo`). Abaixo de 1σ, o dia é beta de
mercado e de commodity e não pede explicação específica da companhia — atribuí-lo
a uma manchete seria ler sinal em ruído. Acima de 2σ, houve componente
idiossincrático: isso estabelece **que** algo fora dos dois fatores atuou, e não
**o quê**.

**A triagem dos últimos 30 pregões.** O mesmo cálculo aplicado a cada dia, com
janela deslizante própria — o beta que explica terça é o que vigorava até
segunda, não um beta médio do período. Cada pregão sai com um selo: *beta de
mercado* (|z| < 1), *misto* (1 ≤ |z| < 2) ou *idiossincrático* (|z| ≥ 2), ao lado
das manchetes daquele dia.

A ordem importa. Ler manchete por manchete procurando causa é procurar padrão em
ruído: sempre se acha. O resíduo filtra antes — nos dias em que índice e petróleo
dão conta do movimento, a manchete ao lado é coincidência de data, e a leitura
causal ali é erro de raciocínio, não informação a mais.

O painel também informa **quantos dias marcados o acaso sozinho produziria**: a
2σ, cerca de 4,6% dos pregões cruzam o limiar por sorte, o que num conjunto de 30
dá ~1,4. Se o número observado não excede isso, o painel diz explicitamente que o
que se vê é compatível com ruído puro. Sem essa correção para comparações
múltiplas, qualquer janela longa o bastante produziria "achados" garantidos.

**A anatomia complementa.** `anatomia_do_pregao()` separa o **gap** (abertura
contra fechamento anterior) do **intradiário** (fechamento contra abertura). É o
teste mais barato de quando a informação chegou: notícia da véspera aparece no
gap, fluxo formado durante a sessão aparece no intradiário. Junto vêm onde o
fechamento caiu na faixa do dia, o volume contra a mediana de 21 pregões e a
amplitude contra o ATR.

**Duas ressalvas que ficam escritas no painel.** O modelo mede associação, não
causa — a direção econômica entre petróleo e petroleira é evidente, mas o modelo
em si não a prova. E Brent e câmbio negociam além do horário da B3, então o
alinhamento diário é imperfeito.

### Manchetes: o que a rotina faz e o que ela não faz

`scripts/noticias.py` coleta manchetes reais, datadas e atribuídas — título,
veículo, horário e link — e as guarda por data de pregão em `noticias.json`. O
dashboard as exibe ao lado da variação daquele dia.

Ela **não** afirma que a ação subiu ou caiu *por causa* de nenhuma delas.
Coincidência de data não estabelece causa, e uma rotina automática que
escrevesse "a ação caiu porque X" estaria produzindo análise inventada com
aparência de fato. O que se entrega é contexto datado e a fonte primária a um
clique; a leitura causal é de quem tem o resto do quadro.

O acervo é acumulado porque o endpoint de busca do Yahoo só devolve manchetes
recentes — não há arquivo consultável para trás. Cada rodada mescla o que
encontrou ao que já estava guardado, deduplicando por link, e o item já guardado
prevalece sobre uma reescrita posterior do título. Nos primeiros dias há pouca
coisa, e isso aparece como está: "sem manchete guardada para este pregão".

A relevância é filtrada mecanicamente, em três regras: entra o que menciona a
empresa no título, **ou** o que tem poucos tickers relacionados *e* usa
vocabulário do setor no título; e sai, em qualquer caso, o que for compilação de
mercado enfileirando companhias.

As duas últimas regras vieram dos dados, não de hipótese. Nas primeiras semanas
de coleta o acervo guardou 7 manchetes em 30 pregões, e 3 delas não eram sobre a
companhia: duas da KNOT Offshore — armadora que fretea navios à Petrobras, e que
o Yahoo por isso marca com o ticker PBR — e uma lista de dez recomendações de
analista que citava "Petrobras" no meio do título. `depura` reaplica a peneira
ao acervo a cada rodada, para que uma correção no filtro limpe o histórico em
vez de valer só dali para a frente.

O custo dessa precisão é conhecido: um fato relevante cujo título não use nenhum
termo do setor nem o nome da empresa não entra. A peneira erra para menos.

`M` omite o primeiro mês da série: não há fechamento anterior que sirva de base,
e uma base parcial daria um número não comparável com os demais.

`REF` só existe quando a coleta do Ibovespa deu certo — ela nunca derruba a
rotina. Sem o bloco, o painel de comparação simplesmente não aparece no
dashboard. O alinhamento repete o último valor conhecido do índice nas datas em
que ele não negociou; **não interpola**, e deixa `null` antes do primeiro dado.

## O dashboard

A página é organizada em quatro seções, com uma faixa fixa no topo trazendo o
que se confere primeiro: fechamento, variação no dia, yield de 12 meses, beta ao
Brent em reais, volatilidade de 21 pregões e posição na faixa de 52 semanas.

| seção | o que responde |
| --- | --- |
| **Preço & técnico** | candles diário e semanal, médias móveis, suporte/resistência, RSI, volume, e a anatomia do **último** pregão com a decomposição do retorno em fatores |
| **Pregões & notícias** | os últimos 30 pregões, cada um com o seu resíduo, o selo de triagem e as manchetes daquele dia |
| **Drivers setoriais** | PETR4 × Brent em reais com correlação e beta móveis; PETR3/PETR4 e paridade do ADR; PETR4 × Ibovespa |
| **Retorno & proventos** | retorno total × retorno de preço, yield TTM ao longo do tempo, proventos por ano, heatmap mensal |
| **Risco** | drawdown, estrutura a termo da volatilidade realizada, beta e correlação móveis ao Ibovespa |

Os painéis ficam todos no DOM e são escondidos por atributo, não removidos: o
`Ctrl+F` do navegador continua achando o conteúdo das outras seções, e o link
com âncora (`#risco`) abre direto na seção. Os gráficos são construídos com
tudo visível e só então as abas escondem o que não é da seção ativa — o
Chart.js mede o canvas na criação, e canvas dentro de container escondido mede
zero.

Além disso, o dashboard traz:

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
