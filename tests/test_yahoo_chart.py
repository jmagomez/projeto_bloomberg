"""Testes da coleta e da validação de atualidade — sem rede.

O caso central reproduz o incidente de 2026-08-22: a resposta vem com HTTP 200,
mas a série termina em 2026-08-20 enquanto o próprio `meta.regularMarketTime`
aponta o pregão de 2026-08-21 como o último fechado.
"""

import pytest
import yahoo_chart as yc

# Epochs reais da B3 (abertura às 10:00 BRT = 13:00 UTC), gmtoffset -10800.
TS_QUI_20 = 1787230800  # 2026-08-20
TS_SEX_21 = 1787317200  # 2026-08-21
FIM_PREGAO_SEX = 1787342400  # 2026-08-21 17:00 BRT
MARKET_TIME_SEX = 1787342739  # 2026-08-21 17:05 BRT
OFFSET = -10800


def resposta(timestamps, market_time, regular_start, regular_end, dividendos=None):
    n = len(timestamps)
    res = {
        "meta": {
            "gmtoffset": OFFSET,
            "regularMarketTime": market_time,
            "currentTradingPeriod": {"regular": {"start": regular_start, "end": regular_end}},
        },
        "timestamp": list(timestamps),
        "indicators": {
            "quote": [
                {
                    "open": [10.0 + i for i in range(n)],
                    "high": [11.0 + i for i in range(n)],
                    "low": [9.0 + i for i in range(n)],
                    "close": [10.5 + i for i in range(n)],
                    "volume": [1_000_000 + i for i in range(n)],
                }
            ]
        },
    }
    if dividendos:
        res["events"] = {"dividends": dividendos}
    return res


def test_data_da_bolsa_usa_o_fuso_da_bolsa():
    # A barra de 21/08 é carimbada às 13:00 UTC; no fuso da B3 ainda é 21/08.
    assert yc.data_da_bolsa(TS_SEX_21, OFFSET) == "2026-08-21"
    assert yc.data_da_bolsa(TS_QUI_20, OFFSET) == "2026-08-20"


def test_data_da_bolsa_nao_vaza_para_o_dia_seguinte():
    # Uma barra carimbada às 23:00 no fuso da bolsa continua sendo do mesmo dia.
    ts_23h_local = TS_SEX_21 + 13 * 3600  # 23:00 BRT
    assert yc.data_da_bolsa(ts_23h_local, OFFSET) == "2026-08-21"


def test_extrai_pregoes_descarta_barra_parcial():
    res = resposta([TS_QUI_20, TS_SEX_21], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX)
    res["indicators"]["quote"][0]["close"][1] = None  # barra em consolidação
    linhas = yc.extrai_pregoes(res)
    assert [linha["d"] for linha in linhas] == ["2026-08-20"]


def test_extrai_proventos_soma_por_data():
    dividendos = {
        "a": {"date": TS_SEX_21, "amount": 0.5},
        "b": {"date": TS_SEX_21, "amount": 0.25},
        "c": {"date": TS_QUI_20, "amount": "invalido"},
    }
    proventos = yc.extrai_proventos(
        resposta([TS_QUI_20, TS_SEX_21], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX, dividendos)
    )
    assert proventos == {"2026-08-21": 0.75}


def test_pregao_faltando_e_sinalizado_como_pendente():
    """O incidente de 2026-08-22, reproduzido.

    A validação não derruba mais a rotina: marca a pendência e deixa a decisão
    para update_dashboard, que só desiste se a coleta também não avançar.
    """
    res = resposta([TS_QUI_20], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX)
    linhas = yc.extrai_pregoes(res)
    estado = yc.estado_do_mercado(res)

    assert estado["ultimo_pregao"] == "2026-08-21"
    assert estado["aberto"] is False
    linhas, avisos, pendente = yc.valida_atualidade(linhas, estado)
    assert pendente == "2026-08-21"
    assert linhas[-1]["d"] == "2026-08-20"
    assert any("2026-08-21" in a and "2026-08-20" in a for a in avisos)


def test_serie_vazia_ainda_levanta():
    with pytest.raises(yc.DadosDesatualizadosError):
        yc.valida_atualidade([], {"ultimo_pregao": "2026-08-21", "aberto": False})


def test_serie_completa_e_aceita():
    res = resposta([TS_QUI_20, TS_SEX_21], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX)
    linhas, avisos, pendente = yc.valida_atualidade(
        yc.extrai_pregoes(res), yc.estado_do_mercado(res)
    )
    assert linhas[-1]["d"] == "2026-08-21"
    assert avisos == []
    assert pendente is None


def test_pregao_em_andamento_descarta_a_barra_do_dia(monkeypatch):
    # Congela "agora" dentro do horário do pregão de 21/08.
    meio_do_pregao = TS_SEX_21 + 3 * 3600
    monkeypatch.setattr(yc, "datetime", _relogio_fixo(meio_do_pregao))

    res = resposta([TS_QUI_20, TS_SEX_21], meio_do_pregao, TS_SEX_21, FIM_PREGAO_SEX)
    estado = yc.estado_do_mercado(res)
    assert estado["aberto"] is True

    linhas, avisos, pendente = yc.valida_atualidade(yc.extrai_pregoes(res), estado)
    assert [linha["d"] for linha in linhas] == ["2026-08-20"]
    assert any("em andamento" in aviso for aviso in avisos)
    assert pendente is None


def test_sem_regular_market_time_apenas_avisa():
    res = resposta([TS_QUI_20], None, TS_SEX_21, FIM_PREGAO_SEX)
    linhas, avisos, pendente = yc.valida_atualidade(
        yc.extrai_pregoes(res), yc.estado_do_mercado(res)
    )
    assert linhas[-1]["d"] == "2026-08-20"
    assert any("regularMarketTime" in aviso for aviso in avisos)
    assert pendente is None


def test_mescla_prefere_a_serie_mais_recente():
    longa = [{"d": "2026-08-20", "c": 1.0}]
    curta = [{"d": "2026-08-20", "c": 2.0}, {"d": "2026-08-21", "c": 3.0}]
    assert yc._mescla(longa, curta) == [
        {"d": "2026-08-20", "c": 2.0},
        {"d": "2026-08-21", "c": 3.0},
    ]


def _relogio_fixo(epoch):
    """datetime com now() congelado, preservando o resto da API."""
    import datetime as _dt

    class _Fixo(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime.fromtimestamp(epoch, tz=tz or _dt.UTC)

    return _Fixo


# ---------------------------------------------------------------------------
# Recomposição do fechamento a partir do meta (incidente de 2026-08-28: o Yahoo
# passou a servir a barra do pregão com close nulo e assim ficou por mais de um
# dia; os demais campos, e o fechamento em meta.regularMarketPrice, estavam lá).
# ---------------------------------------------------------------------------


def resposta_close_nulo(preco_meta, low=42.62, high=43.60):
    res = resposta([TS_QUI_20, TS_SEX_21], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX)
    q = res["indicators"]["quote"][0]
    q["open"][1], q["high"][1], q["low"][1] = 42.72, high, low
    q["close"][1] = None
    q["volume"][1] = 46064700
    res["meta"]["regularMarketPrice"] = preco_meta
    return res


def test_recompoe_fechamento_nulo_a_partir_do_meta():
    res = resposta_close_nulo(43.55)
    linhas = yc.extrai_pregoes(res)
    assert [linha["d"] for linha in linhas] == ["2026-08-20"]  # barra caiu fora

    linhas, recomposta = yc.recupera_fechamento_do_meta(res, linhas)
    assert recomposta == "2026-08-21"
    assert linhas[-1]["d"] == "2026-08-21"
    assert linhas[-1]["c"] == 43.55
    assert linhas[-1]["v"] == 46064700
    assert linhas[-1]["c_de_meta"] is True

    # e aí a validação passa a considerar a série completa
    _, _, pendente = yc.valida_atualidade(linhas, yc.estado_do_mercado(res))
    assert pendente is None


def test_nao_recompoe_se_preco_do_meta_sai_da_faixa_da_barra():
    # 50,00 está fora de [42,62; 43,60]: incoerente com a própria barra
    res = resposta_close_nulo(50.00)
    linhas, recomposta = yc.recupera_fechamento_do_meta(res, yc.extrai_pregoes(res))
    assert recomposta is None
    assert linhas[-1]["d"] == "2026-08-20"


def test_nao_recompoe_com_pregao_em_andamento(monkeypatch):
    meio = TS_SEX_21 + 3 * 3600
    monkeypatch.setattr(yc, "datetime", _relogio_fixo(meio))
    res = resposta_close_nulo(43.55)
    res["meta"]["regularMarketTime"] = meio  # antes do fim do horário regular
    linhas, recomposta = yc.recupera_fechamento_do_meta(res, yc.extrai_pregoes(res))
    assert recomposta is None


def test_nao_recompoe_barra_do_meio_da_serie():
    # buraco no meio nunca é preenchido: só a última barra pode ser recomposta
    res = resposta([TS_QUI_20, TS_SEX_21], MARKET_TIME_SEX, TS_SEX_21, FIM_PREGAO_SEX)
    res["indicators"]["quote"][0]["close"][0] = None
    res["meta"]["regularMarketPrice"] = 10.5
    linhas, recomposta = yc.recupera_fechamento_do_meta(res, yc.extrai_pregoes(res))
    assert recomposta is None
    assert [linha["d"] for linha in linhas] == ["2026-08-21"]


def test_nao_recompoe_sem_preco_no_meta():
    res = resposta_close_nulo(None)
    _, recomposta = yc.recupera_fechamento_do_meta(res, yc.extrai_pregoes(res))
    assert recomposta is None
