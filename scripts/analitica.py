"""Cálculos financeiros do dashboard — funções puras, sem rede e sem estado.

Tudo aqui recebe séries já coletadas e devolve números. A separação é
proposital: a coleta lida com uma fonte que mente de formas criativas
(``yahoo_chart``), e o cálculo precisa ser testável sem nada disso por perto.

Três decisões metodológicas valem ser lidas antes de usar os números:

**Retornos são logarítmicos** em tudo que envolve correlação, beta e
volatilidade, e aritméticos em tudo que o leitor vai comparar com um extrato
(retorno do período, retorno mensal, yield). Log é aditivo no tempo, o que faz
a volatilidade escalar por ``√252`` sem viés; aritmético é o que o dinheiro faz.

**Nada é interpolado.** Quando duas séries têm calendários diferentes — feriado
só no Brasil, só nos EUA, pregão sem negócio no índice — os pares usados para
correlação e beta são apenas as datas em que **as duas** têm observação real.
Repetir o último valor conhecido produziria retorno zero num dia em que o ativo
de fato andou, e retorno zero artificial derruba correlação e beta na direção
do que o analista não pediu. O preenchimento por repetição existe, mas só para
desenhar linha em gráfico (``alinha_referencia``, em ``update_dashboard``),
nunca para alimentar estatística.

**Janelas curtas não são publicadas.** Correlação de 60 pregões precisa de 60
pregões; enquanto não há, o valor é ``None`` e o gráfico simplesmente não
desenha ali. Um beta calculado com 8 observações é ruído com casas decimais.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

# Pregões por ano usados na anualização. 252 é a convenção de mercado para
# renda variável; a B3 fica perto disso (2024 teve 246, 2023 teve 247).
PREGOES_POR_ANO = 252

# Janela padrão das estatísticas móveis: 60 pregões ≈ 3 meses. Curta o
# suficiente para captar mudança de regime, longa o suficiente para o beta não
# virar ruído.
JANELA_MOVEL = 60

# Janelas da estrutura a termo de volatilidade realizada, em pregões.
JANELAS_VOL = (21, 63, 252)

# Abaixo desta soma de quadrados a série é constante para todos os efeitos, e
# correlação e beta ficam indefinidos (0/0). Retorno diário de verdade tem
# variância na casa de 1e-4 por observação; 1e-18 no total é degenerado, não
# mercado parado.
VARIANCIA_MINIMA = 1e-18


def _log_retornos(valores: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(valores, valores[1:], strict=False)]


def pares_de_retornos(
    a: dict[str, float], b: dict[str, float]
) -> tuple[list[str], list[float], list[float]]:
    """Retornos diários de duas séries, só nas datas em que ambas negociaram.

    Devolve ``(datas, retornos_a, retornos_b)``, onde cada retorno vai da data
    anterior **da interseção** até a data corrente. Feriado de um lado só não
    vira retorno zero: vira um intervalo um pouco mais longo, que é o que de
    fato aconteceu com o preço.

    As datas devolvidas são as do segundo ponto de cada par — a data em que o
    retorno se realizou.
    """
    comuns = sorted(set(a) & set(b))
    datas, ra, rb = [], [], []
    for anterior, atual in zip(comuns, comuns[1:], strict=False):
        if a[anterior] <= 0 or b[anterior] <= 0 or a[atual] <= 0 or b[atual] <= 0:
            continue
        datas.append(atual)
        ra.append(math.log(a[atual] / a[anterior]))
        rb.append(math.log(b[atual] / b[anterior]))
    return datas, ra, rb


def _correlacao(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 2:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True))
    sxx = sum((xi - mx) ** 2 for xi in x)
    syy = sum((yi - my) ** 2 for yi in y)
    if sxx < VARIANCIA_MINIMA or syy < VARIANCIA_MINIMA:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def _beta(dependente: list[float], explicativa: list[float]) -> float | None:
    """Inclinação da regressão de ``dependente`` sobre ``explicativa`` (OLS)."""
    n = len(explicativa)
    if n < 2:
        return None
    mx = sum(explicativa) / n
    my = sum(dependente) / n
    sxx = sum((xi - mx) ** 2 for xi in explicativa)
    if sxx < VARIANCIA_MINIMA:
        return None
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(explicativa, dependente, strict=True))
    return sxy / sxx


def estatisticas_moveis(
    ativo: dict[str, float], fator: dict[str, float], janela: int = JANELA_MOVEL
) -> dict:
    """Correlação e beta móveis do ativo contra um fator, em janela deslizante.

    ``beta`` é a inclinação de uma regressão dos retornos do ativo sobre os do
    fator: quanto o ativo anda, em média, para cada 1% que o fator anda. Não é
    a mesma coisa que correlação — correlação diz o quanto os dois andam
    juntos, beta diz o tamanho do passo. Os dois juntos contam a história; um
    beta alto com correlação baixa é um beta em que não se deve confiar.

    Devolve ``{"d": [...], "corr": [...], "beta": [...]}`` alinhados. Antes de
    completar a janela os valores são ``None``.
    """
    datas, ra, rf = pares_de_retornos(ativo, fator)
    corr: list[float | None] = []
    beta: list[float | None] = []
    for i in range(len(datas)):
        if i + 1 < janela:
            corr.append(None)
            beta.append(None)
            continue
        recorte_a = ra[i + 1 - janela : i + 1]
        recorte_f = rf[i + 1 - janela : i + 1]
        c = _correlacao(recorte_a, recorte_f)
        b = _beta(recorte_a, recorte_f)
        corr.append(None if c is None else round(c, 3))
        beta.append(None if b is None else round(b, 3))
    return {"d": datas, "corr": corr, "beta": beta}


def serie_em_reais(em_dolar: dict[str, float], cambio: dict[str, float]) -> dict[str, float]:
    """Converte uma série em dólar para reais, data a data.

    Só entram as datas em que existem **as duas** cotações. Converter o Brent de
    ontem pelo câmbio de hoje produziria um movimento que não aconteceu.
    """
    return {
        d: em_dolar[d] * cambio[d]
        for d in sorted(set(em_dolar) & set(cambio))
        if em_dolar[d] > 0 and cambio[d] > 0
    }


def indice_base_100(serie: dict[str, float], datas: list[str]) -> list[float | None]:
    """Reindexa uma série para 100 no primeiro ponto disponível da janela."""
    base = None
    saida: list[float | None] = []
    for d in datas:
        valor = serie.get(d)
        if valor is None or valor <= 0:
            saida.append(None)
            continue
        if base is None:
            base = valor
        saida.append(round(valor / base * 100, 2))
    return saida


def indice_retorno_total(linhas: list[dict], proventos: dict[str, float]) -> dict:
    """Índice de retorno total contra índice de preço, ambos base 100.

    O retorno total reinveste cada provento no fechamento da própria data-ex.
    É a convenção dos índices de retorno total (IBrX, S&P TR) e a única leitura
    honesta para uma ação cujo caso de investimento é a distribuição: em PETR4,
    olhar só o preço subestima o retorno do acionista em uma fração grande.

    A diferença entre as duas curvas, ao fim, é exatamente a contribuição
    acumulada dos proventos reinvestidos.
    """
    datas: list[str] = []
    preco: list[float] = []
    total: list[float] = []
    if not linhas:
        return {"d": [], "preco": [], "total": []}

    base = linhas[0]["c"]
    acumulado = 100.0
    for i, linha in enumerate(linhas):
        datas.append(linha["d"])
        preco.append(round(linha["c"] / base * 100, 2))
        if i == 0:
            total.append(100.0)
            continue
        anterior = linhas[i - 1]["c"]
        provento = proventos.get(linha["d"], 0.0)
        acumulado *= (linha["c"] + provento) / anterior
        total.append(round(acumulado, 2))
    return {"d": datas, "preco": preco, "total": total}


def yield_ttm(linhas: list[dict], proventos: dict[str, float]) -> dict:
    """Dividend yield dos últimos 12 meses, pregão a pregão.

    Numerador: proventos com data-ex nos 365 dias corridos anteriores.
    Denominador: o fechamento **daquele** pregão. É o yield que um comprador
    naquele dia teria olhado — não o yield de hoje projetado para trás.

    O primeiro ano da série fica de fora: não há 12 meses de proventos para
    somar, e publicar um yield de janela incompleta faria a série começar num
    número artificialmente baixo.
    """
    if not linhas:
        return {"d": [], "y": []}
    eventos = sorted((d, v) for d, v in proventos.items() if v > 0)
    inicio = date.fromisoformat(linhas[0]["d"])
    datas: list[str] = []
    valores: list[float] = []
    for linha in linhas:
        hoje = date.fromisoformat(linha["d"])
        if (hoje - inicio).days < 365:
            continue
        corte = (hoje - timedelta(days=365)).isoformat()
        soma = sum(v for d, v in eventos if corte < d <= linha["d"])
        datas.append(linha["d"])
        valores.append(round(soma / linha["c"] * 100, 2) if linha["c"] > 0 else 0.0)
    return {"d": datas, "y": valores}


def volatilidade_realizada(linhas: list[dict], janelas: tuple[int, ...] = JANELAS_VOL) -> dict:
    """Volatilidade realizada anualizada, em várias janelas.

    Desvio-padrão dos retornos logarítmicos na janela, multiplicado por
    ``√252`` e expresso em % ao ano. Olhar 21, 63 e 252 pregões ao mesmo tempo
    dá a estrutura a termo: a de 21 reagindo enquanto a de 252 ainda não se
    mexeu é o retrato de um choque recente, e o cruzamento das duas costuma
    marcar a virada de regime.
    """
    fechamentos = [linha["c"] for linha in linhas]
    retornos = _log_retornos(fechamentos)
    datas = [linha["d"] for linha in linhas[1:]]
    saida: dict[str, list] = {"d": datas}
    for janela in janelas:
        serie: list[float | None] = []
        for i in range(len(retornos)):
            if i + 1 < janela:
                serie.append(None)
                continue
            recorte = retornos[i + 1 - janela : i + 1]
            media = sum(recorte) / janela
            variancia = sum((r - media) ** 2 for r in recorte) / (janela - 1)
            serie.append(round(math.sqrt(variancia * PREGOES_POR_ANO) * 100, 1))
        saida[f"v{janela}"] = serie
    return saida


def posicao_na_faixa(linhas: list[dict], pregoes: int = 252) -> dict:
    """Onde o último fechamento está dentro da faixa das últimas 52 semanas.

    ``0`` é a mínima da janela, ``100`` a máxima. É o enquadramento que um
    analista faz de cabeça antes de olhar qualquer outra coisa: um papel a 95
    da faixa e um a 12 pedem conversas diferentes, mesmo com o mesmo múltiplo.
    """
    recorte = linhas[-pregoes:]
    if len(recorte) < 2:
        return {}
    maxima = max(r["h"] for r in recorte)
    minima = min(r["l"] for r in recorte)
    fechamento = recorte[-1]["c"]
    faixa = maxima - minima
    return {
        "faixa_max": round(maxima, 2),
        "faixa_min": round(minima, 2),
        "faixa_pct": round((fechamento - minima) / faixa * 100, 1) if faixa > 0 else None,
        "faixa_pregoes": len(recorte),
    }


def razao_entre_series(
    numerador: dict[str, float], denominador: dict[str, float], datas: list[str]
) -> list[float | None]:
    """Razão entre duas séries nas datas pedidas, sem preenchimento.

    Data em que faltar qualquer um dos dois lados vira ``None``: uma razão
    calculada com o preço de ontem de um lado e o de hoje do outro é um número
    que não corresponde a nenhum instante do mercado.
    """
    saida: list[float | None] = []
    for d in datas:
        a, b = numerador.get(d), denominador.get(d)
        saida.append(round(a / b, 4) if a and b and b > 0 else None)
    return saida


def paridade_adr(
    adr_usd: dict[str, float],
    cambio: dict[str, float],
    local: dict[str, float],
    acoes_por_adr: int,
    datas: list[str],
) -> list[float | None]:
    """Prêmio (+) ou desconto (−) do ADR sobre o preço local, em %.

    ``ADR × câmbio ÷ ações_por_ADR`` é o preço local implícito no que o
    estrangeiro pagou; a diferença para o preço em bolsa é o prêmio.

    **Cuidado ao ler.** O ADR negocia em Nova York por cerca de duas horas
    depois do fechamento da B3, e o câmbio de referência é de outro horário
    ainda. Parte do que aparece aqui como prêmio é simplesmente notícia que
    chegou depois que a B3 fechou — não arbitragem aberta. O sinal é o desvio
    persistente, ao longo de dias, não o número de um dia isolado.
    """
    saida: list[float | None] = []
    for d in datas:
        adr, fx, loc = adr_usd.get(d), cambio.get(d), local.get(d)
        if not adr or not fx or not loc or loc <= 0:
            saida.append(None)
            continue
        implicito = adr * fx / acoes_por_adr
        saida.append(round((implicito / loc - 1) * 100, 2))
    return saida


def confere_razao_do_adr(
    adr_usd: dict[str, float],
    cambio: dict[str, float],
    local: dict[str, float],
    esperado: int,
    tolerancia: float = 0.05,
) -> bool:
    """A razão declarada do ADR bate com o que os preços mostram?

    Um programa de ADR pode ser reagrupado, e nesse dia todo o painel de
    paridade passaria a mentir em silêncio. Em vez de confiar na constante, a
    rotina confere a mediana de ``ADR × câmbio ÷ local`` contra o valor
    declarado e não publica o painel se os dois divergirem.
    """
    razoes = sorted(
        adr_usd[d] * cambio[d] / local[d]
        for d in set(adr_usd) & set(cambio) & set(local)
        if local[d] > 0
    )
    if len(razoes) < 30:
        return False
    mediana = razoes[len(razoes) // 2]
    return abs(mediana / esperado - 1) <= tolerancia
