"""
Test 62 (pre-registrado): FADE de las igniciones MALAS — cortar lo que el
sistema largo descarta (solitarias: sin otra ignicion en 24h; gigantes:
liq>100M$/d). Corto al open siguiente, stop = maximo de la ignicion +2%,
TP -15%, 7 dias, fees 0.3%. Split A/B y por sub-clase.
Prediccion: <=0 por ejecuciones de cola; si algo vive, gigantes en B.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

from momentum_ignition import detect, load, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEE = 0.003
HOLD = 168

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
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
ev["solitaria"] = ev["calor"] == 0
ev["gigante"] = ev["liq_d"] > 100e6
malas = ev[ev["solitaria"] | ev["gigante"]]
print(f"{len(malas)} igniciones malas (solitarias: {malas['solitaria'].sum()}, "
      f"gigantes: {malas['gigante'].sum()})\n")


def sim_fade(hp, e):
    i = e["i"]
    entry = hp.iloc[i + 1]["o"]
    stop = hp.iloc[i - 5:i + 1]["h"].max() * 1.02
    risk = stop / entry - 1
    if risk <= 0.01 or risk > 0.35:
        return None
    tp = entry * 0.85
    win = hp.iloc[i + 1:i + 1 + HOLD]
    for _, r in win.iterrows():
        if r["h"] >= stop:
            return -(stop / entry - 1) - FEE, risk
        if r["l"] <= tp:
            return 0.15 - FEE, risk
    return -(win.iloc[-1]["c"] / entry - 1) - FEE, risk


print(f"{'clase':22s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s} {'R medio':>8s}")
for cname, cmask in [("todas las malas", malas.index),
                     ("solo solitarias", malas[malas["solitaria"]].index),
                     ("solo gigantes", malas[malas["gigante"]].index)]:
    rows = {"A": [], "B": []}
    for k in cmask:
        e = ev.loc[k]
        r = sim_fade(frames[e["symbol"]], e)
        if r:
            rows[e["periodo"]].append(r)
    for p in ("A", "B"):
        rr = rows[p]
        if len(rr) < 15:
            print(f"{cname:22s} {p:4s} {len(rr):>5d}   (corta)")
            continue
        rets = np.array([x[0] for x in rr])
        rmul = rets / np.array([x[1] for x in rr])
        w, l = rets[rets > 0], rets[rets <= 0]
        pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else np.inf
        print(f"{cname:22s} {p:4s} {len(rets):>5d} {rets.mean():>+6.2%} "
              f"{(rets>0).mean():>5.1%} {pf:>5.2f} {rmul.mean():>+7.2f}")
