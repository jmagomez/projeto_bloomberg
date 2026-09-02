"""Manchetes sobre a Petrobras, coletadas a cada rodada e acumuladas em arquivo.

**O que este módulo faz e o que ele deliberadamente não faz.**

Ele coleta manchetes reais, datadas e atribuídas — título, veículo, link e
horário de publicação — e as guarda por data de pregão. O dashboard as exibe ao
lado da variação do dia.

Ele **não** afirma que a ação subiu ou caiu *por causa* de nenhuma delas. Essa
atribuição exigiria um julgamento que nem a fonte nem esta rotina têm como
fazer: correlação entre uma manchete e um movimento de preço no mesmo dia não
establece causa, e uma rotina automática que escrevesse "a ação caiu porque X"
estaria produzindo análise inventada com aparência de fato. O que se entrega é
o contexto datado e a fonte primária a um clique; a leitura causal é do
analista, que é quem tem o resto do quadro.

**Por que o histórico é acumulado.** O endpoint de busca do Yahoo devolve só as
manchetes recentes — não há arquivo consultável para trás. Então cada rodada
mescla o que encontrou ao que já estava guardado, deduplicando por link. O
arquivo cresce um pregão por vez; nos primeiros dias há pouca coisa, e isso é
mostrado como está, sem preencher buraco nenhum.

**Relevância é filtrada mecanicamente.** O endpoint devolve muita matéria de
mercado amplo que apenas cita PBR entre dezenas de tickers ("Wall Street's top
analyst calls" com 18 papéis). O filtro exige que o título mencione a empresa
**ou** que a matéria tenha poucos tickers relacionados — sinal de que é sobre a
companhia, não uma retrospectiva de mercado.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import requests

BUSCA_URL = "https://{host}/v1/finance/search"
HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
HEADERS = {"User-Agent": "Mozilla/5.0 (projeto_bloomberg dashboard-updater)"}
TIMEOUT = 30

# O Yahoo indexa a companhia pelos ADRs; a busca por "PETR4.SA" volta vazia.
CONSULTAS = ("PBR", "Petrobras")

# Fuso da B3, para carimbar cada manchete com a data de pregão correspondente.
OFFSET_B3 = -10800

# Tickers que caracterizam uma matéria sobre a companhia.
TICKERS_DA_EMPRESA = {"PBR", "PBR-A", "PETR4.SA", "PETR3.SA"}

# Acima disto a matéria é retrospectiva de mercado, não notícia da empresa.
MAX_TICKERS_RELACIONADOS = 8

# Quantas manchetes o arquivo guarda. ~1 ano de cobertura com folga; o arquivo
# fica na casa de algumas centenas de KB e não pesa no repositório.
LIMITE_ARQUIVO = 1200

# Quantos pregões de manchetes acompanham o data.js. O resto fica no arquivo.
PREGOES_NO_PAYLOAD = 120

PADRAO_EMPRESA = re.compile(r"petrobras|petrobr|\bpbr\b|\bpetr[34]\b", re.IGNORECASE)


def _relevante(item: dict) -> bool:
    titulo = item.get("title") or ""
    if PADRAO_EMPRESA.search(titulo):
        return True
    tickers = item.get("relatedTickers") or []
    if len(tickers) > MAX_TICKERS_RELACIONADOS:
        return False
    return bool(TICKERS_DA_EMPRESA.intersection(tickers))


def _normaliza(item: dict) -> dict | None:
    titulo = (item.get("title") or "").strip()
    link = (item.get("link") or "").strip()
    quando = item.get("providerPublishTime")
    if not titulo or not link or not quando:
        return None
    try:
        instante = datetime.fromtimestamp(int(quando) + OFFSET_B3, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None
    return {
        "d": instante.strftime("%Y-%m-%d"),
        "hora": instante.strftime("%H:%M"),
        "titulo": titulo,
        "veiculo": (item.get("publisher") or "").strip() or "n/d",
        "link": link,
        "ts": int(quando),
    }


def busca_manchetes() -> list[dict]:
    """Consulta o endpoint de busca. Nunca levanta: falhou, devolve o que tem.

    O dashboard não pode parar de publicar cotação porque um feed de notícia
    saiu do ar.
    """
    encontradas: dict[str, dict] = {}
    for consulta in CONSULTAS:
        for host in HOSTS:
            try:
                resp = requests.get(
                    BUSCA_URL.format(host=host),
                    params={"q": consulta, "quotesCount": 0, "newsCount": 20},
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                itens = resp.json().get("news") or []
            except (requests.RequestException, ValueError):
                continue
            for item in itens:
                if not _relevante(item):
                    continue
                normalizada = _normaliza(item)
                if normalizada:
                    encontradas[normalizada["link"]] = normalizada
            break  # um host respondeu; não precisa do outro para esta consulta
    return sorted(encontradas.values(), key=lambda x: x["ts"], reverse=True)


def le_arquivo(caminho: Path) -> list[dict]:
    """Lê o acervo já guardado. Arquivo ausente ou corrompido vira lista vazia."""
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return dados if isinstance(dados, list) else []


def mescla(acervo: list[dict], novas: list[dict], limite: int = LIMITE_ARQUIVO) -> list[dict]:
    """Une o que já havia com o que chegou, deduplicando por link.

    O item já guardado prevalece: se o Yahoo reescrever um título depois, o
    dashboard continua mostrando o que estava publicado quando o pregão
    aconteceu — que é o que interessa para quem olha a série depois.
    """
    por_link = {item["link"]: item for item in novas}
    por_link.update({item["link"]: item for item in acervo if item.get("link")})
    ordenadas = sorted(por_link.values(), key=lambda x: x.get("ts", 0), reverse=True)
    return ordenadas[:limite]


def grava_arquivo(caminho: Path, acervo: list[dict]) -> None:
    caminho.write_text(json.dumps(acervo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def por_pregao(acervo: list[dict], datas: list[str], pregoes: int = PREGOES_NO_PAYLOAD) -> dict:
    """Agrupa as manchetes pelas datas de pregão pedidas, das mais recentes.

    Só entram datas que **são** pregão: manchete de sábado não inventa sessão.
    Cada dia sai com as manchetes em ordem cronológica inversa.
    """
    recentes = set(datas[-pregoes:])
    agrupado: dict[str, list[dict]] = {}
    for item in acervo:
        if item.get("d") in recentes:
            agrupado.setdefault(item["d"], []).append(
                {
                    "h": item["hora"],
                    "t": item["titulo"],
                    "v": item["veiculo"],
                    "u": item["link"],
                }
            )
    for lista in agrupado.values():
        lista.sort(key=lambda x: x["h"], reverse=True)
    return agrupado
