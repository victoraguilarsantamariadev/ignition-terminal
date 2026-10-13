"""
La SANGRIA estructural: ¿es cosechable en cartera?

Estrategia testeada: corto equiponderado de las ~95 altcoins + largo de BTC por
el mismo nocional (cobertura de mercado), rebalanceo diario. PnL diario =
ret_BTC - media(ret_alts). El funding se suma con su signo REAL historico
(funding positivo = los largos pagan al corto -> viento a favor del corto).

AVISO de sesgo, y aqui va A FAVOR de la tesis del corto quedar corta: el universo
son supervivientes (las deslistadas que fueron a cero no estan) -> el resultado
real del corto seria MEJOR que lo medido. Un positivo aqui es conservador.
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

alts, fundings = {}, {}
for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    hp = pd.read_csv(f, index_col=0, parse_dates=True)
    alts[sym] = hp["c"].resample("1D").last()
    ff = f".cache_1h/{sym}_funding_1100.csv"
    if os.path.exists(ff):
        fundings[sym] = pd.read_csv(ff, index_col=0, parse_dates=True).iloc[:, 0]

btc = pd.read_csv(".cache_1h/BTCUSDT_perp_1h_1100.csv", index_col=0, parse_dates=True)
btc_d = btc["c"].resample("1D").last()

px = pd.DataFrame(alts)
rets = px.pct_change()
btc_ret = btc_d.pct_change().reindex(rets.index)
fund = pd.DataFrame(fundings).reindex(rets.index)  # tasa diaria media (ya en /dia)

# pnl diario del spread: largo BTC + corto media de alts (mismo nocional por pata)
alt_leg = rets.mean(axis=1, skipna=True)
n_alts = rets.notna().sum(axis=1)
spread = (btc_ret - alt_leg).where(n_alts >= 30)
# funding: el corto RECIBE funding positivo, paga el negativo (por pata alt)
fund_leg = fund.mean(axis=1, skipna=True).where(n_alts >= 30) * 3  # 3 periodos de 8h/dia... ya diario? ver nota
# nota: los csv de funding ya estan resampleados a MEDIA diaria de los 3 pagos de 8h
# -> el devengo diario del corto es media_diaria * 3
costes = 0.0002  # rebalanceo diario aprox (2 pb/dia sobre el nocional rotado)

df = pd.DataFrame({"spread": spread, "funding": fund_leg}).dropna()
df["total"] = df["spread"] + df["funding"] - costes
df["periodo"] = np.where(df.index < SPLIT, "A", "B")

print(f"{len(df)} dias | {px.shape[1]} alts | BTC como cobertura\n")
print(f"{'componente':22s} {'per':4s} {'medio/dia':>10s} {'anualizado':>11s}")
for comp in ["spread", "funding", "total"]:
    for p in ("A", "B"):
        s = df[df["periodo"] == p][comp]
        print(f"{comp:22s} {p:4s} {s.mean():>+9.4%} {(1+s.mean())**365-1:>+10.1%}")
print()
for p in ("A", "B"):
    s = df[df["periodo"] == p]["total"]
    eq = (1 + s).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = s.mean() / s.std() * np.sqrt(365) if s.std() > 0 else 0
    peor = s.min()
    print(f"periodo {p}: total {(eq.iloc[-1]-1):+.1%} acumulado | maxDD {dd:+.1%} | "
          f"Sharpe {sharpe:.2f} | peor dia {peor:+.2%}")
# los peores meses (alt-season = veneno para este spread)
m = df["total"].resample("ME").sum().sort_values()
print("\npeores meses:", ", ".join(f"{i:%Y-%m} {v:+.1%}" for i, v in m.head(4).items()))
print("mejores meses:", ", ".join(f"{i:%Y-%m} {v:+.1%}" for i, v in m.tail(3).items()))
