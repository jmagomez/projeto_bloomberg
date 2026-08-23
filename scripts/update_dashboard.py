"""Gera o data.js do dashboard PETR4 a partir da série diária do Yahoo Finance.

Publica quatro blocos:

* ``stats`` — resumo do período inteiro (desde 2010) **e** do último pregão;
* ``D``    — série diária das últimas sessões (candles diários do dashboard);
* ``W``    — série semanal OHLCV desde 2010 (gráficos de longo prazo);
* ``DIV``  — proventos (dividendos + JCP) por ano.

A coleta e a validação de atualidade ficam em ``yahoo_chart.py``. Este módulo
não estima nem completa preço nenhum: se a fonte não entregar o último pregão,
a exceção sobe e nada é escrito.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yahoo_chart import (  # noqa: E402
    DadosDesatualizadosError,
    ErroTransitorio,
    busca_serie_diaria,
)

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data.js"
PREFIXO = "window.PETR4 = "

SYMBOL = "PETR4.SA"
PERIOD1 = 1262304000  # 2010-01-01

# Quantos pregões diários acompanham o payload. ~2 anos de sessões: suficiente
# para o candlestick diário e as médias móveis curtas sem inchar o data.js.
JANELA_DIARIA = 520


def calendario_de_proventos(
    proventos: dict[str, float], primeira_data: str, ultima_data: str
) -> tuple[float, float, dict[str, float]]:
    """(total no período, total em 12 meses, total por ano) dentro da janela."""
    corte_12m = (datetime.strptime(ultima_data, "%Y-%m-%d") - timedelta(days=365)).strftime(
        "%Y-%m-%d"
    )
    total = ttm = 0.0
    por_ano: dict[str, float] = {}
    for data, valor in proventos.items():
        if primeira_data <= data <= ultima_data:
            total += valor
            por_ano[data[:4]] = round(por_ano.get(data[:4], 0.0) + valor, 4)
        if corte_12m <= data <= ultima_data:
            ttm += valor
    return round(total, 4), round(ttm, 4), por_ano


def estatisticas(linhas: list[dict], proventos: dict[str, float]) -> dict:
    if len(linhas) < 2:
        raise ValueError("são necessários ao menos dois pregões para calcular estatísticas")

    maxima = max(linhas, key=lambda r: r["h"])
    minima = min(linhas, key=lambda r: r["l"])
    variacoes = [(linhas[i]["c"] / linhas[i - 1]["c"] - 1) * 100 for i in range(1, len(linhas))]
    i_melhor = max(range(len(variacoes)), key=lambda i: variacoes[i])
    i_pior = min(range(len(variacoes)), key=lambda i: variacoes[i])
    primeiro, ultimo, penultimo = linhas[0], linhas[-1], linhas[-2]

    total_div, ttm_div, _ = calendario_de_proventos(proventos, primeiro["d"], ultimo["d"])

    dias_periodo = (
        datetime.strptime(ultimo["d"], "%Y-%m-%d") - datetime.strptime(primeiro["d"], "%Y-%m-%d")
    ).days
    anos = max(dias_periodo / 365.25, 1 / 365.25)

    ret_preco = (ultimo["c"] / primeiro["c"] - 1) * 100
    # Retorno total = variação de preço + proventos por ação, sem reinvestimento.
    ret_total = ((ultimo["c"] + total_div) / primeiro["c"] - 1) * 100
    ret_anual = (((1 + ret_total / 100) ** (1 / anos)) - 1) * 100
    dy_ttm = (ttm_div / ultimo["c"]) * 100 if ultimo["c"] else 0.0

    return {
        "symbol": SYMBOL,
        "source": "Yahoo Finance",
        "days": len(linhas),
        "first_date": primeiro["d"],
        "last_date": ultimo["d"],
        "first_close": round(primeiro["c"], 2),
        "last_close": round(ultimo["c"], 2),
        # --- último pregão em detalhe (o que o dashboard passa a destacar) ---
        "prev_date": penultimo["d"],
        "prev_close": round(penultimo["c"], 2),
        "day_change_pct": round((ultimo["c"] / penultimo["c"] - 1) * 100, 2),
        "day_open": round(ultimo["o"], 2),
        "day_high": round(ultimo["h"], 2),
        "day_low": round(ultimo["l"], 2),
        "day_volume_M": round(ultimo["v"] / 1e6, 1),
        # --- período completo ---
        "ret_pct": round(ret_preco, 2),
        "total_dividends": round(total_div, 2),
        "div_yield_ttm_pct": round(dy_ttm, 2),
        "ret_total_pct": round(ret_total, 2),
        "ret_annual_pct": round(ret_anual, 2),
        "years_period": round(anos, 2),
        "max_high": round(maxima["h"], 2),
        "max_high_date": maxima["d"],
        "min_low": round(minima["l"], 2),
        "min_low_date": minima["d"],
        "vol_pct": round(statistics.stdev(variacoes), 2),
        "vol_annual_pct": round(statistics.stdev(variacoes) * (252**0.5), 1),
        "avg_vol_M": round(sum(r["v"] for r in linhas) / len(linhas) / 1e6, 1),
        "best_day": linhas[i_melhor + 1]["d"],
        "best_pct": round(variacoes[i_melhor], 2),
        "worst_day": linhas[i_pior + 1]["d"],
        "worst_pct": round(variacoes[i_pior], 2),
        "updated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "updated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
    }


def semanal(linhas: list[dict]) -> dict:
    """Agrega os pregões em semanas (segunda a domingo).

    A chave da semana vem de ``date.toordinal()``. A versão anterior usava
    ``datetime.strptime(...).timestamp()``, que interpreta a data no fuso da
    máquina — em um runner fora do UTC as semanas podiam ser quebradas no dia
    errado. ``toordinal()`` não depende de fuso nenhum.
    """
    semanas: list[dict] = []
    atual: dict | None = None
    chave_atual = None
    for linha in linhas:
        # ordinal 1 = 0001-01-01, uma segunda-feira; //7 agrupa de segunda a domingo.
        chave = (date.fromisoformat(linha["d"]).toordinal() - 1) // 7
        if atual is None or chave != chave_atual:
            if atual:
                semanas.append(atual)
            atual, chave_atual = dict(linha), chave
        else:
            atual["d"] = linha["d"]
            atual["h"] = max(atual["h"], linha["h"])
            atual["l"] = min(atual["l"], linha["l"])
            atual["c"] = linha["c"]
            atual["v"] += linha["v"]
            atual["e"] = atual.get("e", 0.0) + linha.get("e", 0.0)
    if atual:
        semanas.append(atual)
    return {
        "d": [s["d"] for s in semanas],
        "o": [round(s["o"], 2) for s in semanas],
        "h": [round(s["h"], 2) for s in semanas],
        "l": [round(s["l"], 2) for s in semanas],
        "c": [round(s["c"], 2) for s in semanas],
        "v": [round(s["v"] / 1e6, 1) for s in semanas],
        "e": [round(s.get("e", 0.0), 4) for s in semanas],
    }


def diaria(linhas: list[dict], janela: int = JANELA_DIARIA) -> dict:
    """Últimos ``janela`` pregões, em arrays paralelos."""
    recorte = linhas[-janela:]
    return {
        "d": [r["d"] for r in recorte],
        "o": [round(r["o"], 2) for r in recorte],
        "h": [round(r["h"], 2) for r in recorte],
        "l": [round(r["l"], 2) for r in recorte],
        "c": [round(r["c"], 2) for r in recorte],
        "v": [round(r["v"] / 1e6, 1) for r in recorte],
        "e": [round(r.get("e", 0.0), 4) for r in recorte],
    }


def le_payload_atual(caminho: Path) -> dict | None:
    """Lê o data.js já publicado, se existir e for legível."""
    if not caminho.exists():
        return None
    texto = caminho.read_text(encoding="utf-8").strip()
    if not texto.startswith(PREFIXO):
        return None
    try:
        return json.loads(texto[len(PREFIXO) :].rstrip(";\n"))
    except json.JSONDecodeError:
        return None


def confere_sem_regressao(novas_stats: dict, anterior: dict | None) -> None:
    """Barra publicações que andariam para trás.

    Rede de segurança independente da validação de atualidade: se o payload
    novo terminar antes do que já está publicado, ou tiver menos pregões, algo
    está errado na fonte e é melhor falhar do que sobrescrever dado bom.
    """
    if not anterior or "stats" not in anterior:
        return
    antes = anterior["stats"]
    if novas_stats["last_date"] < antes.get("last_date", ""):
        raise DadosDesatualizadosError(
            f"regressão detectada: o data.js publicado vai até {antes['last_date']} "
            f"e a nova coleta só alcança {novas_stats['last_date']}"
        )
    if novas_stats["days"] < antes.get("days", 0):
        raise DadosDesatualizadosError(
            f"regressão detectada: {novas_stats['days']} pregões coletados contra "
            f"{antes['days']} já publicados"
        )


def monta_payload(linhas: list[dict], proventos: dict[str, float]) -> dict:
    for linha in linhas:
        linha["e"] = proventos.get(linha["d"], 0.0)

    stats = estatisticas(linhas, proventos)
    _, _, por_ano = calendario_de_proventos(proventos, stats["first_date"], stats["last_date"])
    anos = sorted(por_ano)
    return {
        "stats": stats,
        "D": diaria(linhas),
        "W": semanal(linhas),
        "DIV": {"y": anos, "v": [por_ano[a] for a in anos]},
    }


def main() -> int:
    try:
        linhas, proventos, estado, avisos = busca_serie_diaria(SYMBOL, PERIOD1)
    except DadosDesatualizadosError as exc:
        print(f"[update] ERRO: {exc}", file=sys.stderr)
        return 2
    except ErroTransitorio as exc:
        print(f"[update] ERRO: {exc}", file=sys.stderr)
        return 3

    for aviso in avisos:
        print(f"[update] aviso: {aviso}")

    payload = monta_payload(linhas, proventos)

    try:
        confere_sem_regressao(payload["stats"], le_payload_atual(OUT))
    except DadosDesatualizadosError as exc:
        print(f"[update] ERRO: {exc}", file=sys.stderr)
        return 2

    OUT.write_text(PREFIXO + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

    s = payload["stats"]
    print(
        f"[update] {s['days']} pregões até {s['last_date']} "
        f"(fonte confirma último pregão em {estado.get('ultimo_pregao') or 'n/d'}) | "
        f"fechamento R$ {s['last_close']:.2f} ({s['day_change_pct']:+.2f}% no dia) | "
        f"proventos no período R$ {s['total_dividends']:.2f}/ação | "
        f"retorno total {s['ret_annual_pct']:+.2f}% a.a. | data.js atualizado"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
