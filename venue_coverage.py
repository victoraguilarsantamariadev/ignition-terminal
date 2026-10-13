"""Cobertura de pares de MEXC/Gate/Bitget vs el universo de senales (Binance)."""
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
bn = S.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30).json()
bn_set = {s["symbol"] for s in bn["symbols"]
          if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
          and s["status"] == "TRADING"}
print(f"Binance (fuente de senales): {len(bn_set)} perps USDT")

venues = {}
try:
    mx = S.get("https://contract.mexc.com/api/v1/contract/detail", timeout=30).json()
    venues["MEXC"] = {d["symbol"].replace("_", "") for d in mx["data"]
                      if d["symbol"].endswith("_USDT")}
except Exception as e:
    print("MEXC error:", e)
try:
    gt = S.get("https://api.gateio.ws/api/v4/futures/usdt/contracts", timeout=30).json()
    venues["Gate"] = {c["name"].replace("_", "") for c in gt
                      if c["name"].endswith("_USDT") and not c.get("in_delisting")}
except Exception as e:
    print("Gate error:", e)
try:
    bg = S.get("https://api.bitget.com/api/v2/mix/market/contracts",
               params={"productType": "usdt-futures"}, timeout=30).json()
    venues["Bitget"] = {c["symbol"] for c in bg["data"] if c["symbolStatus"] == "normal"}
except Exception as e:
    print("Bitget error:", e)

for k, v in venues.items():
    inter = len(bn_set & v)
    print(f"{k:7s}: {len(v):>5d} perps | cubre {inter}/{len(bn_set)} del universo Binance "
          f"({inter/len(bn_set):.0%}) | pares propios extra: {len(v - bn_set)}")
