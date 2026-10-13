"""Revision del lote de papel del escaneo 2026-09-03 10:26 UTC."""
import sys
import time

import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
# symbol, precio en el momento del escaneo, stop estructural sugerido
LOTE = [
    ("XVGUSDT", 0.002572, 0.00247302), ("COLLECTUSDT", 0.08001, 0.0731907),
    ("SOMIUSDT", 0.1098, 0.099396), ("ARUSDT", 2.537, 2.23443),
    ("ANKRUSDT", 0.004288, 0.00388674), ("HIVEUSDT", 0.04586, 0.0431442),
    ("AKEUSDT", 0.012927, 0.007524), ("MUBARAKUSDT", 0.0277, 0.021285),
    ("BRUSDT", 0.29018, 0.226423), ("EDGEUSDT", 0.5087, 0.377883),
    ("ZESTUSDT", 0.14822, 0.12573),
]
T0 = int(pd.Timestamp("2026-09-03 10:00:00", tz="UTC").timestamp() * 1000)

print(f"{'par':14s} {'entrada':>10s} {'ahora':>10s} {'cambio':>8s} {'max':>8s} {'min':>8s} {'stop?':>6s}")
for sym, entry, stop in LOTE:
    k = S.get("https://fapi.binance.com/fapi/v1/klines",
              params=dict(symbol=sym, interval="1h", startTime=T0, limit=200), timeout=20).json()
    df = pd.DataFrame(k, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"])
    hi = df["h"].astype(float).max()
    lo = df["l"].astype(float).min()
    now = float(df["c"].astype(float).iloc[-1])
    hit = "STOP" if lo <= stop else ""
    print(f"{sym:14s} {entry:>10.6g} {now:>10.6g} {now/entry-1:>+7.1%} {hi/entry-1:>+7.1%} {lo/entry-1:>+7.1%} {hit:>6s}")
    time.sleep(0.1)
print("\nhora actual:", pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"))
