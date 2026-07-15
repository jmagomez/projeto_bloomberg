"""Load: carrega o CSV tratado no banco SQLite -> data/gold/petr4.db"""
import sqlite3
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
SILVER_CSV = BASE / "data" / "silver" / "petr4_silver.csv"
GOLD_DIR = BASE / "data" / "gold"
DB_PATH = GOLD_DIR / "petr4.db"


def load() -> Path:
    if not SILVER_CSV.exists():
        raise SystemExit(f"{SILVER_CSV} não encontrado. Rode transform_petr4.py antes.")

    df = pd.read_csv(SILVER_CSV, parse_dates=["date"])
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("cotacoes", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cotacoes_date ON cotacoes(date)")
        n = conn.execute("SELECT COUNT(*) FROM cotacoes").fetchone()[0]

    print(f"[load] {n} registros carregados na tabela 'cotacoes' -> {DB_PATH}")
    return DB_PATH


if __name__ == "__main__":
    load()
