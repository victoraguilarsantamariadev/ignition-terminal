"""Recupera y analiza los resultados ya ejecutados de la query 8596145."""
import sys

import numpy as np
import pandas as pd
import requests
from scipy.stats import mannwhitneyu

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY = open(".dune_key").read().strip()
H = {"X-Dune-API-Key": KEY}
res = requests.get("https://api.dune.com/api/v1/query/8596145/results",
                   headers=H, timeout=60).json()
rows = res.get("result", {}).get("rows", [])
if not rows:
    print("sin resultados:", str(res)[:300])
    sys.exit(1)
df = pd.DataFrame(rows)
for c in ["buyers_ign", "buyers_prev", "vol_ign", "vol_prev"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["ratio_buyers"] = df["buyers_ign"] / df["buyers_prev"].replace(0, np.nan)
df["ratio_vol"] = df["vol_ign"] / df["vol_prev"].replace(0, np.nan)
df.to_csv("onchain_pilot.csv", index=False)

print(f"{len(df)} eventos con datos on-chain (dex.trades, BSC):\n")
cols = ["sym", "clase", "t0", "buyers_ign", "buyers_prev", "ratio_buyers", "ratio_vol"]
print(df.sort_values(["clase", "ratio_buyers"], ascending=[True, False])[cols]
      .round(2).to_string(index=False))
print("\nMedianas por clase:")
print(df.groupby("clase")[["buyers_ign", "buyers_prev", "ratio_buyers", "ratio_vol"]]
      .median().round(2).to_string())
g = df[df["clase"] == "ganadora"]["ratio_buyers"].dropna()
b = df[df["clase"] == "basura"]["ratio_buyers"].dropna()
if len(g) >= 5 and len(b) >= 5:
    print(f"\nMann-Whitney ratio_buyers ganadora vs basura: p={mannwhitneyu(g, b).pvalue:.4f}")
    gv = df[df["clase"] == "ganadora"]["ratio_vol"].dropna()
    bv = df[df["clase"] == "basura"]["ratio_vol"].dropna()
    print(f"Mann-Whitney ratio_vol: p={mannwhitneyu(gv, bv).pvalue:.4f}")
