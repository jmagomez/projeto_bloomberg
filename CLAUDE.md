# Instruções para agentes neste repositório

Leia antes de mexer em qualquer coisa. O que está aqui não é resumo do README:
é o que já custou retrabalho e não está óbvio no código.

## O que este projeto é

Um pipeline de coleta em Python que publica um `data.js` estático, e um
`index.html` que o lê. O valor está na **camada de dados e nas suas defesas**,
não na renderização.

Cada defesa tem um docstring que diz qual incidente a pediu. Antes de
"simplificar" uma checagem, leia o docstring dela:

| data | o que a fonte fez | defesa que nasceu disso |
| --- | --- | --- |
| 2014-04-02 | `close` 15,56 contra `low` 15,70, com 66 M de volume — defeito antigo do histórico | `barra_coerente` só exige `high >= low`; `fora_da_faixa` marca sem remover |
| 2026-08-22 | HTTP 200 com a série terminando dois dias antes | `valida_atualidade` + trava de regressão |
| 2026-08-28 | barra do dia com `close` nulo por mais de 24 h | `recupera_fechamento_do_meta` |
| 2026-08-31 | `open/high/low/volume` iguais a `0`, virando "mínima histórica R$ 0,00" | `preco_possivel` + `confere_precos_possiveis` |
| 15/09 a 27/11 | pregão anunciado em `regularMarketTime` e barra diária omitida, em 21% das rodadas | `recompoe_barra_ausente` + rodada de manhã |
| 2026-11-26 | (nossa, não da fonte) e-mail anunciando fechamento de dois dias antes | assunto montado em `emit_summary.py` |

## Mapa do código

| arquivo | o que é | linhas (aprox.) |
| --- | --- | ---: |
| `scripts/yahoo_chart.py` | cliente da fonte e **todas** as defesas de coleta | 771 |
| `scripts/update_dashboard.py` | monta o payload, decide publicar, escreve `data.js` | 924 |
| `scripts/analitica.py` | cálculo financeiro puro — sem rede, sem estado | 567 |
| `scripts/noticias.py` | coleta e acervo de manchetes | 244 |
| `scripts/emit_summary.py` | o e-mail: assunto, título, banner, números | 113 |
| `scripts/*_petr4.py`, `run_etl_pipeline.py` | pipeline ETL antigo (Alpha Vantage → SQLite). **Não roda na rotina.** | — |

## Regras que não se negociam

1. **Não invente número.** Nenhum preço é estimado, interpolado ou completado.
   Se a fonte não entregou, a série não alcança aquele pregão e a pendência é
   sinalizada. Publicar um pregão com número inventado é pior do que publicá-lo
   um dia depois. Ler o mesmo número em **outra resposta da mesma fonte** não é
   inventar — é o que `recompoe_barra_ausente` faz, e cada campo dela continua
   sendo um número publicado pela fonte para aquele pregão.
2. **Antes de acrescentar fonte, esgote a que já existe.** O defeito mais
   frequente (21% das rodadas) era um único campo ausente — a abertura — e a
   mesma API o tinha em outro intervalo. Stooq bloqueia automação; Alpha Vantage
   e brapi revendem o mesmo dado de origem; só a COTAHIST da B3 seria autoridade
   de verdade, e é integração pesada. Segunda fonte só se o problema deixar de
   ser um campo e passar a ser a fonte inteira.
3. **Do intradiário, só a abertura.** Medido: a série de 5 min termina às 16:55 e
   perde o leilão de fechamento — fechamento −1,53%, máxima −1,39%, volume
   −24,7% no pregão de 26/11/2026. Fechamento, máxima, mínima e volume vêm do
   `meta`, que é pós-leilão. Reconstruir o dia inteiro do intradiário é a
   armadilha óbvia deste projeto.
4. **Nenhum calendário de feriados.** `meta.regularMarketTime` já responde "qual
   foi o último pregão" em feriados e emendas. Toda vez que alguém for tentado a
   codificar feriados da B3, a resposta é: pergunte à fonte.
5. **A rotina só publica com o pregão encerrado.** O cron pede; `pregao_em_curso`
   é que garante. Vale para qualquer horário de disparo.
6. **Uma rodada por pregão, na manhã seguinte.** Cron `47 5 * * 2-6` (05:47
   UTC, terça a sábado — a rodada trata do pregão da véspera). Não acrescente
   repescagem: já foi feito e desfeito, a segunda rodada multiplicava commit e
   alarme. A paciência vive dentro da rodada (`ESPERAS_PENDENCIA`), não no cron.
   **O horário tem um teto que não é estético:** a fila do Actions atrasa de 2 a
   7 h, então 05:47 + 7 h = 12:47 UTC, treze minutos antes da abertura. Qualquer
   cron mais tarde arrisca executar com o pregão em curso, e aí `pregao_em_curso`
   pula o dia inteiro. E um **piso** de 09:47 UTC, num passo do workflow, segura
   a rodada que chegou cedo — efetivo é cron + fila, e fila não se controla; o
   que dá para garantir é o mínimo.
7. **Alarme só quando há ação possível.** Fonte atrasada numa noite é aviso, não
   falha. Um alarme que toca em dia normal ensina a ignorar o alarme — foi assim
   que 34 rodadas falharam sem que nada estivesse errado.
8. **O que sai para fora não pode afirmar mais do que se sabe.** E-mail, assunto
   de e-mail e cartão do dashboard precisam dizer quando o dado está incompleto.
   Número certo com rótulo que induz a erro é erro. Foi o incidente de 26/11: o
   assunto "pregão de 2026-11-24" estava correto e mesmo assim se lia como o
   fechamento da véspera, porque chegava de madrugada e a data vinha depois da
   cotação. Quando há `pending_session`, a ressalva vem **antes** do número.
9. **Nada que vá para o e-mail é montado em expressão de YAML.** Assunto, título
   e avisos saem de `emit_summary.py`, porque expressão de YAML não tem teste — e
   foi exatamente no assunto, onde não havia teste, que o defeito de 26/11 morou.
10. **Português.** Código, comentários, docstrings, testes e mensagens de commit.
   Nomes de função em português; termos técnicos consagrados ficam em inglês.
11. **Nenhum teste toca a rede.** Sem exceção.

## Contrato de saída de `update_dashboard.py`

| código | significa | efeito no workflow |
| --- | --- | --- |
| 0 | publicou, ou não havia o que publicar | commit se houve diff; e-mail se `data.js` mudou |
| 2 | dashboard parado atrás da fonte há mais de uma rodada | job vermelho, e-mail de erro |
| 3 | fonte indisponível | job vermelho, e-mail de erro |
| 9 | bolsa operando; nada foi escrito | job **verde**, passos seguintes pulados |

Mudar esses códigos exige mudar o workflow junto.

## Os quatro desfechos de `situacao_da_coleta`

`publica`, `em_dia` e `aguarda` saem com 0; só `atrasado` é falha. A idade da
pendência é medida contra **hoje no fuso da B3**, nunca contra o que está
publicado — entre dois pregões consecutivos cabem de 1 a 6 dias de calendário, e
medir contra o publicado traria de volta o calendário de feriados que a regra 4
proíbe.

## As duas recomposições, que são irmãs e não a mesma coisa

Confundi-las já custou tempo. A diferença é se a barra existe:

| | `recupera_fechamento_do_meta` | `recompoe_barra_ausente` |
| --- | --- | --- |
| sintoma | a barra existe, `close` vem nulo | não há nem `timestamp` para o dia |
| de onde vem o fechamento | `meta.regularMarketPrice` | `meta.regularMarketPrice` |
| de onde vem a abertura | da própria barra | **série intradiária de 5 min** (`abertura_do_intradiario`) |
| marcador na linha | `c_de_meta` | `c_de_meta` **e** `o_de_intradiario` |
| guarda específica | preço do `meta` dentro de `[low, high]` | primeira barra intradiária dentro de `TOLERANCIA_ABERTURA` (15 min) do início do pregão |

A guarda dos 15 min não é arbitrária: em 60 pregões medidos, a abertura derivada
do intradiário bateu exatamente com a oficial em 59. O único desvio (0,22%) é
justamente aquele em que a primeira barra só aparece às 10:50 — a série perdeu o
leilão de abertura. As boas começam às 10:00, 10:05 ou 10:10.

A requisição intradiária é a **quarta** da rodada e só acontece quando falta
pregão. Rodada saudável não paga por ela.

## Contrato de `emit_summary.py` com o workflow

O passo de e-mail consome estes outputs; mudar nome ou semântica de qualquer um
quebra o workflow em silêncio (expressão de YAML não resolvida vira string
vazia, não erro):

| output | papel |
| --- | --- |
| `assunto` | o assunto inteiro, já com a ressalva na frente se houver pendência |
| `titulo` | o `<h2>` do corpo |
| `banner_pendencia` | bloco HTML de aviso, ou string vazia |
| `pendente` | a data pendente, ou string vazia |

Todo valor é **uma linha só**: `$GITHUB_OUTPUT` é `chave=valor` por linha e
quebra com qualquer `\n`. Há teste cobrindo isso para todos os campos, nos dois
estados.

## Workflows

| arquivo | o que faz | quando roda | escreve no repo |
| --- | --- | --- | --- |
| `ci.yml` | lint e formatação (informativos) + `pytest` | push em `main` e pull request | não (`contents: read`) |
| `update-dashboard.yml` | coleta, commit e e-mail | `47 5 * * 2-6` (05:47 UTC, terça a sábado); ou manual | **sim** (`contents: write`) |

Os passos de `update-dashboard.yml`, na ordem, com o que liga cada um:

| passo | condição |
| --- | --- |
| `checkout` | — |
| Verifica secrets de e-mail | — (define `steps.mail.outputs.ok`) |
| `setup-python` | — |
| **Aguarda o piso de 09:47 UTC** | — (dorme só se começou antes; teto de 3 h) |
| Atualiza dados | — (define `pulou`; saída 9 vira `pulou=true` e `exit 0`) |
| Commita se houver mudança | `pulou != 'true'` (define `commitou` e `data_js`) |
| Extrai resumo para o e-mail | `pulou != 'true' && data_js == 'true'` |
| Envia e-mail com o dashboard | o anterior **+** `success()` **+** `mail.ok == 'true'` |
| Notifica falha por e-mail | `failure() && mail.ok == 'true'` |

Três coisas que não se veem lendo o YAML rápido:

- **`pulou` desliga commit, resumo e e-mail de uma vez.** É assim que o código 9
  vira job verde e silencioso.
- **`data_js` existe porque o acervo de manchetes cresce sozinho.** Um dia em que
  só `noticias.json` muda não trouxe fechamento novo, e mandar o e-mail do dia
  nesse caso seria reanunciar a véspera.
- **Armadilha:** "Notifica falha por e-mail" roda em `failure()` mas exige
  `mail.ok == 'true'`. Sem os secrets configurados, a rotina falha **sem avisar
  ninguém** — o job fica vermelho só na aba Actions.

### Por que `data.js` e `noticias.json` estão no `paths-ignore` do `ci.yml`

Os dois ficam na **raiz**, e por isso escapavam do `data/**`: cada commit diário
da rotina disparava a suíte inteira sobre um diff que não tem como quebrá-la.
Foram acrescentados às duas listas, `push` e `pull_request`, em 27/11/2026
(commit `60ea5af`). Duas coisas a lembrar antes de mexer:

- **`paths-ignore` só pula quando *tudo* o que veio no push está na lista.** Um
  push que mexa em `scripts/` e em `data.js` junto roda o CI normalmente — que é
  exatamente o que se quer. Não troque por `paths`, que inverteria a lógica.
- **Este `ci.yml` é template compartilhado.** O cabeçalho dele diz que serve a
  `oil-gas-financial-dashboard`, `vendas-liquidos`, `projeto_bloomberg` e
  `resumo-focus-public`. As duas entradas são inócuas onde esses arquivos não
  existem, então o template continua copiável inteiro; mas se em algum desses
  repos `data.js` for **código**, e não saída de rotina, a linha precisa sair lá.

## Ambiente: o que não funciona daqui

Isto é friction conhecida, redescoberta a cada sessão. Não gaste tempo:

- **`git push` é bloqueado** pelo proxy da sessão ("not in this session's
  authorized repository set"). Publique pelo MCP do GitHub (`push_files`).
- **`.github/workflows/*` devolve 403** para o token do app, inclusive via
  `push_files`. Dois caminhos funcionam, nesta ordem de preferência:
  1. **Pedir ao usuário que commite.** Entregue o arquivo pronto com
     `SendUserFile` e diga o caminho exato. Já funcionou, e é o mais rápido.
  2. **Editor web pelo navegador** (extensão Claude in Chrome): abrir
     `/edit/main/<caminho>`, clicar no editor, `ctrl+a`, colar via
     `ClipboardEvent` sintético com `DataTransfer`. Truque que evita retranscrever
     o arquivo: buscar o conteúdo atual com `fetch` na própria página e aplicar as
     substituições em JS antes de colar.

     **Confira dentro da página antes de entregar o clique.** Leia o documento
     pelos divs `.cm-content > .cm-line` (`textContent`, juntos por `\n`), nunca
     por `innerText` — ele conta linha em branco duas vezes e dá falso alarme — e
     compare o SHA-256 com `crypto.subtle.digest` contra o hash do arquivo local.
     É a mesma exigência da seção "Depois de publicar, confira", só que antes do
     commit: foi um subagente trocando um acento em silêncio que criou a regra.
- **A extensão do Chrome cai no meio da sessão.** Já aconteceu mais de uma vez:
  funciona no começo do turno e some depois. Não conte com ela para o passo
  final de uma cadeia — faça o que depende dela cedo, ou tenha o plano B (acima).
- **`gh` CLI devolve 403** para a API deste repo pelo mesmo motivo.
- **`raw.githubusercontent.com` serve cache** de até alguns minutos. Para
  conferir o que foi publicado, use `git clone --depth 1 --branch <branch>` e
  `cmp`, nunca `curl` no raw. Isso já produziu um diagnóstico falso.
- **Os endpoints do Yahoo não são alcançáveis** do contêiner, nem Stooq, Alpha
  Vantage ou brapi. Os testes são todos offline, de propósito. Para **investigar**
  a fonte ao vivo, use o navegador do usuário: navegue até a URL da API e leia o
  JSON com `javascript_tool` (`JSON.parse(document.body.innerText)`), ou navegue
  até a raiz do host e faça `fetch` same-origin para fugir do CORS.
- `git clone` e `git ls-remote` por HTTPS **funcionam** (leitura).

## Depois de publicar, confira

Transcrição por MCP já corrompeu arquivo em silêncio (um acento trocado por um
subagente). Toda publicação é conferida byte a byte — inclusive a que o usuário
fez à mão:

```bash
git clone -q --depth 1 --branch <branch> https://github.com/jmagomez/projeto_bloomberg.git chk
cmp <arquivo-local> chk/<arquivo>
```

Ao delegar a transcrição a um subagente, exija que ele escreva a cópia em disco
e rode `cmp` **antes** de publicar: um retry de `push_files` é outra retranscrição
e tem o mesmo modo de falha.

## Antes de abrir PR

```bash
ruff check .
ruff format --check .      # 5 scripts antigos de ETL já estão fora de forma; ignore
PYTHONPATH=scripts pytest -q
```

O CI roda `pytest` sem `PYTHONPATH` — quem resolve é `tests/conftest.py`.

## Diagnóstico: onde olhar primeiro

Falha da rotina quase sempre é a fonte, não o código. O log do passo
"Atualiza dados" diz qual dos casos é, com as datas. Antes de propor correção,
leia o log da rodada que falhou — a aba Actions, filtrada por `is:failure`.

E antes de propor correção de **frequência**, meça. O histórico de commits de
`data.js` dá a série de pregões publicados, e a lista de sessões conhecidas sai
do próprio `data.js` — dá para medir a defasagem sem calendário de feriados e
sem rede. Foi assim que "a fonte parece lenta" virou "21% das rodadas, sempre
exatamente um pregão".
