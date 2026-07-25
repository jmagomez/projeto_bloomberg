"""Atualiza data.js do dashboard: busca cotações da PETR4 no Yahoo Finance,
calcula estatísticas diárias (incluindo dividendos e JCP) e a série semanal
OHLCV desde 2010."""
import json
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data.js"

SYMBOL = "PETR4.SA"
PERIOD1 = 1262304000  # 2010-01-01
# events=div: a resposta do Yahoo passa a incluir os proventos (dividendos e
# juros sobre capital próprio) pagos por ação em cada data ex, em
# chart.result[0].events.dividends. O Yahoo não distingue dividendo de JCP:
# o valor de cada evento já é o montante líquido distribuído por ação.
URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{s}"
    "?period1={p1}&period2={p2}&interval=1d&events=div"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (dashboard-updater)"}

TENTATIVAS = 4
ESPERA_BASE = 5.0  # segundos; dobra a cada tentativa (5, 10, 20)
RETRIABLE = {429, 500, 502, 503, 504}


def fetch_daily():
    """Busca a série diária e os proventos no Yahoo Finance, com retry e
    backoff exponencial.

    O endpoint costuma responder 429 (rate limit) para IPs de runners do
    GitHub; sem retry a rotina quebraria de forma intermitente.

    Retorna (rows, dividends_by_day):
      rows              -- lista de dicts diários {d,o,h,l,c,v,e} onde "e" é
                            o provento (dividendo + JCP) por ação pago na
                            data "d" (0.0 quando não há pagamento).
      dividends_by_day   -- dict {data: valor_por_ação} com todos os
                            proventos retornados pela API (podem cair fora
                            do intervalo de "rows" caso não coincidam com um
                            pregão exato).
    """
    p2 = int(datetime.now(timezone.utc).timestamp())
    url = URL.format(s=SYMBOL, p1=PERIOD1, p2=p2)
    ultima_falha = None
    r = None
    for tentativa in range(TENTATIVAS):
        if tentativa:
            espera = ESPERA_BASE * 2 ** (tentativa - 1)
            print(f"[update] tentativa {tentativa + 1}/{TENTATIVAS} em {espera:.0f}s ({ultima_falha})")
            time.sleep(espera)
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
        except requests.RequestException as exc:
            ultima_falha = f"erro de rede: {exc}"
            continue
        if r.status_code in RETRIABLE:
            ultima_falha = f"HTTP {r.status_code}"
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError(
            f"Yahoo Finance indisponível após {TENTATIVAS} tentativas ({ultima_falha})"
        )

    res = r.json()["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]

    div_events = ((res.get("events") or {}).get("dividends")) or {}
    dividends_by_day = {}
    for ev in div_events.values():
        try:
            d = datetime.fromtimestamp(ev["date"], tz=timezone.utc).strftime("%Y-%m-%d")
            dividends_by_day[d] = round(dividends_by_day.get(d, 0.0) + float(ev["amount"]), 4)
        except (KeyError, TypeError, ValueError):
            continue

    rows = []
    for i, t in enumerate(ts):
        if q["close"][i] is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append({
            "d": d,
            "o": q["open"][i], "h": q["high"][i], "l": q["low"][i],
            "c": q["close"][i], "v": q["volume"][i] or 0,
            "e": dividends_by_day.get(d, 0.0),
        })
    return rows, dividends_by_day


def dividend_breakdown(dividends_by_day, first_date, last_date):
    """Retorna (total_periodo, total_12m, proventos_por_ano) considerando
    apenas eventos entre first_date e last_date (inclusive)."""
    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
    ttm_cutoff = (last_dt - timedelta(days=365)).strftime("%Y-%m-%d")
    total = 0.0
    ttm = 0.0
    by_year = {}
    for d, amt in dividends_by_day.items():
        if first_date <= d <= last_date:
            total += amt
            year = d[:4]
            by_year[year] = round(by_year.get(year, 0.0) + amt, 4)
        if ttm_cutoff <= d <= last_date:
            ttm += amt
    return round(total, 4), round(ttm, 4), by_year


def daily_stats(rows, dividends_by_day):
    hi = max(rows, key=lambda r: r["h"])
    lo = min(rows, key=lambda r: r["l"])
    variations = [(rows[i]["c"] / rows[i-1]["c"] - 1) * 100 for i in range(1, len(rows))]
    best_i = max(range(len(variations)), key=lambda i: variations[i])
    worst_i = min(range(len(variations)), key=lambda i: variations[i])
    first, last = rows[0], rows[-1]

    total_div, ttm_div, _ = dividend_breakdown(dividends_by_day, first["d"], last["d"])

    days_period = (datetime.strptime(last["d"], "%Y-%m-%d") - datetime.strptime(first["d"], "%Y-%m-%d")).days
    years = max(days_period / 365.25, 1 / 365.25)

    ret_price_pct = (last["c"] / first["c"] - 1) * 100
    # Retorno total no período = variação de preço + proventos (dividendos e
    # JCP) recebidos por ação, simples (sem reinvestimento).
    ret_total_pct = ((last["c"] + total_div) / first["c"] - 1) * 100
    # Anualizado (CAGR) a partir do retorno total do período.
    ret_annual_pct = (((1 + ret_total_pct / 100) ** (1 / years)) - 1) * 100
    div_yield_ttm_pct = (ttm_div / last["c"]) * 100 if last["c"] else 0.0

    return {
        "symbol": SYMBOL, "source": "Yahoo Finance",
        "days": len(rows), "first_date": first["d"], "last_date": last["d"],
        "first_close": round(first["c"], 2), "last_close": round(last["c"], 2),
        "ret_pct": round(ret_price_pct, 2),
        "total_dividends": round(total_div, 2),
        "div_yield_ttm_pct": round(div_yield_ttm_pct, 2),
        "ret_total_pct": round(ret_total_pct, 2),
        "ret_annual_pct": round(ret_annual_pct, 2),
        "years_period": round(years, 2),
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
            cur["e"] = cur.get("e", 0.0) + r.get("e", 0.0)
    if cur:
        weeks.append(cur)
    return {
        "d": [w["d"] for w in weeks],
        "o": [round(w["o"], 2) for w in weeks],
        "h": [round(w["h"], 2) for w in weeks],
        "l": [round(w["l"], 2) for w in weeks],
        "c": [round(w["c"], 2) for w in weeks],
        "v": [round(w["v"] / 1e6, 1) for w in weeks],
        # soma de proventos (dividendos + JCP) por ação pagos na semana;
        # usado para marcar os eventos no gráfico de histórico completo.
        "e": [round(w.get("e", 0.0), 4) for w in weeks],
    }


def main():
    rows, dividends_by_day = fetch_daily()
    stats = daily_stats(rows, dividends_by_day)
    _, _, div_by_year = dividend_breakdown(dividends_by_day, stats["first_date"], stats["last_date"])
    years_sorted = sorted(div_by_year.keys())

    payload = {
        "stats": stats,
        "W": weekly(rows),
        "DIV": {"y": years_sorted, "v": [div_by_year[y] for y in years_sorted]},
    }
    OUT.write_text("window.PETR4 = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")
    s = payload["stats"]
    print(
        f"[update] {s['days']} pregões até {s['last_date']} | fechamento R$ {s['last_close']} | "
        f"proventos no período R$ {s['total_dividends']}/ação | retorno total {s['ret_annual_pct']:+.2f}% a.a. | "
        "data.js atualizado"
    )


if __name__ == "__main__":
    main()
