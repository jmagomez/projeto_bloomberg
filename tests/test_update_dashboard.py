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


def test_payload_tem_os_quatro_blocos():
    payload = ud.monta_payload([dict(p) for p in SERIE], {"2026-08-11": 0.5})
    assert set(payload) == {"stats", "D", "W", "DIV"}
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
