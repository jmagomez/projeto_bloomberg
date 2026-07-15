"""Atualiza data.js do dashboard: busca cotações da PETR4 no Yahoo Finance,
calcula estatísticas diárias e a série semanal OHLCV desde 2010."""
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data.js"

SYMBOL = "PETR4.SA"
PERIOD1 = 1262304000  # 2010-01-01
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1={p1}&period2={p2}&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0 (dashboard-updater)"}


def fetch_daily():
    p2 = int(datetime.now(timezone.utc).timestamp())
    r = requests.get(URL.format(s=SYMBOL, p1=PERIOD1, p2=p2), headers=HEADERS, timeout=60)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        if q["close"][i] is None:
            continue
        rows.append({
            "d": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
            "o": q["open"][i], "h": q["high"][i], "l": q["low"][i],
            "c": q["close"][i], "v": q["volume"][i] or 0,
        })
    return rows


def daily_stats(rows):
    hi = max(rows, key=lambda r: r["h"])
    lo = min(rows, key=lambda r: r["l"])
    variations = [(rows[i]["c"] / rows[i-1]["c"] - 1) * 100 for i in range(1, len(rows))]
    best_i = max(range(len(variations)), key=lambda i: variations[i])
    worst_i = min(range(len(variations)), key=lambda i: variations[i])
    first, last = rows[0], rows[-1]
    return {
        "symbol": SYMBOL, "source": "Yahoo Finance",
        "days": len(rows), "first_date": first["d"], "last_date": last["d"],
        "first_close": round(first["c"], 2), "last_close": round(last["c"], 2),
        "ret_pct": round((last["c"] / first["c"] - 1) * 100, 2),
        "max_high": round(hi["h"], 2), "max_high_date": hi["d"],
        "min_low": round(lo["l"], 2), "min_low_date": lo["d"],
        "vol_pct": round(statistics.stdev(variations), 2),
        "avg_vol_M": round(sum(r["v"] for r in rows) / len(rows) / 1e6, 1),
        "best_day": rows[best_i + 1]["d"], "best_pct": round(variations[best_i], 2),
        "worst_day": rows[worst_i + 1]["d"], "worst_pct": round(variations[worst_i], 2),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def weekly(rows):
    weeks, cur, key0 = [], None, None
    for r in rows:
        epoch_days = datetime.strptime(r["d"], "%Y-%m-%d").timestamp() / 86400
        key = int((epoch_days + 4) // 7)
        if cur is None or key != key0:
            if cur:
                weeks.append(cur)
            cur, key0 = dict(r), key
        else:
            cur["d"] = r["d"]
            cur["h"] = max(cur["h"], r["h"])
            cur["l"] = min(cur["l"], r["l"])
            cur["c"] = r["c"]
            cur["v"] += r["v"]
    if cur:
        weeks.append(cur)
    return {
        "d": [w["d"] for w in weeks],
        "o": [round(w["o"], 2) for w in weeks],
        "h": [round(w["h"], 2) for w in weeks],
        "l": [round(w["l"], 2) for w in weeks],
        "c": [round(w["c"], 2) for w in weeks],
        "v": [round(w["v"] / 1e6, 1) for w in weeks],
    }


def main():
    rows = fetch_daily()
    payload = {"stats": daily_stats(rows), "W": weekly(rows)}
    OUT.write_text("window.PETR4 = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")
    s = payload["stats"]
    print(f"[update] {s['days']} pregões até {s['last_date']} | fechamento R$ {s['last_close']} | data.js atualizado")


if __name__ == "__main__":
    main()
