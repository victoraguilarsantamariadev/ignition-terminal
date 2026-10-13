"""¿El filtro de delta (calidad de la chispa) es estable entre periodos?"""
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ev = pd.read_csv("ignitions.csv", parse_dates=["t"])
ev["periodo"] = np.where(ev["t"] < pd.Timestamp("2025-07-30"), "A(23-25)", "B(25-26)")
ev["grupo"] = pd.cut(ev["delta_share"], [-np.inf, -0.01, 0.03, np.inf],
                     labels=["hueca (<-0.01)", "mixta", "compra agresiva (>0.03)"])

print(f"{'periodo':9s} {'grupo':26s} {'n':>5s} {'P(+25%)':>8s} {'fwd_ret':>8s} {'mediana':>8s}")
for (p, g), sub in ev.groupby(["periodo", "grupo"], observed=True):
    if len(sub) < 20:
        continue
    print(f"{p:9s} {str(g):26s} {len(sub):>5d} {(sub['fwd_max']>=0.25).mean():>7.1%} "
          f"{sub['fwd_ret'].mean():>+7.2%} {sub['fwd_ret'].median():>+7.2%}")

print("\nY el filtro binario delta>=+0.03 vs resto:")
for p, sub in ev.groupby("periodo"):
    hi = sub[sub["delta_share"] >= 0.03]
    lo = sub[sub["delta_share"] < 0.03]
    print(f"  {p}: con filtro n={len(hi):>4d} fwd_ret {hi['fwd_ret'].mean():+.2%} "
          f"P(+25%)={(hi['fwd_max']>=0.25).mean():.1%}  |  "
          f"sin pasar n={len(lo):>4d} fwd_ret {lo['fwd_ret'].mean():+.2%} "
          f"P(+25%)={(lo['fwd_max']>=0.25).mean():.1%}")
