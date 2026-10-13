"""
Enriquece senales_log.csv al esquema completo: edad, bvx, gvx, mvx.
La amplitud se calcula EN EL MOMENTO de la senal (velas historicas de cada
exchange hasta t0), no con el dato de hoy — sin trampas retrospectivas.
"""
import csv
import json
import os
import sys
import time

import pandas as pd
import requests

from ignition_scan import _volx_from

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()


def bybit_at(sym, t0ms):
    try:
        r = S.get("https://api.bybit.com/v5/market/kline",
                  params=dict(category="linear", symbol=sym, interval="60",
                              start=t0ms - 31 * 86400000, end=t0ms, limit=1000), timeout=15)
        rows = r.json().get("result", {}).get("list") or []
        return _volx_from([float(x[6]) for x in rows][::-1])
    except Exception:
        return None


def gate_at(sym, t0ms):
    try:
        r = S.get("https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
                  params={"contract": sym.replace("USDT", "_USDT"), "interval": "1h",
                          "from": t0ms // 1000 - 31 * 86400, "to": t0ms // 1000}, timeout=15)
        rows = r.json()
        return _volx_from([float(x.get("v", 0)) for x in rows]) if isinstance(rows, list) else None
    except Exception:
        return None


def mexc_at(sym, t0ms):
    try:
        r = S.get(f"https://contract.mexc.com/api/v1/contract/kline/{sym.replace('USDT','_USDT')}",
                  params=dict(interval="Min60", start=t0ms // 1000 - 31 * 86400,
                              end=t0ms // 1000), timeout=15)
        d = r.json().get("data") or {}
        return _volx_from(d.get("vol") or [])
    except Exception:
        return None


HEADER = ["symbol", "hora", "px_deteccion", "stop_estruct", "delta",
          "liq_d", "print_ratio", "tipo", "edad", "bvx", "gvx", "mvx"]

with open("senales_log.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
ld = json.load(open("listing_dates.json"))
out = []
for n, r in enumerate(rows, 1):
    h = pd.Timestamp(r["hora"])
    t0ms = int(h.timestamp() * 1000)
    if not r.get("edad"):
        r["edad"] = int((h - pd.Timestamp(ld[r["symbol"]], unit="ms")).days) \
            if r["symbol"] in ld else ""
    if not r.get("bvx"):
        for k, fn in (("bvx", bybit_at), ("gvx", gate_at), ("mvx", mexc_at)):
            v = fn(r["symbol"], t0ms)
            r[k] = round(v, 1) if v else ""
            time.sleep(0.1)
        print(f"[{n}/{len(rows)}] {r['symbol']} {r['hora'][:16]}: "
              f"byb={r['bvx']} gate={r['gvx']} mexc={r['mvx']}", file=sys.stderr, flush=True)
    out.append({k: r.get(k, "") for k in HEADER})

with open("senales_log.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=HEADER)
    w.writeheader()
    w.writerows(out)
print(f"{len(out)} senales migradas al esquema completo")
