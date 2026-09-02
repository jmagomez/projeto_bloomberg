"""Testes dos cálculos financeiros — sem rede, com números conferíveis à mão."""

import math

import analitica as an
import pytest


def serie(valores, inicio="2026-01-05"):
    """Constrói {data: valor} em dias úteis consecutivos a partir de ``inicio``."""
    from datetime import date, timedelta

    d = date.fromisoformat(inicio)
    saida = {}
    for v in valores:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        saida[d.isoformat()] = v
        d += timedelta(days=1)
    return saida


def linhas_de(serie_dict, proventos=None):
    proventos = proventos or {}
    return [
        {"d": d, "o": v, "h": v * 1.01, "l": v * 0.99, "c": v, "v": 1_000_000}
        for d, v in sorted(serie_dict.items())
    ]


# ---------------------------------------------------------------------------
# Pares de retornos: o ponto metodológico central
# ---------------------------------------------------------------------------


def test_pares_usam_so_datas_em_que_os_dois_negociaram():
    a = {"2026-01-05": 10.0, "2026-01-06": 11.0, "2026-01-07": 12.0}
    b = {"2026-01-05": 100.0, "2026-01-07": 110.0}  # feriado no dia 06
    datas, ra, rb = an.pares_de_retornos(a, b)
    assert datas == ["2026-01-07"]
    # O retorno de A vai de 05 a 07 — não de 06 a 07 — porque foi esse o
    # intervalo em que B também andou.
    assert ra == [pytest.approx(math.log(12 / 10))]
    assert rb == [pytest.approx(math.log(110 / 100))]


def test_pares_nao_inventam_retorno_zero_no_feriado():
    """A armadilha que este desenho evita: repetir o valor do dia anterior."""
    a = {"2026-01-05": 10.0, "2026-01-06": 11.0, "2026-01-07": 12.0}
    b = {"2026-01-05": 100.0, "2026-01-07": 110.0}
    _, _, rb = an.pares_de_retornos(a, b)
    assert all(r != 0 for r in rb)


def test_pares_ignoram_valores_nao_positivos():
    a = {"2026-01-05": 10.0, "2026-01-06": 0.0, "2026-01-07": 12.0}
    b = {"2026-01-05": 100.0, "2026-01-06": 100.0, "2026-01-07": 110.0}
    datas, _, _ = an.pares_de_retornos(a, b)
    assert datas == []  # 06 cai por ser zero; 07 cai porque o par dele é o 06


# ---------------------------------------------------------------------------
# Correlação e beta móveis
# ---------------------------------------------------------------------------


def retornos_variados(n, semente=12345):
    """Retornos diários determinísticos e de fato variáveis.

    Uma série de crescimento **constante** tem variância zero nos retornos, e aí
    correlação e beta são 0/0 — indefinidos, não iguais a 1. Foi essa a
    armadilha na primeira versão destes testes.
    """
    estado = semente
    saida = []
    for _ in range(n):
        estado = (1103515245 * estado + 12345) % (2**31)
        saida.append((estado / 2**31 - 0.5) * 0.04)  # ±2% ao dia
    return saida


def de_retornos(retornos, inicio=100.0):
    valores, atual = [inicio], inicio
    for r in retornos:
        atual *= math.exp(r)
        valores.append(atual)
    return serie(valores)


def test_beta_de_serie_perfeitamente_dobrada_e_dois():
    r = retornos_variados(80)
    fator = de_retornos(r)
    ativo = de_retornos([2 * x for x in r])
    saida = an.estatisticas_moveis(ativo, fator, janela=60)
    assert saida["beta"][-1] == pytest.approx(2.0, abs=0.01)
    assert saida["corr"][-1] == pytest.approx(1.0, abs=0.001)


def test_correlacao_negativa_perfeita():
    r = retornos_variados(80)
    saida = an.estatisticas_moveis(de_retornos([-x for x in r]), de_retornos(r), janela=60)
    assert saida["corr"][-1] == pytest.approx(-1.0, abs=0.001)
    assert saida["beta"][-1] == pytest.approx(-1.0, abs=0.01)


def test_correlacao_fica_dentro_de_menos_um_e_um():
    r = retornos_variados(200, semente=7)
    s = retornos_variados(200, semente=99)
    saida = an.estatisticas_moveis(de_retornos(s), de_retornos(r), janela=60)
    assert all(-1.0 <= c <= 1.0 for c in saida["corr"] if c is not None)


def test_janela_incompleta_fica_nula():
    r = retornos_variados(80)
    saida = an.estatisticas_moveis(de_retornos([2 * x for x in r]), de_retornos(r), janela=60)
    assert saida["corr"][:59] == [None] * 59
    assert saida["beta"][58] is None
    assert saida["beta"][59] is not None


def test_fator_parado_nao_produz_beta():
    """Série constante: variância zero no explicativo, beta indefinido."""
    fator = serie([100.0] * 80)
    ativo = de_retornos(retornos_variados(79))
    saida = an.estatisticas_moveis(ativo, fator, janela=60)
    assert saida["beta"][-1] is None
    assert saida["corr"][-1] is None


def test_serie_de_crescimento_constante_nao_vira_correlacao_um():
    """Retorno idêntico todo dia é variância zero — 0/0, não correlação 1."""
    fator = serie([100 * (1.01**i) for i in range(80)])
    ativo = serie([100 * (1.02**i) for i in range(80)])
    saida = an.estatisticas_moveis(ativo, fator, janela=60)
    assert saida["corr"][-1] is None


# ---------------------------------------------------------------------------
# Brent em reais
# ---------------------------------------------------------------------------


def test_serie_em_reais_multiplica_data_a_data():
    brent = {"2026-01-05": 80.0, "2026-01-06": 82.0}
    cambio = {"2026-01-05": 5.0, "2026-01-06": 5.5}
    assert an.serie_em_reais(brent, cambio) == {"2026-01-05": 400.0, "2026-01-06": 451.0}


def test_serie_em_reais_exige_as_duas_cotacoes():
    brent = {"2026-01-05": 80.0, "2026-01-06": 82.0}
    cambio = {"2026-01-05": 5.0}
    assert an.serie_em_reais(brent, cambio) == {"2026-01-05": 400.0}


def test_indice_base_100_comeca_no_primeiro_ponto_valido():
    s = {"2026-01-06": 50.0, "2026-01-07": 75.0}
    assert an.indice_base_100(s, ["2026-01-05", "2026-01-06", "2026-01-07"]) == [None, 100.0, 150.0]


# ---------------------------------------------------------------------------
# Retorno total e yield
# ---------------------------------------------------------------------------


def test_retorno_total_reinveste_o_provento_na_data_ex():
    linhas = linhas_de(serie([10.0, 10.0, 10.0]))
    datas = [linha["d"] for linha in linhas]
    tr = an.indice_retorno_total(linhas, {datas[1]: 1.0})
    # preço não anda; o total ganha 10% no dia do provento e carrega o ganho
    assert tr["preco"] == [100.0, 100.0, 100.0]
    assert tr["total"] == [100.0, 110.0, 110.0]


def test_retorno_total_sem_proventos_acompanha_o_preco():
    linhas = linhas_de(serie([10.0, 11.0, 12.0]))
    tr = an.indice_retorno_total(linhas, {})
    assert tr["total"] == tr["preco"]


def test_yield_ttm_soma_365_dias_e_divide_pelo_fechamento_do_dia():
    from datetime import date, timedelta

    base = date(2025, 1, 6)
    linhas = [
        {"d": (base + timedelta(days=i)).isoformat(), "o": 10, "h": 10, "l": 10, "c": 10.0, "v": 1}
        for i in range(0, 800, 7)
    ]
    proventos = {"2025-06-02": 0.50, "2025-12-01": 0.50}
    y = an.yield_ttm(linhas, proventos)
    # o primeiro ano fica de fora
    assert y["d"][0] >= "2026-01-06"
    # em 2026-01-06 os dois proventos ainda estão na janela: 1,00 / 10,00 = 10%
    assert y["y"][0] == pytest.approx(10.0, abs=0.01)
    # depois de 2026-06-02 o primeiro provento sai da janela
    depois = [v for d, v in zip(y["d"], y["y"], strict=True) if d > "2026-06-03"]
    assert depois and depois[0] == pytest.approx(5.0, abs=0.01)


def test_yield_ttm_sem_12_meses_nao_publica_nada():
    linhas = linhas_de(serie([10.0, 11.0, 12.0]))
    assert an.yield_ttm(linhas, {"2026-01-06": 1.0}) == {"d": [], "y": []}


# ---------------------------------------------------------------------------
# Volatilidade e faixa de 52 semanas
# ---------------------------------------------------------------------------


def test_volatilidade_de_serie_sem_variacao_e_zero():
    linhas = linhas_de(serie([10.0] * 30))
    vol = an.volatilidade_realizada(linhas, janelas=(21,))
    assert vol["v21"][-1] == 0.0


def test_volatilidade_anualiza_por_raiz_de_252():
    # retornos alternando +1% e -1% em log
    valores, atual = [100.0], 100.0
    for i in range(40):
        atual *= math.exp(0.01 if i % 2 == 0 else -0.01)
        valores.append(atual)
    linhas = linhas_de(serie(valores))
    vol = an.volatilidade_realizada(linhas, janelas=(21,))
    esperado = 0.01 * math.sqrt(252) * 100  # ~15,9% a.a.
    assert vol["v21"][-1] == pytest.approx(esperado, rel=0.05)


def test_volatilidade_marca_janela_incompleta_como_nula():
    linhas = linhas_de(serie([10.0 + i for i in range(30)]))
    vol = an.volatilidade_realizada(linhas, janelas=(21,))
    assert vol["v21"][0] is None
    assert vol["v21"][20] is not None


def test_posicao_na_faixa():
    linhas = linhas_de(serie([10.0, 20.0, 15.0]))
    faixa = an.posicao_na_faixa(linhas, pregoes=252)
    # h = c*1.01 e l = c*0.99, então máx = 20,2 e mín = 9,9
    assert faixa["faixa_max"] == pytest.approx(20.2, abs=0.01)
    assert faixa["faixa_min"] == pytest.approx(9.9, abs=0.01)
    assert faixa["faixa_pct"] == pytest.approx((15 - 9.9) / (20.2 - 9.9) * 100, abs=0.1)


def test_posicao_na_faixa_com_serie_curta_nao_publica():
    assert an.posicao_na_faixa(linhas_de(serie([10.0])), pregoes=252) == {}


# ---------------------------------------------------------------------------
# Razão ON/PN e paridade do ADR
# ---------------------------------------------------------------------------


def test_razao_entre_series_deixa_nulo_onde_falta_lado():
    on = {"2026-01-05": 55.0, "2026-01-07": 56.0}
    pn = {"2026-01-05": 50.0, "2026-01-06": 50.0, "2026-01-07": 50.0}
    assert an.razao_entre_series(on, pn, ["2026-01-05", "2026-01-06", "2026-01-07"]) == [
        1.1,
        None,
        1.12,
    ]


def test_paridade_do_adr_sem_premio_da_zero():
    # ADR a 20 USD, câmbio 5, 2 ações por ADR -> implícito 50,00
    adr = {"2026-01-05": 20.0}
    fx = {"2026-01-05": 5.0}
    local = {"2026-01-05": 50.0}
    assert an.paridade_adr(adr, fx, local, 2, ["2026-01-05"]) == [0.0]


def test_paridade_do_adr_mede_premio_em_percentual():
    adr = {"2026-01-05": 21.0}  # implícito 52,50 contra 50,00 na bolsa
    fx = {"2026-01-05": 5.0}
    local = {"2026-01-05": 50.0}
    assert an.paridade_adr(adr, fx, local, 2, ["2026-01-05"]) == [5.0]


def test_confere_razao_do_adr_aceita_a_razao_certa():
    datas = sorted(serie([1.0] * 40))
    adr = {d: 20.0 for d in datas}
    fx = {d: 5.0 for d in datas}
    local = {d: 50.0 for d in datas}
    assert an.confere_razao_do_adr(adr, fx, local, esperado=2)
    assert not an.confere_razao_do_adr(adr, fx, local, esperado=4)


def test_confere_razao_do_adr_recusa_amostra_pequena():
    adr, fx, local = {"2026-01-05": 20.0}, {"2026-01-05": 5.0}, {"2026-01-05": 50.0}
    assert not an.confere_razao_do_adr(adr, fx, local, esperado=2)
