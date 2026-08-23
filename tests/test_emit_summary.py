"""Testes do resumo enviado por e-mail pela rotina."""

import json

import emit_summary as es
import pytest
import update_dashboard as ud
from test_update_dashboard import SERIE


@pytest.fixture
def data_js(tmp_path):
    payload = ud.monta_payload([dict(p) for p in SERIE], {"2026-08-11": 0.5})
    arquivo = tmp_path / "data.js"
    arquivo.write_text(
        ud.PREFIXO + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8"
    )
    return arquivo


def test_resumo_traz_o_pregao_do_dia(data_js):
    r = es.resumo(es.carrega(data_js))
    assert r["last_date"] == "2026-08-21"
    assert r["last_close"] == "11.20"
    assert r["prev_close"] == "11.10"
    assert r["var_dia"].startswith("+")
    assert r["seta_dia"] == "▲"


def test_resumo_marca_queda_em_vermelho(tmp_path):
    serie = [dict(p) for p in SERIE]
    serie[-1]["c"] = 10.0  # fecha abaixo do pregão anterior
    payload = ud.monta_payload(serie, {})
    arquivo = tmp_path / "data.js"
    arquivo.write_text(ud.PREFIXO + json.dumps(payload) + ";\n", encoding="utf-8")

    r = es.resumo(es.carrega(arquivo))
    assert r["var_dia"].startswith("-")
    assert r["seta_dia"] == "▼"
    assert r["cor_dia"] == "#cf222e"


def test_todos_os_valores_sao_seguros_para_github_output(data_js):
    # O GitHub Actions quebra se um valor contiver quebra de linha.
    for chave, valor in es.resumo(es.carrega(data_js)).items():
        assert "\n" not in valor, chave
        assert "\r" not in valor, chave


def test_carrega_rejeita_arquivo_com_prefixo_errado(tmp_path):
    arquivo = tmp_path / "data.js"
    arquivo.write_text("var outraCoisa = {};", encoding="utf-8")
    with pytest.raises(ValueError):
        es.carrega(arquivo)
