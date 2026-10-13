"""
CASH-AND-CARRY (el trade real de los fondos): largo spot + corto perp de la
MISMA moneda -> el precio se cancela, se cobra el funding.

Backtest: cada dia, cartera de los TOP-N pares por funding trailing 7d (>0),
equiponderada. Retorno diario = funding real devengado (media diaria x3)
- costes de rotacion (0.15% por cambio de componente, ida+vuelta ambas patas).
Sin pata de precio: el unico riesgo del backtest es que el funding se gire.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SPLIT = pd.Timestamp("2025-07-30")
TOP_N = 10
COST_SWAP = 0.0015  # 0.15% por sustituir un componente (4 ordenes)

fundings = {}
for f in sorted(glob.glob(".cache_1h/*_funding_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    s = pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
    fundings[sym] = s
fund = pd.DataFrame(fundings) * 3  # devengo DIARIO (los csv son media de los 3 pagos)

trail = fund.rolling(7, min_periods=4).mean().shift(1)  # decision con datos de ayer
pnl, turnover = [], []
prev = set()
for t in fund.index[10:]:
    row = trail.loc[t].dropna()
    row = row[row > 0].nlargest(TOP_N)
    sel = set(row.index)
    if len(sel) < 5:
        pnl.append((t, 0.0))
        prev = sel
        continue
    earned = fund.loc[t, list(sel)].mean()
    swaps = len(sel - prev)
    cost = swaps / max(len(sel), 1) * COST_SWAP
    pnl.append((t, earned - cost))
    turnover.append(swaps)
    prev = sel

df = pd.DataFrame(pnl, columns=["t", "r"]).set_index("t")
df["periodo"] = np.where(df.index < SPLIT, "A", "B")
print(f"cartera: top-{TOP_N} por funding trailing | rotacion media {np.mean(turnover):.1f} cambios/dia\n")
for p in ("A", "B"):
    s = df[df["periodo"] == p]["r"]
    eq = (1 + s).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sh = s.mean() / s.std() * np.sqrt(365) if s.std() > 0 else 0
    neg = (s < 0).mean()
    print(f"{p}: {(eq.iloc[-1]-1):+.1%} acumulado ({(1+s.mean())**365-1:+.1%} anualizado) | "
          f"maxDD {dd:+.2%} | Sharpe {sh:.1f} | dias negativos {neg:.0%}")
m = df["r"].resample("ME").sum()
print(f"\npeor mes: {m.idxmin():%Y-%m} {m.min():+.2%} | mejor: {m.idxmax():%Y-%m} {m.max():+.2%}")
print("\nAvisos: requiere que exista spot para la pata larga (no siempre, aprox);")
print("capital en DOS patas (retorno sobre capital total = la mitad del mostrado);")
print("riesgo real no modelado: gap entre patas en crashes y funding girandose intradia.")
