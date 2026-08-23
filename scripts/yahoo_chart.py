"""Cliente da chart API do Yahoo Finance com validação de atualidade.

Motivação
---------
A rotina do dashboard publicava, sem checagem, qualquer série devolvida com
HTTP 200. Em 2026-08-22 (sábado, 12:21 UTC) o endpoint respondeu 200 com a
série terminando em 2026-08-20 (quinta), embora o pregão de 2026-08-21 (sexta)
já estivesse fechado havia ~16 h — a mesma consulta, repetida depois, devolveu
a sexta normalmente. Resultado: o dashboard ficou uma semana inteira exibindo o
penúltimo pregão.

A defesa implementada aqui não inventa nem estima preço nenhum. Ela apenas
compara duas informações que a *própria resposta* do Yahoo traz:

* ``meta.regularMarketTime`` — instante do último negócio consolidado, ou seja,
  qual foi o último pregão na visão da fonte;
* o último ponto do array ``timestamp`` — qual foi o último pregão realmente
  entregue na série.

Se o segundo for anterior ao primeiro, a série está desatualizada. Nesse caso a
rotina reconsulta (outro host e outra janela, que têm cache independente) e, se
ainda assim faltar o pregão, levanta ``DadosDesatualizadosError`` — o job falha
e o dashboard mantém o dado anterior, correto, em vez de publicar defasagem
silenciosa.

Nenhum calendário de feriados da B3 é necessário: ``regularMarketTime`` já
responde "qual foi o último pregão" mesmo em feriados e emendas.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

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
    url = CHART_URL.format(host=host, symbol=symbol)
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


def extrai_pregoes(res: dict) -> list[dict]:
    """Converte a resposta em linhas diárias completas.

    Descarta barras com qualquer campo OHLC nulo: o Yahoo publica barras
    parciais (todos os campos ``null``) enquanto consolida o pregão, e
    arredondá-las adiante quebraria a rotina.
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
            o, h, low, c = abertura[i], maxima[i], minima[i], fechamento[i]
        except IndexError:
            continue
        if o is None or h is None or low is None or c is None:
            continue
        vol = volume[i] if i < len(volume) else 0
        linhas.append(
            {
                "d": data_da_bolsa(ts, offset),
                "o": float(o),
                "h": float(h),
                "l": float(low),
                "c": float(c),
                "v": int(vol or 0),
            }
        )
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
        serie_longa = extrai_pregoes(res)
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
        serie_longa = _mescla(serie_longa, extrai_pregoes(res))
        proventos.update(extrai_proventos(res))
        estado = estado_do_mercado(res)
        if estado["ultimo_pregao"] and (
            estado_melhor is None
            or not estado_melhor["ultimo_pregao"]
            or estado["ultimo_pregao"] > estado_melhor["ultimo_pregao"]
        ):
            estado_melhor = estado

    return serie_longa, proventos, estado_melhor or {"ultimo_pregao": None, "aberto": False}, avisos


def valida_atualidade(linhas: list[dict], estado: dict) -> tuple[list[dict], list[str]]:
    """Confere se a série alcança o último pregão que a fonte reporta.

    Levanta ``DadosDesatualizadosError`` se faltar. Se o pregão ainda estiver em
    andamento, descarta a barra parcial do dia e devolve um aviso — a rotina
    normal roda depois do fechamento, então esse caminho só aparece em execuções
    manuais durante o horário do pregão.
    """
    avisos: list[str] = []
    if not linhas:
        raise DadosDesatualizadosError("a fonte devolveu uma série vazia")

    esperado = estado.get("ultimo_pregao")

    if estado.get("aberto"):
        if esperado and linhas and linhas[-1]["d"] == esperado:
            linhas = linhas[:-1]
            avisos.append(
                f"pregão de {esperado} em andamento — barra parcial descartada; "
                "os dados vão até o pregão anterior"
            )
        if not linhas:
            raise DadosDesatualizadosError("só havia a barra parcial do pregão em andamento")
        return linhas, avisos

    if not esperado:
        avisos.append(
            "a resposta não trouxe 'meta.regularMarketTime'; não foi possível "
            "confirmar se a série alcança o último pregão"
        )
        return linhas, avisos

    obtido = linhas[-1]["d"]
    if obtido < esperado:
        raise DadosDesatualizadosError(
            f"série desatualizada: a fonte informa que o último pregão fechado é "
            f"{esperado}, mas a série entregue termina em {obtido}"
        )
    return linhas, avisos


def busca_serie_diaria(
    symbol: str, period1: int
) -> tuple[list[dict], dict[str, float], dict, list[str]]:
    """Baixa a série diária validada.

    Repete a consulta inteira quando a resposta vem desatualizada — o cache do
    Yahoo é por nó e costuma normalizar em segundos. Só depois de esgotar as
    tentativas é que o erro sobe e derruba o job.
    """
    ultima_falha: Exception | None = None
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
            linhas, avisos_validacao = valida_atualidade(linhas, estado)
            return linhas, proventos, estado, avisos + avisos_validacao
        except (ErroTransitorio, DadosDesatualizadosError) as exc:
            ultima_falha = exc

    if isinstance(ultima_falha, DadosDesatualizadosError):
        raise DadosDesatualizadosError(
            f"{ultima_falha} — após {TENTATIVAS} tentativas. Nada foi publicado: "
            "o dashboard mantém o último dado íntegro."
        ) from ultima_falha
    raise ErroTransitorio(
        f"Yahoo Finance indisponível após {TENTATIVAS} tentativas ({ultima_falha})"
    ) from ultima_falha
