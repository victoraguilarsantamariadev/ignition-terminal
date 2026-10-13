"""Exploracion del API de Coinalyze: exchanges, simbolos, profundidad del historico."""
import sys
import time

import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY = open(".coinalyze_key").read().strip()
S = requests.Session()
S.headers["api_key"] = KEY
BASE = "https://api.coinalyze.net/v1"

r = S.get(f"{BASE}/exchanges", timeout=20)
print("exchanges:", r.status_code)
ex = r.json()
for e in ex:
    print(" ", e)

r = S.get(f"{BASE}/future-markets", timeout=20)
mk = r.json()
print(f"\n{len(mk)} mercados de futuros")
wif = [m for m in mk if "WIF" in m.get("symbol", "")]
for m in wif[:6]:
    print(" ", m)

# profundidad de historico: OI horario de WIF en Binance desde 2023
sym = None
for m in wif:
    if m.get("base_asset") == "WIF" and m.get("is_perpetual") and m["symbol"].endswith(".A"):
        sym = m["symbol"]
        break
print("\nsimbolo elegido:", sym)
if sym:
    frm = int(pd.Timestamp("2023-09-01").timestamp())
    to = int(time.time())
    r = S.get(f"{BASE}/open-interest-history",
              params=dict(symbols=sym, interval="1hour", **{"from": frm, "to": to}), timeout=30)
    print("oi-history:", r.status_code)
    j = r.json()
    if isinstance(j, list) and j:
        hist = j[0].get("history", [])
        print(f"  puntos: {len(hist)}")
        if hist:
            print("  primero:", pd.Timestamp(hist[0]["t"], unit="s"), "ultimo:", pd.Timestamp(hist[-1]["t"], unit="s"))
    else:
        print("  respuesta:", str(j)[:300])
    r = S.get(f"{BASE}/liquidation-history",
              params=dict(symbols=sym, interval="1hour", **{"from": frm, "to": to}), timeout=30)
    print("liq-history:", r.status_code)
    j = r.json()
    if isinstance(j, list) and j:
        hist = j[0].get("history", [])
        print(f"  puntos: {len(hist)}")
        if hist:
            print("  primero:", pd.Timestamp(hist[0]["t"], unit="s"), "ultimo:", pd.Timestamp(hist[-1]["t"], unit="s"))
            print("  muestra:", hist[-2])
    else:
        print("  respuesta:", str(j)[:300])
print("\nheaders rate-limit:", {k: v for k, v in r.headers.items() if "imit" in k})
