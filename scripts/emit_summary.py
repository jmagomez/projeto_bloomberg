"""Extrai do data.js o resumo usado no e-mail diário da rotina.

Escreve pares ``chave=valor`` em stdout, no formato que o GitHub Actions espera
em ``$GITHUB_OUTPUT``. Ficava embutido como heredoc no YAML do workflow, onde
não era testável nem passava pelo lint.

**O assunto e o título do e-mail são montados aqui, não no YAML.** O motivo é o
incidente de 26/11/2026: a fonte devia o pregão de 25/11, entregou a série até
24/11, e a rotina publicou esse avanço parcial — corretamente, porque é melhor
avançar do que ficar parado, e o dashboard sinaliza a pendência. O e-mail, que
não sabia nada disso, saiu com o assunto "pregão de 2026-11-24" numa noite em
que o pregão do dia era 25/11. Chegando de madrugada, com a cotação em
destaque, ele se lê como "o fechamento de ontem" — e era o de dois dias antes.

O número nunca esteve errado, e a data sempre esteve no assunto. O que faltava
era o e-mail **saber** que não estava carregando o último pregão. Montar o
assunto em Python, e não em expressão de YAML, é o que torna isso testável:
há teste para os dois estados.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DATA_JS = BASE / "data.js"
PREFIXO = "window.PETR4 = "


def carrega(caminho: Path = DATA_JS) -> dict:
    texto = caminho.read_text(encoding="utf-8").strip()
    if not texto.startswith(PREFIXO):
        raise ValueError(f"{caminho} não começa com {PREFIXO!r}")
    return json.loads(texto[len(PREFIXO) :].rstrip(";\n"))


# O aviso vai em uma linha só: `$GITHUB_OUTPUT` usa `chave=valor` por linha e
# quebra com qualquer `\n` no valor. Há teste cobrindo isso para todos os campos.
BANNER_PENDENCIA = (
    '<p style="margin:0 0 16px;padding:12px;border-left:4px solid #bf8700;'
    'background:#fff8c5;color:#4d2d00;font-size:14px">'
    "<strong>Este não é o fechamento do último pregão.</strong> "
    "A fonte informa que o pregão de {pendente} já fechou e não o entregou. "
    "Os números abaixo são os do pregão de {publicado}, o último íntegro que ela "
    "serviu. A próxima rodada publica o que faltar; nada aqui foi estimado."
    "</p>"
)


def assunto_do_email(publicado: str, fechamento: str, variacao: str, pendente: str) -> str:
    """O assunto, com a ressalva **na frente** quando há pendência.

    Na frente de propósito: notificação de celular mostra o começo do assunto, e
    é exatamente aí que "PETR4 R$ 40,55" seguido de uma data antiga engana.
    """
    if pendente:
        return (
            f"⚠️ PETR4 incompleto — a fonte ainda deve o pregão de {pendente}; "
            f"o dashboard vai até {publicado} (R$ {fechamento})"
        )
    return f"PETR4 R$ {fechamento} ({variacao}% no dia) — pregão de {publicado}"


def resumo(payload: dict) -> dict[str, str]:
    s = payload["stats"]
    fechamentos = payload["W"]["c"]
    var_semana = (fechamentos[-1] / fechamentos[-2] - 1) * 100 if len(fechamentos) > 1 else 0.0

    publicado = s["last_date"]
    pendente = s.get("pending_session") or ""
    fechamento = f"{s['last_close']:.2f}"
    variacao = f"{s['day_change_pct']:+.2f}"

    return {
        "pendente": pendente,
        "assunto": assunto_do_email(publicado, fechamento, variacao, pendente),
        "titulo": (
            f"PETR4 — pregão de {publicado} (a fonte ainda deve o de {pendente})"
            if pendente
            else f"PETR4 — pregão de {publicado}"
        ),
        "banner_pendencia": (
            BANNER_PENDENCIA.format(pendente=pendente, publicado=publicado) if pendente else ""
        ),
        "last_date": s["last_date"],
        "last_close": fechamento,
        "prev_close": f"{s['prev_close']:.2f}",
        "var_dia": variacao,
        "seta_dia": "▲" if s["day_change_pct"] >= 0 else "▼",
        "cor_dia": "#1a7f37" if s["day_change_pct"] >= 0 else "#cf222e",
        "day_open": f"{s['day_open']:.2f}",
        "day_high": f"{s['day_high']:.2f}",
        "day_low": f"{s['day_low']:.2f}",
        "day_volume": f"{s['day_volume_M']:.1f}",
        "var_semana": f"{var_semana:+.2f}",
        "max_high": f"{s['max_high']:.2f}",
        "min_low": f"{s['min_low']:.2f}",
        "ret_pct": f"{s['ret_pct']:+.2f}",
        "ret_annual": f"{s['ret_annual_pct']:+.2f}",
        "div_yield": f"{s['div_yield_ttm_pct']:.2f}",
        "days": str(s["days"]),
    }


def main() -> int:
    for chave, valor in resumo(carrega()).items():
        print(f"{chave}={valor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
