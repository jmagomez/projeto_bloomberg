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


# --- o e-mail precisa saber quando não carrega o último pregão ----------------
#
# Incidente de 26/11/2026: a fonte devia o pregão de 25/11, serviu a série até
# 24/11, a rotina publicou o avanço parcial e o e-mail saiu anunciando
# "pregão de 2026-11-24" numa noite em que o pregão do dia era o 25/11.


@pytest.fixture
def data_js_com_pendencia(tmp_path):
    payload = ud.monta_payload([dict(p) for p in SERIE], {}, pendente="2026-08-24")
    arquivo = tmp_path / "data.js"
    arquivo.write_text(ud.PREFIXO + json.dumps(payload) + ";\n", encoding="utf-8")
    return arquivo


def test_assunto_normal_nao_menciona_pendencia(data_js):
    r = es.resumo(es.carrega(data_js))
    assert r["pendente"] == ""
    assert r["assunto"] == "PETR4 R$ 11.20 (+0.90% no dia) — pregão de 2026-08-21"
    assert r["banner_pendencia"] == ""
    assert r["titulo"] == "PETR4 — pregão de 2026-08-21"


def test_assunto_com_pendencia_avisa_antes_de_qualquer_coisa(data_js_com_pendencia):
    """A ressalva vem na frente: notificação de celular mostra só o começo."""
    r = es.resumo(es.carrega(data_js_com_pendencia))
    assert r["pendente"] == "2026-08-24"
    assert r["assunto"].startswith("⚠️ PETR4 incompleto")
    assert "2026-08-24" in r["assunto"]  # o que falta
    assert "2026-08-21" in r["assunto"]  # o que há
    # E o assunto não pode mais afirmar, sem ressalva, ser o pregão do dia.
    assert not r["assunto"].startswith("PETR4 R$")


def test_banner_explica_o_que_falta_e_o_que_ha(data_js_com_pendencia):
    r = es.resumo(es.carrega(data_js_com_pendencia))
    banner = r["banner_pendencia"]
    assert "não é o fechamento do último pregão" in banner
    assert "2026-08-24" in banner and "2026-08-21" in banner
    assert "nada aqui foi estimado" in banner
    assert banner.startswith("<p ") and banner.endswith("</p>")


def test_titulo_do_corpo_tambem_carrega_a_ressalva(data_js_com_pendencia):
    r = es.resumo(es.carrega(data_js_com_pendencia))
    assert r["titulo"] == "PETR4 — pregão de 2026-08-21 (a fonte ainda deve o de 2026-08-24)"


def test_valores_com_pendencia_continuam_seguros_para_github_output(data_js_com_pendencia):
    """O banner é HTML numa linha só — `$GITHUB_OUTPUT` quebra com quebra de linha."""
    for chave, valor in es.resumo(es.carrega(data_js_com_pendencia)).items():
        assert "\n" not in valor, chave
        assert "\r" not in valor, chave


def test_os_numeros_continuam_sendo_do_pregao_publicado(data_js_com_pendencia):
    """A correção é de rótulo, não de número: nada passa a ser estimado."""
    r = es.resumo(es.carrega(data_js_com_pendencia))
    assert r["last_date"] == "2026-08-21"
    assert r["last_close"] == "11.20"
    assert r["prev_close"] == "11.10"


def test_assunto_do_email_e_funcao_pura():
    """Montado em Python, e não em expressão de YAML, para poder ser testado."""
    assert es.assunto_do_email("2026-11-24", "40.55", "+1.23", "") == (
        "PETR4 R$ 40.55 (+1.23% no dia) — pregão de 2026-11-24"
    )
    assert es.assunto_do_email("2026-11-24", "40.55", "+1.23", "2026-11-25") == (
        "⚠️ PETR4 incompleto — a fonte ainda deve o pregão de 2026-11-25; "
        "o dashboard vai até 2026-11-24 (R$ 40.55)"
    )
