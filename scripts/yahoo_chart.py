"""Cliente da chart API do Yahoo Finance, com as defesas que os incidentes pediram.

A rotina do dashboard já publicou, sem checagem, qualquer série devolvida com
HTTP 200. Dois incidentes moldaram o que está aqui:

**2026-08-22 — série truncada.** O endpoint respondeu 200 com a série terminando
em 2026-08-20, embora o pregão de 2026-08-21 já estivesse fechado havia ~16 h; a
mesma consulta, repetida depois, devolveu a sexta normalmente. O dashboard passou
uma semana exibindo o penúltimo pregão.

**2026-08-28 — fechamento nulo.** O Yahoo passou a servir a barra do pregão com
``open``, ``high``, ``low`` e ``volume`` preenchidos e ``close`` nulo, e assim
ficou por mais de um dia. O fechamento estava na mesma resposta, em
``meta.regularMarketPrice``. Como nenhum retry resolvia, a rotina falhava toda
noite e o dashboard ia acumulando atraso.

As defesas, nesta ordem:

1. ``recupera_fechamento_do_meta`` recompõe a última barra a partir do
   ``meta.regularMarketPrice`` da própria resposta, sob condições estritas.
2. ``valida_atualidade`` compara ``meta.regularMarketTime`` (qual foi o último
   pregão, na visão da fonte) com o último ponto de ``timestamp`` (qual foi
   entregue) e **sinaliza** a pendência em vez de derrubar o job.
3. Quem decide publicar é ``update_dashboard``: avanço parcial sinalizado vale
   mais que dashboard parado; sem avanço nenhum, aí sim falha.

Nada é estimado, interpolado ou completado: todo número vem da resposta da fonte.
Nenhum calendário de feriados é necessário — ``regularMarketTime`` já responde
"qual foi o último pregão" mesmo em feriados e emendas.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from urllib.parse import quote

import requests

CHART_URL = "https://{host}/v8/finance/chart/{symbol}"
HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
HEADERS = {"User-Agent": "Mozilla/5.0 (projeto_bloomberg dashboard-updater)"}

# Códigos que valem uma nova tentativa (rate limit e indisponibilidade
# temporária). O 401/403 entra porque os nós do Yahoo às vezes exigem cookie em
# um host e não no outro — alternar de host costuma resolver.
RETRIABLE_STATUS = {401, 403, 429, 500, 502, 503, 504}

TENTATIVAS = 4
ESPERA_BASE = 5.0  # segundos; dobra a cada tentativa (5, 10, 20)
TIMEOUT = 60

# Folga aceita entre os campos de uma mesma barra. O Yahoo arredonda open,
# high, low e close separadamente, então uma barra legítima pode sair alguns
# centésimos fora da faixa. 0,5% barra lixo sem derrubar arredondamento.
TOLERANCIA_OHLC = 0.005


class ErroTransitorio(RuntimeError):
    """Falha que vale a pena repetir (rede, rate limit, 5xx)."""


class DadosDesatualizadosError(RuntimeError):
    """A fonte respondeu, mas sem o último pregão que ela mesma diz existir."""


def data_da_bolsa(ts: int, gmtoffset: int) -> str:
    """Converte um epoch para a data-calendário **no fuso da bolsa**.

    O pregão da B3 abre às 10:00 BRT, o que hoje cai às 13:00 UTC — converter em
    UTC dá a data certa por coincidência. Usar ``gmtoffset`` (que vem na própria
    resposta) mantém a conversão correta caso o Yahoo passe a carimbar as barras
    em outro horário ou o fuso do país mude.
    """
    return datetime.fromtimestamp(ts + gmtoffset, tz=UTC).strftime("%Y-%m-%d")


def _requisita(host: str, symbol: str, params: dict) -> dict:
    url = CHART_URL.format(host=host, symbol=quote(symbol, safe=""))
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ErroTransitorio(f"erro de rede em {host}: {exc}") from exc

    if resp.status_code in RETRIABLE_STATUS:
        raise ErroTransitorio(f"HTTP {resp.status_code} em {host}")
    resp.raise_for_status()

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ErroTransitorio(f"resposta não-JSON em {host}: {exc}") from exc

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ErroTransitorio(f"erro da API em {host}: {chart['error']}")
    resultados = chart.get("result") or []
    if not resultados:
        raise ErroTransitorio(f"resposta sem 'result' em {host}")
    return resultados[0]


def preco_possivel(x: object) -> float | None:
    """Converte para ``float`` só o que pode ser preço de uma ação listada.

    Devolve ``None`` para nulo, para o que não é número, para NaN/infinito e
    para qualquer valor **menor ou igual a zero**. Foi essa última peneira que
    faltou em 2026-08-31: o Yahoo entregou a barra do pregão com ``open``,
    ``high``, ``low`` e ``volume`` iguais a ``0`` (não ``null``) e o fechamento
    correto. A checagem de então só olhava ``None``, os zeros passaram, e o
    dashboard publicou abertura, máxima, mínima e volume zerados — e, pior, uma
    "mínima histórica" de R$ 0,00, porque o zero virou o menor valor da série
    inteira.
    """
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def barra_coerente(o: float, h: float, low: float, c: float) -> bool:
    """A barra descreve um pregão estruturalmente possível?

    A única checagem é ``high >= low``: máxima abaixo da mínima não descreve
    pregão nenhum, em nenhuma leitura.

    **Por que não checar também se abertura e fechamento caem dentro da faixa
    do dia.** Era o que esta função fazia na primeira versão, e ela descartava
    2014-04-02 — pregão real, volume real de 66 M, em que o Yahoo publica
    ``close`` 15,56 contra ``low`` 15,70. Os 0,9% de inconsistência são um
    defeito antigo do histórico da fonte, não uma barra suja: cada campo é uma
    observação legítima. Descartá-la abriria um buraco de um dia na série desde
    2010, e a trava de regressão barrou a publicação — corretamente.

    Preço fora da faixa não fica sem registro: ``fora_da_faixa`` marca a barra
    para o log, sem removê-la. Quem separa lixo de ruído aqui é
    ``preco_possivel`` — zero e negativo são impossíveis e continuam barrados,
    e era só disso que a barra de 2026-08-31 precisava.
    """
    return h >= low


def fora_da_faixa(o: float, h: float, low: float, c: float) -> bool:
    """Abertura ou fechamento fora da faixa ``[low, high]`` da própria barra.

    Não reprova a barra — só merece uma linha no log. A tolerância existe
    porque o Yahoo arredonda cada campo por conta própria.
    """
    return not (low * (1 - TOLERANCIA_OHLC) <= min(o, c) and max(o, c) <= h * (1 + TOLERANCIA_OHLC))


def extrai_pregoes(res: dict) -> list[dict]:
    """Converte a resposta em linhas diárias completas.

    Descarta a barra inteira quando qualquer campo OHLC é nulo, impossível
    (zero, negativo, NaN) ou estruturalmente absurdo (máxima abaixo da mínima).
    O Yahoo publica barras parciais enquanto consolida o pregão — às vezes com
    ``null``, às vezes com ``0`` — e arrastar isso adiante contamina a série
    toda: em 2026-08-31 um zero virou a "mínima histórica" do dashboard.

    Inconsistência leve **não** descarta: a barra vai marcada com
    ``fora_faixa`` para o log e é publicada como veio. Ver ``barra_coerente``.

    Barra descartada não é reinventada: a série simplesmente não alcança aquele
    pregão, ``valida_atualidade`` marca a pendência, e a repescagem da manhã
    seguinte pega a barra já consolidada. É o que se quer — publicar um pregão
    com número inventado seria pior do que publicá-lo algumas horas depois.
    """
    meta = res.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    timestamps = res.get("timestamp") or []
    cotacoes = ((res.get("indicators") or {}).get("quote") or [{}])[0]

    abertura = cotacoes.get("open") or []
    maxima = cotacoes.get("high") or []
    minima = cotacoes.get("low") or []
    fechamento = cotacoes.get("close") or []
    volume = cotacoes.get("volume") or []

    linhas = []
    for i, ts in enumerate(timestamps):
        try:
            bruto = (abertura[i], maxima[i], minima[i], fechamento[i])
        except IndexError:
            continue
        o, h, low, c = (preco_possivel(x) for x in bruto)
        if None in (o, h, low, c) or not barra_coerente(o, h, low, c):
            continue
        vol = volume[i] if i < len(volume) else 0
        linha = {
            "d": data_da_bolsa(ts, offset),
            "o": o,
            "h": h,
            "l": low,
            "c": c,
            "v": int(vol or 0),
        }
        if fora_da_faixa(o, h, low, c):
            linha["fora_faixa"] = True
        linhas.append(linha)
    return linhas


def extrai_proventos(res: dict) -> dict[str, float]:
    """Proventos (dividendos + JCP) por ação, por data-ex.

    O Yahoo não separa dividendo de JCP: cada evento já traz o montante
    distribuído por ação naquela data.
    """
    meta = res.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    eventos = ((res.get("events") or {}).get("dividends")) or {}
    por_data: dict[str, float] = {}
    for ev in eventos.values():
        try:
            data = data_da_bolsa(int(ev["date"]), offset)
            valor = float(ev["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        por_data[data] = round(por_data.get(data, 0.0) + valor, 4)
    return por_data


def recupera_fechamento_do_meta(res: dict, linhas: list[dict]) -> tuple[list[dict], str | None]:
    """Recompõe a última barra quando o Yahoo entrega ``close`` nulo.

    Em 2026-08-28 o Yahoo passou a servir a barra do pregão com ``open``,
    ``high``, ``low`` e ``volume`` preenchidos mas ``close`` (e ``adjclose``)
    nulos — e assim ficou por mais de um dia, o que nenhum retry resolveria. O
    fechamento, porém, estava na mesma resposta, em ``meta.regularMarketPrice``,
    junto com ``regularMarketDayHigh/Low/Volume`` batendo com a própria barra.

    Nada é estimado: o valor vem da mesma resposta, e só é aceito quando

    * o pregão já fechou (``regularMarketTime`` alcançou o fim do horário
      regular) — barra em andamento nunca é recomposta;
    * a barra faltante é a **última** da série e é justamente a do pregão que o
      ``meta`` reporta;
    * ``open``, ``high``, ``low`` da barra estão preenchidos;
    * o preço do ``meta`` cai dentro da faixa ``[low, high]`` da própria barra.

    Devolve ``(linhas, data_recomposta_ou_None)``.
    """
    meta = res.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    market_time = meta.get("regularMarketTime")
    preco = meta.get("regularMarketPrice")
    if not market_time or preco in (None, 0):
        return linhas, None

    periodo = ((meta.get("currentTradingPeriod") or {}).get("regular")) or {}
    fim = periodo.get("end")
    if fim and int(market_time) < int(fim):
        return linhas, None  # pregão em andamento

    data_meta = data_da_bolsa(int(market_time), offset)
    if linhas and linhas[-1]["d"] >= data_meta:
        return linhas, None  # a série já alcança o pregão

    timestamps = res.get("timestamp") or []
    if not timestamps or data_da_bolsa(int(timestamps[-1]), offset) != data_meta:
        return linhas, None  # a barra faltante não é a última da série

    cotacoes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    i = len(timestamps) - 1
    try:
        o = preco_possivel(cotacoes["open"][i])
        h = preco_possivel(cotacoes["high"][i])
        low = preco_possivel(cotacoes["low"][i])
    except (KeyError, IndexError):
        return linhas, None
    if None in (o, h, low):
        # Abertura, máxima ou mínima ausentes ou impossíveis. O ``meta`` traz
        # regularMarketDayHigh/Low/Volume, mas **não** traz a abertura — não há
        # de onde tirar esse campo sem inventá-lo, então a barra não é
        # recomposta. Fica pendente e a repescagem da manhã resolve.
        return linhas, None

    fechamento = preco_possivel(preco)
    if fechamento is None or not (low <= fechamento <= h):
        return linhas, None  # incoerente com a própria barra: não usa

    volumes = cotacoes.get("volume") or []
    vol = volumes[i] if i < len(volumes) else 0
    linhas = linhas + [
        {
            "d": data_meta,
            "o": float(o),
            "h": float(h),
            "l": float(low),
            "c": fechamento,
            "v": int(vol or 0),
            "c_de_meta": True,
        }
    ]
    return linhas, data_meta


def estado_do_mercado(res: dict) -> dict:
    """Lê da resposta o que a fonte diz sobre o último pregão.

    Retorna ``{"ultimo_pregao": "YYYY-MM-DD" | None, "aberto": bool}``.
    ``ultimo_pregao`` é ``None`` quando a resposta não traz
    ``regularMarketTime`` — nesse caso não há como validar e a rotina apenas
    avisa, em vez de falhar por falta de informação.
    """
    meta = res.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    market_time = meta.get("regularMarketTime")

    periodo = ((meta.get("currentTradingPeriod") or {}).get("regular")) or {}
    inicio, fim = periodo.get("start"), periodo.get("end")
    agora = int(datetime.now(UTC).timestamp())
    aberto = bool(inicio and fim and int(inicio) <= agora < int(fim))

    ultimo = data_da_bolsa(int(market_time), offset) if market_time else None
    return {"ultimo_pregao": ultimo, "aberto": aberto}


def _mescla(base: list[dict], extra: list[dict]) -> list[dict]:
    """Une duas séries por data; a de ``extra`` prevalece em caso de empate.

    Serve para o caso em que a consulta longa vem de um nó com cache velho e a
    consulta curta (outra chave de cache) já tem o pregão mais recente. São
    dados da mesma fonte — nada é estimado.
    """
    por_data = {linha["d"]: linha for linha in base}
    for linha in extra:
        por_data[linha["d"]] = linha
    return [por_data[d] for d in sorted(por_data)]


def _uma_tentativa(
    symbol: str, period1: int
) -> tuple[list[dict], dict[str, float], dict, list[str]]:
    agora = int(datetime.now(UTC).timestamp())
    params_longo = {
        "period1": period1,
        "period2": agora,
        "interval": "1d",
        "events": "div",
    }
    params_curto = {"range": "1mo", "interval": "1d", "events": "div"}

    avisos: list[str] = []
    recomposicoes: set[str] = set()
    serie_longa: list[dict] = []
    proventos: dict[str, float] = {}
    estado_melhor: dict | None = None
    falhas: list[str] = []

    # Série completa: o primeiro host que responder resolve.
    for host in HOSTS:
        try:
            res = _requisita(host, symbol, params_longo)
        except ErroTransitorio as exc:
            falhas.append(str(exc))
            continue
        serie_longa, recomposta = recupera_fechamento_do_meta(res, extrai_pregoes(res))
        if recomposta:
            recomposicoes.add(recomposta)
        proventos = extrai_proventos(res)
        estado_melhor = estado_do_mercado(res)
        break

    if not serie_longa:
        raise ErroTransitorio("nenhum host devolveu a série completa: " + "; ".join(falhas))

    # Sondagens curtas nos dois hosts: barata (≈1 mês de pregões) e com chave de
    # cache diferente da consulta longa. Serve para (a) descobrir o pregão mais
    # recente que a fonte conhece e (b) completar o rabo da série.
    for host in HOSTS:
        try:
            res = _requisita(host, symbol, params_curto)
        except ErroTransitorio as exc:
            avisos.append(f"sondagem em {host} falhou: {exc}")
            continue
        curta, recomposta = recupera_fechamento_do_meta(res, extrai_pregoes(res))
        if recomposta:
            recomposicoes.add(recomposta)
        serie_longa = _mescla(serie_longa, curta)
        proventos.update(extrai_proventos(res))
        estado = estado_do_mercado(res)
        if estado["ultimo_pregao"] and (
            estado_melhor is None
            or not estado_melhor["ultimo_pregao"]
            or estado["ultimo_pregao"] > estado_melhor["ultimo_pregao"]
        ):
            estado_melhor = estado

    estado = estado_melhor or {"ultimo_pregao": None, "aberto": False}
    if recomposicoes:
        alvo = max(recomposicoes)
        if any(linha["d"] == alvo for linha in serie_longa):
            avisos.append(
                f"a barra de {alvo} veio com 'close' nulo; fechamento recomposto a "
                "partir de 'meta.regularMarketPrice' da mesma resposta"
            )
    estado["fechamento_recomposto"] = max(recomposicoes) if recomposicoes else None
    return serie_longa, proventos, estado, avisos


def valida_atualidade(linhas: list[dict], estado: dict) -> tuple[list[dict], list[str], str | None]:
    """Confere se a série alcança o último pregão que a fonte reporta.

    Devolve ``(linhas, avisos, pendente)``. ``pendente`` é a data do pregão que
    a fonte diz existir mas não entregou — ``None`` quando está tudo em dia.

    Quem decide o que fazer com um pregão pendente é ``update_dashboard``: se a
    coleta ainda assim avança em relação ao que está publicado, vale mais
    publicar o avanço (sinalizado) do que deixar o dashboard parado; se não
    avança nada, aí sim o job falha. Antes disso, qualquer pendência derrubava a
    rotina — e o dashboard acumulava dias de atraso enquanto a fonte não se
    resolvia.

    Se o pregão ainda estiver em andamento, a barra parcial do dia é descartada.
    """
    avisos: list[str] = []
    if not linhas:
        raise DadosDesatualizadosError("a fonte devolveu uma série vazia")

    esperado = estado.get("ultimo_pregao")

    if estado.get("aberto"):
        if esperado and linhas[-1]["d"] == esperado:
            linhas = linhas[:-1]
            avisos.append(
                f"pregão de {esperado} em andamento — barra parcial descartada; "
                "os dados vão até o pregão anterior"
            )
        if not linhas:
            raise DadosDesatualizadosError("só havia a barra parcial do pregão em andamento")
        return linhas, avisos, None

    if not esperado:
        avisos.append(
            "a resposta não trouxe 'meta.regularMarketTime'; não foi possível "
            "confirmar se a série alcança o último pregão"
        )
        return linhas, avisos, None

    obtido = linhas[-1]["d"]
    if obtido < esperado:
        avisos.append(
            f"a fonte informa que o último pregão fechado é {esperado}, mas a série "
            f"entregue termina em {obtido}"
        )
        return linhas, avisos, esperado
    return linhas, avisos, None


def busca_serie_diaria(
    symbol: str, period1: int
) -> tuple[list[dict], dict[str, float], dict, list[str]]:
    """Baixa a série diária validada.

    Repete a consulta quando a resposta vem incompleta — o cache do Yahoo é por
    nó e às vezes normaliza em segundos. Esgotadas as tentativas, devolve o que
    conseguiu com ``estado["pendente"]`` preenchido, em vez de levantar: a
    decisão de publicar ou não é de quem chama.
    """
    ultima_falha: Exception | None = None
    resultado = None
    for tentativa in range(TENTATIVAS):
        if tentativa:
            espera = ESPERA_BASE * 2 ** (tentativa - 1)
            print(
                f"[update] tentativa {tentativa + 1}/{TENTATIVAS} em {espera:.0f}s "
                f"({ultima_falha})",
                flush=True,
            )
            time.sleep(espera)
        try:
            linhas, proventos, estado, avisos = _uma_tentativa(symbol, period1)
            linhas, avisos_val, pendente = valida_atualidade(linhas, estado)
            estado["pendente"] = pendente
            resultado = (linhas, proventos, estado, avisos + avisos_val)
            if not pendente:
                return resultado
            ultima_falha = DadosDesatualizadosError("; ".join(avisos_val) or "pregão pendente")
        except (ErroTransitorio, DadosDesatualizadosError) as exc:
            ultima_falha = exc

    if resultado is not None:
        return resultado
    raise ErroTransitorio(
        f"Yahoo Finance indisponível após {TENTATIVAS} tentativas ({ultima_falha})"
    ) from ultima_falha


def busca_fechamentos(symbol: str, period1: int) -> dict[str, float]:
    """Série de fechamentos diários de um símbolo auxiliar (ex.: ^BVSP).

    Usada só para comparação no dashboard. Devolve ``{data: fechamento}`` e
    nunca levanta: se o símbolo de referência falhar, o dashboard segue sem o
    painel de comparação — não faz sentido derrubar a rotina da PETR4 por causa
    do índice.
    """
    agora = int(datetime.now(UTC).timestamp())
    params = {"period1": period1, "period2": agora, "interval": "1d"}
    for host in HOSTS:
        try:
            res = _requisita(host, symbol, params)
        except ErroTransitorio:
            continue
        linhas, _ = recupera_fechamento_do_meta(res, extrai_pregoes(res))
        if linhas:
            return {linha["d"]: round(linha["c"], 2) for linha in linhas}
    return {}
