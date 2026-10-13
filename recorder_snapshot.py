"""
Grabadora horaria de posicionamiento — ~500 perpetuos USDT de Binance.
Cada ejecucion anade una foto a los CSV del dia en ./recorder/:
  funding_YYYY-MM-DD.csv : mark, index, funding rate (1 llamada bulk)
  book_YYYY-MM-DD.csv    : mejor bid/ask (spread) (1 llamada bulk)
  oi_YYYY-MM-DD.csv      : open interest por simbolo
  ratios_YYYY-MM-DD.csv  : top traders (cuentas y posiciones) y taker buy/sell
Pensada para el Programador de tareas de Windows, cada hora. ~6 min/ejecucion.
"""
import csv
import os
import sys
import time

import requests

FAPI = "https://fapi.binance.com"
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorder")
os.makedirs(DIR, exist_ok=True)
S = requests.Session()


def get(url, **params):
    for _ in range(4):
        try:
            r = S.get(url, params=params, timeout=20)
        except requests.RequestException:
            time.sleep(3)
            continue
        if r.status_code in (418, 429):
            time.sleep(int(r.headers.get("Retry-After", 15)) + 1)
            continue
        if r.status_code != 200:
            return None
        return r.json()
    return None


def append(fname, header, rows):
    path = os.path.join(DIR, fname)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerows(rows)


def main():
    ts = int(time.time())
    day = time.strftime("%Y-%m-%d", time.gmtime(ts))

    info = get(FAPI + "/fapi/v1/exchangeInfo")
    if not info:
        sys.exit(1)
    syms = sorted(s["symbol"] for s in info["symbols"]
                  if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
                  and s["status"] == "TRADING")

    prem = get(FAPI + "/fapi/v1/premiumIndex") or []
    rows = [(ts, p["symbol"], p["markPrice"], p["indexPrice"], p["lastFundingRate"])
            for p in prem if p["symbol"] in set(syms)]
    append(f"funding_{day}.csv", ["ts", "symbol", "mark", "index", "funding"], rows)

    book = get(FAPI + "/fapi/v1/ticker/bookTicker") or []
    rows = [(ts, b["symbol"], b["bidPrice"], b["bidQty"], b["askPrice"], b["askQty"])
            for b in book if b["symbol"] in set(syms)]
    append(f"book_{day}.csv", ["ts", "symbol", "bid", "bid_qty", "ask", "ask_qty"], rows)

    oi_rows, ratio_rows = [], []
    for sym in syms:
        oi = get(FAPI + "/fapi/v1/openInterest", symbol=sym)
        if oi:
            oi_rows.append((ts, sym, oi["openInterest"]))
        ta = get(FAPI + "/futures/data/topLongShortAccountRatio", symbol=sym, period="1h", limit=1)
        tp = get(FAPI + "/futures/data/topLongShortPositionRatio", symbol=sym, period="1h", limit=1)
        tk = get(FAPI + "/futures/data/takerlongshortRatio", symbol=sym, period="1h", limit=1)
        ratio_rows.append((ts, sym,
                           ta[0]["longShortRatio"] if ta else "",
                           tp[0]["longShortRatio"] if tp else "",
                           tk[0]["buySellRatio"] if tk else ""))
        time.sleep(0.04)
    append(f"oi_{day}.csv", ["ts", "symbol", "oi"], oi_rows)
    append(f"ratios_{day}.csv", ["ts", "symbol", "top_acc_ls", "top_pos_ls", "taker_bs"], ratio_rows)
    print(f"snapshot {day} ts={ts}: {len(oi_rows)} OI, {len(ratio_rows)} ratios")


if __name__ == "__main__":
    main()
