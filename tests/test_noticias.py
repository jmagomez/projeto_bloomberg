"""Testes da coleta e do acervo de manchetes — sem rede."""

import json

import noticias as nt

# 2026-08-31 14:00 BRT
TS = 1788195600


def item(
    titulo="Petrobras anuncia resultado", link="https://ex.com/1", ts=TS, tickers=None, ed="Reuters"
):
    return {
        "title": titulo,
        "link": link,
        "publisher": ed,
        "providerPublishTime": ts,
        "relatedTickers": tickers if tickers is not None else ["PBR", "PBR-A"],
    }


def test_relevante_aceita_titulo_que_cita_a_empresa():
    assert nt._relevante(item(titulo="Petrobras eyes LNG exports", tickers=["X"] * 20))


def test_relevante_recusa_retrospectiva_de_mercado():
    """O caso real: 18 tickers, título sobre Moderna e Allstate."""
    assert not nt._relevante(
        item(
            titulo="Moderna upgraded, Allstate downgraded: Wall Street's top calls",
            tickers=["MRNA", "ALL", "EPM", "FINV", "UMBF", "PBR", "PBR-A", "WULF", "TMC"],
        )
    )


def test_relevante_aceita_materia_curta_com_ticker_da_empresa():
    assert nt._relevante(item(titulo="Brazil oil output hits record", tickers=["PBR", "CL=F"]))


def test_relevante_recusa_materia_sem_relacao():
    assert not nt._relevante(item(titulo="Apple ships new phone", tickers=["AAPL"]))


# --- os três casos reais que a peneira antiga deixou passar -------------------

ROUNDUP = (
    "Here Are Friday's Top Wall Street Analyst Research Calls: Baozun, "
    "Commerce Bancshares, Element Solutions, Evolution Petroleum, Petrobras, "
    "Rythm Pharmaceuticals, Terawulf, UMB Financial, Workday, and More"
)
KNOT_1 = "KNOT Offshore Unit to Acquire Knutsen Canadian Chartering"
KNOT_2 = (
    "KNOT Offshore Partners LP Acquires Hedda Knutsen and Completes $225 Million Loan Refinancing"
)


def test_relevante_recusa_compilacao_que_cita_a_empresa_no_titulo():
    """Publicada em 28/08/2026 e guardada: dez companhias, nenhuma o assunto."""
    assert not nt._relevante(item(titulo=ROUNDUP, tickers=["PBR"]))


def test_relevante_recusa_fornecedor_que_pega_carona_no_ticker():
    """26/08/2026: o Yahoo marca PBR porque a armadora fretea navios à empresa."""
    assert not nt._relevante(item(titulo=KNOT_1, tickers=["KNOP", "PBR"]))
    assert not nt._relevante(item(titulo=KNOT_2, tickers=["KNOP", "PBR"]))


def test_refinanciamento_nao_conta_como_refino():
    """`refin` casaria com "Refinancing"; o padrão pede refinery/refining."""
    assert not nt.PADRAO_SETOR.search(KNOT_2)
    assert nt.PADRAO_SETOR.search("Shell restarts Bukom refining unit")


def test_relevante_mantem_as_manchetes_boas_do_mesmo_acervo():
    """As quatro que sobreviveram têm de continuar entrando."""
    for titulo in (
        "Petrobras and Pemex Explore Mexico's Deepwater Pre-Salt Potential",
        "PBR Q2 Earnings Beat on Record Output, but Can the Gains Persist?",
        "Petrobras Eyes LNG Exports to Asia as Gas Demand Surges",
        "Oil Stocks Hit New Highs After U.S. Resumes Strikes in Strait of Hormuz",
    ):
        assert nt._relevante(item(titulo=titulo, tickers=["PBR", "XOM"])), titulo


def test_retrospectiva_nao_derruba_titulo_com_poucas_virgulas():
    curto = "Petrobras raises diesel prices, first hike since March"
    assert not nt._e_retrospectiva(curto)
    assert nt._relevante(item(titulo=curto))


def test_depura_limpa_o_que_a_peneira_antiga_guardou():
    acervo = [
        nt._normaliza(item(titulo=ROUNDUP, link="https://ex.com/roundup")),
        nt._normaliza(item(titulo=KNOT_1, link="https://ex.com/knot")),
        nt._normaliza(item(titulo="Petrobras Eyes LNG Exports to Asia", link="https://ex.com/lng")),
    ]
    assert [x["link"] for x in nt.depura(acervo)] == ["https://ex.com/lng"]


def test_mescla_aplica_a_peneira_ao_acervo_antigo():
    antigo = [nt._normaliza(item(titulo=ROUNDUP, link="https://ex.com/roundup"))]
    novo = [nt._normaliza(item(titulo="Petrobras cuts capex guidance", link="https://ex.com/2"))]
    assert [x["link"] for x in nt.mescla(antigo, novo)] == ["https://ex.com/2"]


def test_normaliza_carimba_a_data_no_fuso_da_b3():
    saida = nt._normaliza(item())
    assert saida["d"] == "2026-08-31"
    assert saida["hora"] == "14:00"
    assert saida["veiculo"] == "Reuters"


def test_normaliza_nao_vaza_para_o_dia_seguinte():
    # 23:30 UTC de 31/08 ainda é 20:30 de 31/08 no fuso da B3
    saida = nt._normaliza(item(ts=1788219000))
    assert saida["d"] == "2026-08-31"


def test_normaliza_recusa_item_incompleto():
    assert nt._normaliza(item(titulo="")) is None
    assert nt._normaliza(item(link="")) is None
    assert nt._normaliza({"title": "x", "link": "y"}) is None


def test_mescla_deduplica_por_link():
    # os dois títulos passam pela peneira: o que se testa aqui é a dedup, e o
    # acervo agora é depurado antes de mesclar (ver `depura`)
    antigo = [nt._normaliza(item(titulo="Petrobras: título original", link="https://ex.com/1"))]
    novo = [nt._normaliza(item(titulo="Petrobras: título reescrito", link="https://ex.com/1"))]
    unido = nt.mescla(antigo, novo)
    assert len(unido) == 1
    # o que já estava guardado prevalece
    assert unido[0]["titulo"] == "Petrobras: título original"


def test_mescla_acumula_historico():
    antigo = [nt._normaliza(item(link="https://ex.com/1", ts=TS - 86400))]
    novo = [nt._normaliza(item(link="https://ex.com/2", ts=TS))]
    unido = nt.mescla(antigo, novo)
    assert [x["link"] for x in unido] == ["https://ex.com/2", "https://ex.com/1"]


def test_mescla_respeita_o_limite_mantendo_as_mais_novas():
    acervo = [nt._normaliza(item(link=f"https://ex.com/{i}", ts=TS - i * 3600)) for i in range(10)]
    unido = nt.mescla(acervo, [], limite=3)
    assert len(unido) == 3
    assert unido[0]["ts"] > unido[-1]["ts"]


def test_le_arquivo_tolera_ausencia_e_lixo(tmp_path):
    assert nt.le_arquivo(tmp_path / "nao_existe.json") == []
    ruim = tmp_path / "ruim.json"
    ruim.write_text("{quebrado", encoding="utf-8")
    assert nt.le_arquivo(ruim) == []
    objeto = tmp_path / "objeto.json"
    objeto.write_text('{"a": 1}', encoding="utf-8")
    assert nt.le_arquivo(objeto) == []


def test_ida_e_volta_do_arquivo(tmp_path):
    acervo = [nt._normaliza(item())]
    caminho = tmp_path / "noticias.json"
    nt.grava_arquivo(caminho, acervo)
    assert nt.le_arquivo(caminho) == acervo
    assert json.loads(caminho.read_text(encoding="utf-8"))


def test_por_pregao_agrupa_so_em_datas_de_pregao():
    acervo = [
        nt._normaliza(item(link="a", ts=TS)),  # 31/08, segunda
        nt._normaliza(item(link="b", ts=TS - 2 * 86400)),  # 29/08, sábado
    ]
    agrupado = nt.por_pregao(acervo, ["2026-08-28", "2026-08-31"])
    assert set(agrupado) == {"2026-08-31"}  # sábado não é pregão: fica de fora
    assert agrupado["2026-08-31"][0]["u"] == "a"


def test_por_pregao_ordena_do_mais_recente_no_dia():
    acervo = [
        nt._normaliza(item(link="cedo", ts=TS - 3600)),
        nt._normaliza(item(link="tarde", ts=TS)),
    ]
    agrupado = nt.por_pregao(acervo, ["2026-08-31"])
    assert [x["u"] for x in agrupado["2026-08-31"]] == ["tarde", "cedo"]


def test_por_pregao_limita_a_janela_recente():
    datas = [f"2026-0{m}-0{d}" for m in (7, 8) for d in (1, 2, 3)]
    acervo = [nt._normaliza(item(link="antigo", ts=TS - 60 * 86400))]
    assert nt.por_pregao(acervo, datas, pregoes=2) == {}
