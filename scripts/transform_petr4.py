"""Transform: limpa e padroniza o JSON bruto -> data/silver/petr4_silver.csv"""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
RAW_DIR = BASE / "data" / "raw"
SILVER_DIR = BASE / "data" / "silver"

COLMAP = {
    "1. open": "open",
    "2. high": "high",
    "3. low": "low",
    "4. close": "close",
    "5. volume": "volume",
}


def latest_raw() -> Path:
    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"Nenhum JSON bruto encontrado em {RAW_DIR}. Rode extract_petr4.py antes.")
    return files[-1]


def transform() -> Path:
    src = latest_raw()
    raw = json.loads(src.read_text(encoding="utf-8"))
    ts = raw["Time Series (Daily)"]

    df = pd.DataFrame.from_dict(ts, orient="index").rename(columns=COLMAP)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": int})

    # variação percentual diária do fechamento
    df["var_pct"] = (df["close"].pct_change() * 100).round(2).fillna(0.0)
    df.index.name = "date"

    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    out = SILVER_DIR / "petr4_silver.csv"
    df.to_csv(out)
    print(f"[transform] {len(df)} pregões tratados ({df.index.min().date()} a {df.index.max().date()}) -> {out}")
    return out


if __name__ == "__main__":
    transform()
