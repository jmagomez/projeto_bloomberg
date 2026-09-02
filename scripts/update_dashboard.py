"""Gera o data.js do dashboard PETR4 a partir da série diária do Yahoo Finance.

Blocos publicados:

* ``stats`` — resumo do período inteiro (desde 2010), do último pregão e do
  drawdown; carrega também ``pending_session`` e ``close_source``, que contam ao
  dashboard o que a fonte deixou de entregar e de onde veio o fechamento;
* ``D``    — série diária das últimas sessões (candles e volume diários);
* ``W``    — série semanal OHLCV desde 2010 (gráficos de longo prazo);
* ``M``    — retornos mensais desde 2010 (heatmap ano × mês);
* ``DIV``  — proventos (dividendos + JCP) por ano;
* ``REF``  — fechamentos do índice de referência alinhados às datas da PETR4,
  para a comparação base 100. Some do payload se a coleta do índice falhar.

A coleta e a validação de atualidade ficam em ``yahoo_chart.py``. Este módulo
não estima nem completa preço nenhum. Se a fonte deve um pregão mas a coleta
ainda assim avança em relação ao publicado, o avanço é publicado com a pendência
sinalizada; se não avança nada, o job falha e o data.js fica como está.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analitica as an  # noqa: E402
import noticias as nt  # noqa: E402
from yahoo_chart import (  # noqa: E402
    DadosDesatualizadosError,
    ErroTransitorio,
    busca_fechamentos,
    busca_serie_diaria,
)

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data.js"
ARQUIVO_NOTICIAS = BASE / "noticias.json"
PREFIXO = "window.PETR4 = "

SYMBOL = "PETR4.SA"
# Índice de referência para a comparação relativa do dashboard. É opcional: se
# a coleta dele falhar, o painel some e a rotina segue normalmente.
SYMBOL_REF = "^BVSP"
NOME_REF = "Ibovespa"
PERIOD1 = 1262304000  # 2010-01-01

# Séries auxiliares. Todas opcionais pelo mesmo motivo do índice: nenhuma delas
# pode derrubar a publicação da cotação da PETR4, que é o dado principal.
SYMBOL_BRENT = "BZ=F"  # Brent futuro, em dólar por barril
SYMBOL_CAMBIO = "BRL=X"  # USD/BRL
SYMBOL_ON = "PETR3.SA"  # ordinária, para o spread ON/PN
SYMBOL_ADR = "PBR-A"  # ADR da preferencial

# Cada ADR da Petrobras representa 2 ações. A rotina não confia nesta constante:
# confere_razao_do_adr mede a razão implícita nos próprios preços e o painel só
# sai se as duas baterem. Medianas anuais de 2010 a 2026 ficaram entre 1,988 e
# 2,025 — mas um reagrupamento futuro passaria despercebido sem a conferência.
ACOES_POR_ADR = 2

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


def drawdown(linhas: list[dict]) -> dict:
    """Estatísticas de queda desde o topo, sobre os fechamentos diários.

    Para uma ação com a volatilidade da PETR4 o drawdown diz mais sobre risco
    do que o desvio-padrão: mostra quanto se perdeu do pico até o fundo e
    quanto tempo levou para voltar.
    """
    pico = linhas[0]["c"]
    pico_data = linhas[0]["d"]
    pior = 0.0
    pior_de = pior_ate = linhas[0]["d"]
    pior_pico = pico
    for linha in linhas:
        if linha["c"] > pico:
            pico, pico_data = linha["c"], linha["d"]
        queda = linha["c"] / pico - 1
        if queda < pior:
            pior, pior_de, pior_ate, pior_pico = queda, pico_data, linha["d"], pico

    # Data em que o preço voltou ao pico anterior à pior queda (se voltou).
    recuperado = None
    for linha in linhas:
        if linha["d"] > pior_ate and linha["c"] >= pior_pico:
            recuperado = linha["d"]
            break

    topo = max(linhas, key=lambda r: r["c"])
    atual = linhas[-1]["c"] / topo["c"] - 1
    return {
        "max_drawdown_pct": round(pior * 100, 2),
        "max_drawdown_de": pior_de,
        "max_drawdown_ate": pior_ate,
        "max_drawdown_recuperado": recuperado,
        "drawdown_atual_pct": round(atual * 100, 2),
        "ath_close": round(topo["c"], 2),
        "ath_date": topo["d"],
    }


def mensal(linhas: list[dict]) -> dict:
    """Retornos mensais, do fechamento de um mês para o do seguinte.

    O primeiro mês da série fica de fora de propósito: não existe fechamento do
    mês anterior para servir de base, e inventar uma base parcial produziria um
    número que não é comparável com os demais.
    """
    fechamento_do_mes: dict[str, float] = {}
    for linha in linhas:
        fechamento_do_mes[linha["d"][:7]] = linha["c"]
    meses = sorted(fechamento_do_mes)
    return {
        "d": meses[1:],
        "r": [
            round((fechamento_do_mes[m] / fechamento_do_mes[a] - 1) * 100, 2)
            # strict=False de propósito: os dois lados têm tamanhos diferentes,
            # já que cada retorno compara um mês com o anterior.
            for a, m in zip(meses, meses[1:], strict=False)
        ],
    }


def alinha_referencia(fechamentos: dict[str, float], datas: list[str]) -> list[float | None]:
    """Alinha a série do índice às datas da PETR4.

    Feriado só de um dos dois, ou pregão sem negócio no índice, viram repetição
    do último valor conhecido — nunca interpolação. Antes do primeiro dado
    disponível o valor fica nulo e o gráfico simplesmente não desenha ali.
    """
    if not fechamentos:
        return []
    ordenadas = sorted(fechamentos)
    saida: list[float | None] = []
    i = 0
    ultimo: float | None = None
    for data in datas:
        while i < len(ordenadas) and ordenadas[i] <= data:
            ultimo = fechamentos[ordenadas[i]]
            i += 1
        saida.append(ultimo)
    return saida


def amostra_semanal(datas: list[str], *series: list) -> tuple[list[str], list[list]]:
    """Reduz séries longas a uma observação por semana (a última de cada uma).

    As séries analíticas — retorno total, yield, volatilidade, correlação móvel
    — cobrem 4.100 pregões desde 2010. Publicá-las em resolução diária dobraria
    o ``data.js`` sem mudar nada do que se vê: num gráfico de 1.100 px, 4.100
    pontos são 4 por pixel. Uma observação semanal é o mesmo desenho com um
    sétimo do peso.

    Amostrar (pegar a última observação da semana) não é o mesmo que suavizar:
    nenhum valor é recalculado ou misturado com o vizinho. Cada ponto publicado
    é um número que existiu de fato naquele pregão.
    """
    if not datas:
        return [], [[] for _ in series]
    indices = []
    chave_anterior = None
    for i, d in enumerate(datas):
        chave = (date.fromisoformat(d).toordinal() - 1) // 7
        if chave_anterior is not None and chave != chave_anterior:
            indices.append(i - 1)
        chave_anterior = chave
    indices.append(len(datas) - 1)
    return [datas[i] for i in indices], [[s[i] for i in indices] for s in series]


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
    # A mínima da série só cai quando a ação de fato negocia mais baixo do que
    # em qualquer pregão desde 2010. Um tombo grande aí é sinal de barra suja,
    # não de mercado: foi assim que um zero virou "mínima histórica R$ 0,00".
    minima_antes = antes.get("min_low")
    minima_agora = novas_stats.get("min_low")
    if minima_antes and minima_agora is not None and minima_agora < minima_antes * 0.5:
        raise DadosDesatualizadosError(
            f"mínima da série despencou de R$ {minima_antes:.2f} para "
            f"R$ {minima_agora:.2f} em uma única coleta — quase certamente barra suja"
        )


# Campos de ``stats`` que são preço ou volume e, portanto, nunca podem ser
# negativos; os de preço também não podem ser zero.
PRECOS_EM_STATS = (
    "last_close",
    "prev_close",
    "first_close",
    "day_open",
    "day_high",
    "day_low",
    "max_high",
    "min_low",
    "ath_close",
)


def confere_precos_possiveis(payload: dict) -> None:
    """Última trava antes de escrever: nenhum preço publicado pode ser ≤ 0.

    A coleta já peneira barras impossíveis. Isto aqui é a rede embaixo da rede,
    e existe porque em 2026-08-31 um zero atravessou a coleta, entrou no
    ``data.js`` e virou a "mínima histórica" exibida no dashboard. Uma trava que
    olha o payload **pronto** não depende de nenhum caminho específico da
    coleta — vale também para os que forem acrescentados depois.
    """
    stats = payload["stats"]
    ruins = [campo for campo in PRECOS_EM_STATS if (stats.get(campo) or 0) <= 0]
    if ruins:
        raise DadosDesatualizadosError(
            "preço impossível em stats: " + ", ".join(f"{c}={stats.get(c)!r}" for c in ruins)
        )
    if stats.get("day_volume_M", 0) < 0:
        raise DadosDesatualizadosError(f"volume negativo: {stats['day_volume_M']}")

    for bloco in ("D", "W"):
        serie = payload.get(bloco) or {}
        for campo in ("o", "h", "l", "c"):
            for data, valor in zip(serie.get("d", []), serie.get(campo, []), strict=True):
                if valor is None or valor <= 0:
                    raise DadosDesatualizadosError(
                        f"preço impossível em {bloco}.{campo} no pregão de {data}: {valor!r}"
                    )


def blocos_analiticos(
    linhas: list[dict], proventos: dict[str, float], aux: dict[str, dict[str, float]]
) -> tuple[dict, dict]:
    """Monta os blocos de análise setorial e de risco, e o que vai para os cartões.

    Devolve ``(blocos, resumo)``. Cada bloco é opcional: se a série auxiliar de
    que ele depende não veio, ele simplesmente não entra no payload e o painel
    correspondente some do dashboard. Nenhuma ausência derruba a rotina.

    Todas as séries longas saem em resolução semanal (ver ``amostra_semanal``).
    """
    blocos: dict = {}
    resumo: dict = {}
    fechamentos = {linha["d"]: linha["c"] for linha in linhas}
    datas_diarias = [linha["d"] for linha in linhas]

    # --- retorno total x preço, e yield TTM ao longo do tempo -------------
    tr = an.indice_retorno_total(linhas, proventos)
    y = an.yield_ttm(linhas, proventos)
    d_tr, (preco, total) = amostra_semanal(tr["d"], tr["preco"], tr["total"])
    d_y, (yy,) = amostra_semanal(y["d"], y["y"])
    blocos["TR"] = {"d": d_tr, "preco": preco, "total": total, "yd": d_y, "y": yy}
    if total and preco and preco[-1]:
        # Quanto do retorno acumulado veio de distribuição e não de preço.
        resumo["parcela_proventos_pct"] = (
            round((total[-1] - preco[-1]) / (total[-1] - 100) * 100, 1) if total[-1] > 100 else None
        )
        resumo["tr_indice"] = total[-1]
        resumo["preco_indice"] = preco[-1]
    if yy:
        resumo["div_yield_ttm_serie_ultimo"] = yy[-1]
        ordenado = sorted(v for v in yy if v is not None)
        resumo["div_yield_mediana_pct"] = ordenado[len(ordenado) // 2] if ordenado else None

    # --- Brent em reais: o driver de receita ------------------------------
    brent, cambio = aux.get("brent") or {}, aux.get("cambio") or {}
    brent_brl = an.serie_em_reais(brent, cambio) if brent and cambio else {}
    if brent_brl:
        idx_datas, (p_idx, b_idx) = amostra_semanal(
            datas_diarias,
            an.indice_base_100(fechamentos, datas_diarias),
            an.indice_base_100(brent_brl, datas_diarias),
        )
        movel = an.estatisticas_moveis(fechamentos, brent_brl)
        d_mov, (corr, beta) = amostra_semanal(movel["d"], movel["corr"], movel["beta"])
        blocos["BRENT"] = {
            "d": idx_datas,
            "p": p_idx,
            "b": b_idx,
            "md": d_mov,
            "corr": corr,
            "beta": beta,
            "symbol": SYMBOL_BRENT,
            "cambio": SYMBOL_CAMBIO,
            "janela": an.JANELA_MOVEL,
        }
        ultimo_dia = max(set(brent) & set(cambio), default=None)
        if ultimo_dia:
            resumo["brent_usd"] = round(brent[ultimo_dia], 2)
            resumo["brent_brl"] = round(brent_brl[ultimo_dia], 2)
            resumo["usdbrl"] = round(cambio[ultimo_dia], 4)
            resumo["brent_data"] = ultimo_dia
        validos_corr = [c for c in movel["corr"] if c is not None]
        validos_beta = [b for b in movel["beta"] if b is not None]
        if validos_corr:
            resumo["corr_brent"] = validos_corr[-1]
        if validos_beta:
            resumo["beta_brent"] = validos_beta[-1]

    # --- ON/PN e paridade do ADR ------------------------------------------
    on, adr = aux.get("on") or {}, aux.get("adr") or {}
    razao_ok = bool(adr and cambio) and an.confere_razao_do_adr(
        adr, cambio, fechamentos, ACOES_POR_ADR
    )
    if on or razao_ok:
        d_par, (on_pn, premio) = amostra_semanal(
            datas_diarias,
            an.razao_entre_series(on, fechamentos, datas_diarias)
            if on
            else [None] * len(datas_diarias),
            an.paridade_adr(adr, cambio, fechamentos, ACOES_POR_ADR, datas_diarias)
            if razao_ok
            else [None] * len(datas_diarias),
        )
        blocos["PARES"] = {
            "d": d_par,
            "onpn": on_pn if on else None,
            "adr": premio if razao_ok else None,
            "on_symbol": SYMBOL_ON,
            "adr_symbol": SYMBOL_ADR,
            "acoes_por_adr": ACOES_POR_ADR,
        }
        atuais_onpn = [v for v in on_pn if v is not None]
        if atuais_onpn:
            resumo["on_pn"] = atuais_onpn[-1]
            ordenado = sorted(atuais_onpn)
            resumo["on_pn_mediana"] = ordenado[len(ordenado) // 2]
        atuais_adr = [v for v in premio if v is not None]
        if atuais_adr:
            resumo["adr_premio_pct"] = atuais_adr[-1]

    # --- risco: volatilidade realizada, beta ao índice, faixa de 52 sem. ---
    vol = an.volatilidade_realizada(linhas)
    campos = [f"v{j}" for j in an.JANELAS_VOL]
    d_vol, series_vol = amostra_semanal(vol["d"], *(vol[c] for c in campos))
    risco: dict = {"d": d_vol, **dict(zip(campos, series_vol, strict=True))}
    for campo in campos:
        atuais = [v for v in vol[campo] if v is not None]
        if atuais:
            resumo[f"vol_{campo[1:]}d_pct"] = atuais[-1]

    referencia = aux.get("ref") or {}
    if referencia:
        movel_ibov = an.estatisticas_moveis(fechamentos, referencia)
        d_mi, (corr_i, beta_i) = amostra_semanal(
            movel_ibov["d"], movel_ibov["corr"], movel_ibov["beta"]
        )
        risco.update({"md": d_mi, "corr_ref": corr_i, "beta_ref": beta_i, "ref_nome": NOME_REF})
        validos = [b for b in movel_ibov["beta"] if b is not None]
        if validos:
            resumo["beta_ibov"] = validos[-1]
    blocos["RISCO"] = risco
    resumo.update(an.posicao_na_faixa(linhas))
    return blocos, resumo


def monta_payload(
    linhas: list[dict],
    proventos: dict[str, float],
    referencia: dict[str, float] | None = None,
    pendente: str | None = None,
    auxiliares: dict[str, dict[str, float]] | None = None,
    manchetes: dict | None = None,
) -> dict:
    for linha in linhas:
        linha["e"] = proventos.get(linha["d"], 0.0)

    stats = estatisticas(linhas, proventos)
    stats.update(drawdown(linhas))
    stats["pending_session"] = pendente
    stats["close_source"] = "meta" if linhas[-1].get("c_de_meta") else "chart"

    _, _, por_ano = calendario_de_proventos(proventos, stats["first_date"], stats["last_date"])
    anos = sorted(por_ano)

    D = diaria(linhas)
    W = semanal(linhas)
    payload = {
        "stats": stats,
        "D": D,
        "W": W,
        "M": mensal(linhas),
        "DIV": {"y": anos, "v": [por_ano[a] for a in anos]},
    }

    if referencia:
        payload["REF"] = {
            "nome": NOME_REF,
            "symbol": SYMBOL_REF,
            "D": alinha_referencia(referencia, D["d"]),
            "W": alinha_referencia(referencia, W["d"]),
        }

    aux = dict(auxiliares or {})
    aux.setdefault("ref", referencia or {})
    blocos, resumo = blocos_analiticos(linhas, proventos, aux)
    payload.update(blocos)
    stats.update(resumo)
    if manchetes:
        payload["NEWS"] = manchetes
    return payload


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

    anterior = le_payload_atual(OUT)
    publicado = (anterior or {}).get("stats", {}).get("last_date", "")
    pendente = estado.get("pendente")

    # Pregão pendente na fonte: só vale desistir se a coleta também não avançar
    # em relação ao que já está publicado. Avançando, é melhor publicar o avanço
    # marcado como incompleto do que deixar o dashboard parado esperando a fonte.
    if pendente and linhas[-1]["d"] <= publicado:
        print(
            f"[update] ERRO: a fonte informa o pregão de {pendente}, não o entregou, "
            f"e a coleta não avança além do que já está publicado ({publicado}). "
            "Nada foi escrito.",
            file=sys.stderr,
        )
        return 2

    referencia = busca_fechamentos(SYMBOL_REF, PERIOD1)
    if not referencia:
        print(f"[update] aviso: sem dados de {SYMBOL_REF}; painel de comparação sai do data.js")

    # Séries auxiliares dos painéis setoriais. Nenhuma é obrigatória: o painel
    # que depender de uma que falhou some do data.js, e a cotação da PETR4 —
    # que é o dado principal — publica do mesmo jeito.
    auxiliares: dict[str, dict[str, float]] = {"ref": referencia}
    for chave, simbolo in (
        ("brent", SYMBOL_BRENT),
        ("cambio", SYMBOL_CAMBIO),
        ("on", SYMBOL_ON),
        ("adr", SYMBOL_ADR),
    ):
        auxiliares[chave] = busca_fechamentos(simbolo, PERIOD1)
        if not auxiliares[chave]:
            print(
                f"[update] aviso: sem dados de {simbolo}; o painel que depende dele sai do data.js"
            )

    # Manchetes: acumuladas em arquivo porque o endpoint de busca só devolve as
    # recentes. Falha de rede aqui não impede nada — o acervo já gravado segue
    # sendo publicado.
    acervo = nt.le_arquivo(ARQUIVO_NOTICIAS)
    antes = len(acervo)
    try:
        acervo = nt.mescla(acervo, nt.busca_manchetes())
    except Exception as exc:  # noqa: BLE001 — notícia nunca derruba a cotação
        print(f"[update] aviso: coleta de manchetes falhou ({exc}); usando o acervo gravado")
    if acervo:
        nt.grava_arquivo(ARQUIVO_NOTICIAS, acervo)
    print(f"[update] manchetes: {antes} no acervo, {len(acervo)} depois da coleta")

    manchetes = nt.por_pregao(acervo, [linha["d"] for linha in linhas])
    payload = monta_payload(linhas, proventos, referencia, pendente, auxiliares, manchetes)

    try:
        confere_precos_possiveis(payload)
        confere_sem_regressao(payload["stats"], anterior)
    except DadosDesatualizadosError as exc:
        print(f"[update] ERRO: {exc}", file=sys.stderr)
        return 2

    OUT.write_text(PREFIXO + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

    s = payload["stats"]
    if pendente:
        print(
            f"::warning::Publicado até {s['last_date']}, mas a fonte informa que o pregão "
            f"de {pendente} já fechou e não o entregou. O dashboard sinaliza a pendência."
        )
    if linhas[-1].get("fora_faixa"):
        print(
            f"::warning::A barra de {s['last_date']} veio da fonte com abertura ou "
            f"fechamento fora da própria faixa do dia (A {s['day_open']} · F "
            f"{s['last_close']} · faixa {s['day_low']}–{s['day_high']}). Publicada "
            "como veio — nenhum campo foi corrigido."
        )
    if s["close_source"] == "meta":
        print(
            f"::notice::O fechamento de {s['last_date']} veio de 'meta.regularMarketPrice' "
            "porque a barra do Yahoo estava com 'close' nulo."
        )
    print(
        f"[update] {s['days']} pregões até {s['last_date']} "
        f"(fonte confirma último pregão em {estado.get('ultimo_pregao') or 'n/d'}) | "
        f"fechamento R$ {s['last_close']:.2f} ({s['day_change_pct']:+.2f}% no dia) | "
        f"drawdown atual {s['drawdown_atual_pct']:+.2f}% | "
        f"proventos no período R$ {s['total_dividends']:.2f}/ação | "
        f"retorno total {s['ret_annual_pct']:+.2f}% a.a. | data.js atualizado"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
