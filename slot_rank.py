"""
Seleccion de cartera: dias con mas senales elegibles (calor+sin gigantes) que
slots (3). ¿Que criterio de priorizacion rinde mas?
  azar        : media de todas las elegibles del dia (esperanza del random)
  delta       : mayor delta agresor de la ignicion
  chispa      : mayor ret de ignicion
  volx        : mayor multiplo de volumen
  liq_baja    : menor liquidez del par
  bybit_amplio: mayor expansion de volumen en Bybit
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SLOTS = 3

frames, events = {}, []
for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    hp = load(f)
    if hp is None:
        continue
    frames[sym] = hp
    events += detect(hp, sym)
ev = pd.DataFrame(events)
ev["t"] = pd.to_datetime(ev["t"])
ev = ev.sort_values("t").reset_index(drop=True)
times = ev["t"]
ev["calor"] = [((times >= t - pd.Timedelta(hours=24)) & (times < t)).sum() for t in times]
liq = []
for _, e in ev.iterrows():
    hp = frames[e["symbol"]]
    liq.append(hp.iloc[max(0, e["i"] - 720):e["i"]]["qv"].resample("1D").sum().median())
ev["liq_d"] = liq
try:
    bb = pd.read_csv("ignitions_bybit.csv", parse_dates=["t"])
    ev = ev.merge(bb[["symbol", "t", "volx_bybit"]], on=["symbol", "t"], how="left")
except Exception:
    ev["volx_bybit"] = np.nan

ev = ev[(ev["calor"] >= 1) & (ev["liq_d"] < 100e6)].copy()
rets = []
for _, e in ev.iterrows():
    r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
    rets.append(r[0] if r else np.nan)
ev["ret"] = rets
ev = ev.dropna(subset=["ret"])
ev["dia"] = ev["t"].dt.date
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")

crit = {
    "azar (media del dia)": None,
    "delta desc": ("delta_share", False),
    "chispa desc": ("ign_ret", False),
    "volx desc": ("volx", False),
    "liq asc": ("liq_d", True),
    "bybit_volx desc": ("volx_bybit", False),
}
days = ev.groupby("dia").filter(lambda g: len(g) > SLOTS)
n_days = days["dia"].nunique()
print(f"dias con >{SLOTS} senales elegibles: {n_days} "
      f"({len(days)} senales implicadas)\n")
print(f"{'criterio':22s} {'per':4s} {'exp/trade elegido':>18s}")
for name, c in crit.items():
    for p in ("A", "B"):
        sel = []
        for _, g in days[days["periodo"] == p].groupby("dia"):
            if c is None:
                sel.append(g["ret"].mean())
            else:
                col, asc = c
                gg = g.dropna(subset=[col])
                if len(gg) < SLOTS:
                    gg = g
                pick = gg.sort_values(col, ascending=asc).head(SLOTS)
                sel.append(pick["ret"].mean())
        if len(sel) < 8:
            continue
        print(f"{name:22s} {p:4s} {np.mean(sel):>+17.2%}")
