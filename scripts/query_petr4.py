"""Query: consulta o banco gold e imprime análises da PETR4"""
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DB_PATH = BASE / "data" / "gold" / "petr4.db"


def query() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} não encontrado. Rode load_petr4.py antes.")

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        (dias,) = c.execute("SELECT COUNT(*) FROM cotacoes").fetchone()
        ini, fim = c.execute("SELECT MIN(date), MAX(date) FROM cotacoes").fetchone()
        (p_ini,) = c.execute("SELECT close FROM cotacoes ORDER BY date LIMIT 1").fetchone()
        (p_fim,) = c.execute("SELECT close FROM cotacoes ORDER BY date DESC LIMIT 1").fetchone()
        maxima = c.execute("SELECT date, high FROM cotacoes ORDER BY high DESC LIMIT 1").fetchone()
        minima = c.execute("SELECT date, low FROM cotacoes ORDER BY low ASC LIMIT 1").fetchone()
        (vol_medio,) = c.execute("SELECT AVG(volume) FROM cotacoes").fetchone()
        melhor = c.execute("SELECT date, var_pct FROM cotacoes ORDER BY var_pct DESC LIMIT 1").fetchone()
        pior = c.execute("SELECT date, var_pct FROM cotacoes ORDER BY var_pct ASC LIMIT 1").fetchone()

    retorno = (p_fim / p_ini - 1) * 100
    print("=" * 52)
    print("PETR4.SA — análise do período")
    print("=" * 52)
    print(f"Período:            {ini[:10]} a {fim[:10]} ({dias} pregões)")
    print(f"Fechamento inicial: R$ {p_ini:.2f}")
    print(f"Fechamento final:   R$ {p_fim:.2f}")
    print(f"Retorno no período: {retorno:+.2f}%")
    print(f"Máxima:             R$ {maxima[1]:.2f} em {maxima[0][:10]}")
    print(f"Mínima:             R$ {minima[1]:.2f} em {minima[0][:10]}")
    print(f"Volume médio/dia:   {vol_medio:,.0f}")
    print(f"Melhor dia:         {melhor[0][:10]} ({melhor[1]:+.2f}%)")
    print(f"Pior dia:           {pior[0][:10]} ({pior[1]:+.2f}%)")


if __name__ == "__main__":
    query()
