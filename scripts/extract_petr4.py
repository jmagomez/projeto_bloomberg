"""Extract: baixa cotações diárias da PETR4 na API Alpha Vantage -> data/raw/*.json"""
import json
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parents[1]
RAW_DIR = BASE / "data" / "raw"

SYMBOL = "PETR4.SA"
URL = "https://www.alphavantage.co/query"


def extract() -> Path:
    load_dotenv(BASE / ".env")
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key or api_key == "SUA_CHAVE_AQUI":
        raise SystemExit(
            "ALPHA_VANTAGE_API_KEY não configurada. Copie .env.example para .env "
            "e preencha sua chave (https://www.alphavantage.co/support/#api-key)."
        )

    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": SYMBOL,
        "outputsize": "compact",
        "apikey": api_key,
    }
    resp = requests.get(URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "Time Series (Daily)" not in data:
        raise SystemExit(f"Resposta inesperada da API: {data}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"{SYMBOL}_{date.today().isoformat()}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[extract] {len(data['Time Series (Daily)'])} pregões salvos em {out}")
    return out


if __name__ == "__main__":
    extract()
