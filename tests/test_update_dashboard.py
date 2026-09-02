"""Testes das agregações e estatísticas do data.js — sem rede."""

import json

import pytest
import update_dashboard as ud
from yahoo_chart import DadosDesatualizadosError


def pregao(d, o, h, low, c, v=1_000_000, e=0.0):
    return {"d": d, "o": o, "h": h, "l": low, "c": c, "v": v, "e": e}


# Duas semanas cheias: 10-14/08 (seg-sex) e 17-21/08 (seg-sex) de 2026.
SEMANA_1 = [
    pregao("2026-08-10", 10.0, 10.5, 9.8, 10.2),
    pregao("2026-08-11", 10.2, 10.9, 10.1, 10.8),
    pregao("2026-08-12", 10.8, 11.0, 10.4, 10.5),
    pregao("2026-08-13", 10.5, 10.6, 10.0, 10.1),
    pregao("2026-08-14", 10.1, 10.4, 9.9, 10.3),
]
SEMANA_2 = [
    pregao("2026-08-17", 10.3, 10.7, 10.2, 10.6),
    pregao("2026-08-18", 10.6, 11.2, 10.5, 11.0),
    pregao("2026-08-19", 11.0, 11.5, 10.9, 11.4),
    pregao("2026-08-20", 11.4, 11.6, 11.0, 11.1),
    pregao("2026-08-21", 11.1, 11.3, 10.8, 11.2),
]
SERIE = SEMANA_1 + SEMANA_2


def test_semanal_agrupa_de_segunda_a_sexta():
    W = ud.semanal([dict(p) for p in SERIE])
    assert W["d"] == ["2026-08-14", "2026-08-21"]  # rotulada pelo último pregão
    assert W["o"] == [10.0, 10.3]  # abertura da segunda
    assert W["c"] == [10.3, 11.2]  # fechamento da sexta
    assert W["h"] == [11.0, 11.6]
    assert W["l"] == [9.8, 10.2]
    assert W["v"] == [5.0, 5.0]  # em milhões


def test_semanal_nao_depende_do_fuso_da_maquina(monkeypatch):
    """A versão antiga usava datetime.timestamp() (fuso local) para agrupar."""
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")  # UTC+14
    import time

    if hasattr(time, "tzset"):
        time.tzset()
    W = ud.semanal([dict(p) for p in SERIE])
    assert W["d"] == ["2026-08-14", "2026-08-21"]


def test_semana_parcial_termina_no_ultimo_pregao_disponivel():
    parcial = SEMANA_1 + SEMANA_2[:3]  # semana 2 só até quarta
    W = ud.semanal([dict(p) for p in parcial])
    assert W["d"][-1] == "2026-08-19"
    assert W["c"][-1] == 11.4


def test_diaria_recorta_a_janela_pedida():
    D = ud.diaria([dict(p) for p in SERIE], janela=3)
    assert D["d"] == ["2026-08-19", "2026-08-20", "2026-08-21"]
    assert D["c"] == [11.4, 11.1, 11.2]


def test_estatisticas_do_ultimo_pregao():
    stats = ud.estatisticas([dict(p) for p in SERIE], {})
    assert stats["last_date"] == "2026-08-21"
    assert stats["last_close"] == 11.2
    assert stats["prev_date"] == "2026-08-20"
    assert stats["prev_close"] == 11.1
    assert stats["day_change_pct"] == pytest.approx(0.9, abs=0.01)  # 11.2/11.1-1
    assert stats["day_open"] == 11.1
    assert stats["day_high"] == 11.3
    assert stats["day_low"] == 10.8
    assert stats["max_high"] == 11.6 and stats["max_high_date"] == "2026-08-20"
    assert stats["min_low"] == 9.8 and stats["min_low_date"] == "2026-08-10"
    assert stats["days"] == 10


def test_estatisticas_exigem_dois_pregoes():
    with pytest.raises(ValueError):
        ud.estatisticas([dict(SERIE[0])], {})


def test_proventos_no_periodo_e_em_12_meses():
    proventos = {
        "2025-01-15": 1.0,  # fora da janela de 12 meses
        "2026-03-10": 2.0,
        "2026-08-11": 0.5,
        "2027-01-01": 9.9,  # depois do fim do período — deve ser ignorado
    }
    total, ttm, por_ano = ud.calendario_de_proventos(proventos, "2026-01-01", "2026-08-21")
    assert total == 2.5
    assert ttm == 2.5
    assert por_ano == {"2026": 2.5}


def test_dividend_yield_usa_o_ultimo_fechamento():
    stats = ud.estatisticas([dict(p) for p in SERIE], {"2026-08-11": 1.12})
    # 1.12 / 11.20 = 10%
    assert stats["div_yield_ttm_pct"] == pytest.approx(10.0, abs=0.01)


def test_payload_tem_os_blocos_esperados():
    payload = ud.monta_payload([dict(p) for p in SERIE], {"2026-08-11": 0.5})
    # TR e RISCO saem sempre: dependem só da própria série da PETR4.
    assert set(payload) == {"stats", "D", "W", "M", "DIV", "TR", "RISCO"}
    assert payload["DIV"] == {"y": ["2026"], "v": [0.5]}
    assert payload["D"]["e"][1] == 0.5  # provento marcado no dia certo
    assert json.dumps(payload)  # serializável


def test_regressao_de_data_e_bloqueada():
    anterior = {"stats": {"last_date": "2026-08-21", "days": 10}}
    novas = {"last_date": "2026-08-20", "days": 10}
    with pytest.raises(DadosDesatualizadosError):
        ud.confere_sem_regressao(novas, anterior)


def test_regressao_de_quantidade_e_bloqueada():
    anterior = {"stats": {"last_date": "2026-08-21", "days": 4133}}
    novas = {"last_date": "2026-08-21", "days": 900}
    with pytest.raises(DadosDesatualizadosError):
        ud.confere_sem_regressao(novas, anterior)


def test_avanco_normal_passa():
    anterior = {"stats": {"last_date": "2026-08-20", "days": 9}}
    novas = {"last_date": "2026-08-21", "days": 10}
    ud.confere_sem_regressao(novas, anterior)  # não levanta


def test_le_payload_atual_ida_e_volta(tmp_path):
    payload = ud.monta_payload([dict(p) for p in SERIE], {})
    arquivo = tmp_path / "data.js"
    arquivo.write_text(
        ud.PREFIXO + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8"
    )
    assert ud.le_payload_atual(arquivo)["stats"]["last_date"] == "2026-08-21"


def test_le_payload_atual_tolera_arquivo_invalido(tmp_path):
    arquivo = tmp_path / "data.js"
    arquivo.write_text("window.PETR4 = {quebrado;", encoding="utf-8")
    assert ud.le_payload_atual(arquivo) is None
    assert ud.le_payload_atual(tmp_path / "inexistente.js") is None


# ---------------------------------------------------------------------------
# Drawdown, série mensal, alinhamento do índice de referência e publicação
# parcial quando a fonte deve um pregão.
# ---------------------------------------------------------------------------


def serie_com_topo_e_fundo():
    """Sobe até 20, cai até 8 (-60%), volta a 21 (recupera e faz novo topo)."""
    precos = [10, 14, 20, 15, 8, 12, 19, 21]
    datas = [
        "2026-01-05",
        "2026-02-05",
        "2026-03-05",
        "2026-04-06",
        "2026-05-05",
        "2026-06-05",
        "2026-07-06",
        "2026-08-05",
    ]
    return [pregao(d, c, c + 1, c - 1, c) for d, c in zip(datas, precos, strict=True)]


def test_drawdown_encontra_pior_queda_e_recuperacao():
    dd = ud.drawdown(serie_com_topo_e_fundo())
    assert dd["max_drawdown_pct"] == pytest.approx(-60.0, abs=0.01)  # 8/20 - 1
    assert dd["max_drawdown_de"] == "2026-03-05"  # pico anterior à queda
    assert dd["max_drawdown_ate"] == "2026-05-05"  # fundo
    assert dd["max_drawdown_recuperado"] == "2026-08-05"  # primeiro fech. >= 20
    assert dd["ath_close"] == 21
    assert dd["ath_date"] == "2026-08-05"
    assert dd["drawdown_atual_pct"] == pytest.approx(0.0, abs=0.01)


def test_drawdown_sem_recuperacao_fica_none():
    serie = serie_com_topo_e_fundo()[:6]  # termina em 12, sem voltar aos 20
    dd = ud.drawdown(serie)
    assert dd["max_drawdown_recuperado"] is None
    assert dd["drawdown_atual_pct"] == pytest.approx(-40.0, abs=0.01)  # 12/20 - 1


def test_mensal_ignora_o_primeiro_mes_por_falta_de_base():
    M = ud.mensal([dict(p) for p in SERIE])
    assert M["d"] == []  # SERIE inteira cabe em agosto/2026: nenhum retorno completo
    M2 = ud.mensal(serie_com_topo_e_fundo())
    assert M2["d"] == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert M2["r"][0] == pytest.approx(40.0, abs=0.01)  # 14/10 - 1
    assert M2["r"][3] == pytest.approx(-46.67, abs=0.01)  # 8/15 - 1


def test_mensal_usa_o_ultimo_fechamento_de_cada_mes():
    serie = [
        pregao("2026-01-05", 10, 10, 10, 10),
        pregao("2026-01-30", 10, 10, 10, 20),  # fechamento do mês
        pregao("2026-02-27", 20, 20, 20, 30),
    ]
    M = ud.mensal(serie)
    assert M["d"] == ["2026-02"]
    assert M["r"] == [50.0]  # 30/20 - 1


def test_alinha_referencia_repete_ultimo_valor_e_nao_interpola():
    ref = {"2026-08-10": 100.0, "2026-08-12": 110.0}
    datas = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]
    assert ud.alinha_referencia(ref, datas) == [100.0, 100.0, 110.0, 110.0]


def test_alinha_referencia_deixa_nulo_antes_do_primeiro_dado():
    ref = {"2026-08-12": 110.0}
    assert ud.alinha_referencia(ref, ["2026-08-10", "2026-08-12"]) == [None, 110.0]


def test_alinha_referencia_sem_dados_devolve_vazio():
    assert ud.alinha_referencia({}, ["2026-08-10"]) == []


def test_payload_traz_os_blocos_novos():
    ref = {p["d"]: 100.0 + i for i, p in enumerate(SERIE)}
    payload = ud.monta_payload([dict(p) for p in SERIE], {}, ref, pendente="2026-08-24")
    assert set(payload) == {"stats", "D", "W", "M", "DIV", "REF", "TR", "RISCO"}
    assert payload["stats"]["pending_session"] == "2026-08-24"
    assert payload["stats"]["close_source"] == "chart"
    assert payload["stats"]["max_drawdown_pct"] <= 0
    assert len(payload["REF"]["D"]) == len(payload["D"]["d"])
    assert len(payload["REF"]["W"]) == len(payload["W"]["d"])
    assert json.dumps(payload)


def test_payload_sem_referencia_omite_o_bloco():
    payload = ud.monta_payload([dict(p) for p in SERIE], {}, {}, None)
    assert "REF" not in payload
    # e sem as séries setoriais, os painéis delas também somem
    assert "BRENT" not in payload
    assert "PARES" not in payload
    assert payload["stats"]["pending_session"] is None


def test_close_source_marca_fechamento_vindo_do_meta():
    serie = [dict(p) for p in SERIE]
    serie[-1]["c_de_meta"] = True
    assert ud.monta_payload(serie, {})["stats"]["close_source"] == "meta"


# ---------------------------------------------------------------------------
# Travas de sanidade do payload pronto (incidente de 2026-08-31).
# ---------------------------------------------------------------------------


def test_payload_com_preco_zerado_nao_e_publicado():
    serie = [dict(p) for p in SERIE]
    serie[-1]["l"] = 0.0
    payload = ud.monta_payload(serie, {})
    with pytest.raises(DadosDesatualizadosError, match="impossível"):
        ud.confere_precos_possiveis(payload)


def test_payload_com_abertura_zerada_nao_e_publicado():
    serie = [dict(p) for p in SERIE]
    serie[-1]["o"] = 0.0
    with pytest.raises(DadosDesatualizadosError, match="impossível"):
        ud.confere_precos_possiveis(ud.monta_payload(serie, {}))


def test_payload_saudavel_passa_na_trava():
    ud.confere_precos_possiveis(ud.monta_payload([dict(p) for p in SERIE], {}))


def test_minima_que_despenca_e_barrada():
    anterior = {"stats": {"last_date": "2026-08-20", "days": 9, "min_low": 4.12}}
    novas = {"last_date": "2026-08-21", "days": 10, "min_low": 0.0}
    with pytest.raises(DadosDesatualizadosError, match="despencou"):
        ud.confere_sem_regressao(novas, anterior)


def test_minima_que_cai_dentro_do_razoavel_passa():
    anterior = {"stats": {"last_date": "2026-08-20", "days": 9, "min_low": 4.12}}
    novas = {"last_date": "2026-08-21", "days": 10, "min_low": 3.90}
    ud.confere_sem_regressao(novas, anterior)  # não levanta


def test_marca_fora_faixa_nao_vaza_para_o_payload():
    """A marca é para o log; o data.js publica só os campos de sempre."""
    serie = [dict(p) for p in SERIE]
    serie[-1]["fora_faixa"] = True
    payload = ud.monta_payload(serie, {})
    assert "fora_faixa" not in payload["D"]
    assert "fora_faixa" not in payload["W"]
    assert "fora_faixa" not in payload["stats"]
    ud.confere_precos_possiveis(payload)  # e continua publicável


# ---------------------------------------------------------------------------
# Amostragem semanal e blocos analíticos
# ---------------------------------------------------------------------------


def test_amostra_semanal_pega_a_ultima_observacao_de_cada_semana():
    datas = [p["d"] for p in SERIE]  # 10-14/08 e 17-21/08 de 2026
    valores = list(range(10))
    d, (v,) = ud.amostra_semanal(datas, valores)
    assert d == ["2026-08-14", "2026-08-21"]
    assert v == [4, 9]  # sexta de cada semana


def test_amostra_semanal_nao_recalcula_nada():
    """Amostrar não é suavizar: cada ponto publicado existiu naquele pregão."""
    datas = [p["d"] for p in SERIE]
    valores = [10.0, 99.0, 10.0, 10.0, 7.5, 1, 2, 3, 4, 42.0]
    _, (v,) = ud.amostra_semanal(datas, valores)
    assert v == [7.5, 42.0]
    assert all(x in valores for x in v)


def test_amostra_semanal_com_serie_vazia():
    assert ud.amostra_semanal([], []) == ([], [[]])


def test_amostra_semanal_preserva_varias_series_alinhadas():
    datas = [p["d"] for p in SERIE]
    a, b = list(range(10)), list(range(100, 110))
    d, (sa, sb) = ud.amostra_semanal(datas, a, b)
    assert len(d) == len(sa) == len(sb) == 2
    assert sb == [104, 109]


def test_blocos_sem_auxiliares_traz_so_o_que_depende_da_propria_serie():
    blocos, resumo = ud.blocos_analiticos([dict(p) for p in SERIE], {}, {})
    assert set(blocos) == {"TR", "RISCO"}
    assert "faixa_pct" in resumo  # a faixa de 52 semanas sai da própria série


def test_bloco_brent_exige_brent_e_cambio():
    linhas = [dict(p) for p in SERIE]
    datas = [linha["d"] for linha in linhas]
    brent = {d: 80.0 + i for i, d in enumerate(datas)}
    blocos, _ = ud.blocos_analiticos(linhas, {}, {"brent": brent})
    assert "BRENT" not in blocos  # sem câmbio não há Brent em reais
    blocos, resumo = ud.blocos_analiticos(
        linhas, {}, {"brent": brent, "cambio": {d: 5.0 for d in datas}}
    )
    assert "BRENT" in blocos
    assert resumo["brent_usd"] == 89.0
    assert resumo["brent_brl"] == 445.0


def test_painel_do_adr_nao_sai_se_a_razao_nao_bater():
    """Se um reagrupamento mudasse a razão, o painel some em vez de mentir."""
    linhas = [dict(p) for p in SERIE]
    datas = [linha["d"] for linha in linhas]
    cambio = {d: 5.0 for d in datas}
    # ADR precificado como se fossem 5 ações por ADR, com a constante em 2
    adr = {d: linha["c"] * 5 / 5.0 for d, linha in zip(datas, linhas, strict=True)}
    blocos, resumo = ud.blocos_analiticos(linhas, {}, {"cambio": cambio, "adr": adr})
    assert "PARES" not in blocos
    assert "adr_premio_pct" not in resumo


def test_bloco_pares_sai_com_a_ordinaria_mesmo_sem_adr():
    linhas = [dict(p) for p in SERIE]
    datas = [linha["d"] for linha in linhas]
    on = {d: linha["c"] * 1.1 for d, linha in zip(datas, linhas, strict=True)}
    blocos, resumo = ud.blocos_analiticos(linhas, {}, {"on": on})
    assert blocos["PARES"]["adr"] is None
    assert resumo["on_pn"] == pytest.approx(1.1, abs=0.001)


def test_resumo_traz_a_volatilidade_por_prazo():
    linhas = [dict(p) for p in SERIE]
    _, resumo = ud.blocos_analiticos(linhas, {}, {})
    # a série de teste tem 10 pregões: só a janela de 21 seria curta demais
    assert "faixa_max" in resumo and "faixa_min" in resumo


def test_manchetes_entram_no_payload_quando_existem():
    manchetes = {"2026-08-21": [{"h": "10:00", "t": "T", "v": "V", "u": "https://x"}]}
    payload = ud.monta_payload([dict(p) for p in SERIE], {}, None, None, None, manchetes)
    assert payload["NEWS"] == manchetes
    assert "NEWS" not in ud.monta_payload([dict(p) for p in SERIE], {})
