# Instruções para agentes neste repositório

Leia antes de mexer em qualquer coisa. O que está aqui não é resumo do README:
é o que já custou retrabalho e não está óbvio no código.

## O que este projeto é

Um pipeline de coleta em Python que publica um `data.js` estático, e um
`index.html` que o lê. O valor está na **camada de dados e nas suas defesas**,
não na renderização. Cinco incidentes moldaram o código; cada defesa tem um
docstring que diz qual incidente a pediu. Antes de "simplificar" uma checagem,
leia o docstring dela.

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

## Os quatro desfechos de `situacao_da_coleta`

Antes de mexer: `publica`, `em_dia` e `aguarda` saem com 0; só `atrasado` é
falha. A idade da pendência é medida contra **hoje no fuso da B3**, nunca contra
o que está publicado — entre dois pregões consecutivos cabem de 1 a 6 dias de
calendário, e medir contra o publicado traria de volta o calendário de feriados
que a regra 4 proíbe.


## Workflows

| arquivo | o que faz | quando roda | escreve no repo |
|---|---|---|---|
| `ci.yml` | lint, formatação e `pytest` | push e pull request | não (`contents: read`) |
| `update-dashboard.yml` | `update_dashboard.py`, commit, e-mail com o dashboard | `47 21 * * 1-5` (18h47 BRT, dia útil); ou manual | **sim** |

`update-dashboard.yml` consome o contrato acima pelo output `pulou` do passo "Atualiza
dados", que desliga commit, resumo e e-mail de uma vez — é assim que o código 9 vira job
verde e silencioso. O e-mail do dashboard exige também `data_js == 'true'`: dado que não
mudou não gera e-mail.

Armadilha: o passo "Notifica falha por e-mail" roda em `failure()`, mas exige
`steps.mail.outputs.ok == 'true'`, definido no primeiro passo. Sem os secrets de e-mail
configurados, a rotina falha **sem avisar ninguém** — o job fica vermelho apenas na aba
Actions.

## Ambiente: o que não funciona daqui

Isto é friction conhecida, redescoberta a cada sessão. Não gaste tempo:

- **`git push` é bloqueado** pelo proxy da sessão ("not in this session's
  authorized repository set"). Publique pelo MCP do GitHub (`push_files`).
- **`.github/workflows/*` devolve 403** para o token do app, inclusive via
  `push_files`. O caminho que funciona é o editor web do GitHub pelo navegador
  (extensão Claude in Chrome): abrir `/edit/main/<caminho>`, clicar no editor,
  `ctrl+a`, e colar via `ClipboardEvent` sintético com `DataTransfer`.
- **`gh` CLI devolve 403** para a API deste repo pelo mesmo motivo.
- **`raw.githubusercontent.com` serve cache** de até alguns minutos. Para
  conferir o que foi publicado, use `git clone --depth 1 --branch <branch>` e
  `cmp`, nunca `curl` no raw.
- **Os endpoints do Yahoo não são alcançáveis** do contêiner. Não tente testar a
  coleta de ponta a ponta aqui; os testes são todos offline, de propósito.
- `git clone` e `git ls-remote` por HTTPS **funcionam** (leitura).

## Depois de publicar, confira

Transcrição por MCP já corrompeu arquivo em silêncio (um acento trocado por um
subagente). Toda publicação é conferida byte a byte:

```bash
git clone -q --depth 1 --branch <branch> https://github.com/jmagomez/projeto_bloomberg.git chk
cmp <arquivo-local> chk/<arquivo>
```

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
