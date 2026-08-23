"""Extrai do data.js o resumo usado no e-mail diário da rotina.

Escreve pares ``chave=valor`` em stdout, no formato que o GitHub Actions espera
em ``$GITHUB_OUTPUT``. Ficava embutido como heredoc no YAML do workflow, onde
não era testável nem passava pelo lint.
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


def resumo(payload: dict) -> dict[str, str]:
    s = payload["stats"]
    fechamentos = payload["W"]["c"]
    var_semana = (fechamentos[-1] / fechamentos[-2] - 1) * 100 if len(fechamentos) > 1 else 0.0

    return {
        "last_date": s["last_date"],
        "last_close": f"{s['last_close']:.2f}",
        "prev_close": f"{s['prev_close']:.2f}",
        "var_dia": f"{s['day_change_pct']:+.2f}",
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
