"""¿En que punto del camino hacia el 25% de TPs (+40%) estamos con cada capa?"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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
ld = {k: pd.Timestamp(v, unit="ms") for k, v in json.load(open("listing_dates.json")).items()}
ev["edad_d"] = [(t - ld.get(s, pd.Timestamp("2000-01-01"))).days for s, t in zip(ev["symbol"], ev["t"])]
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")

capas = [
    ("sin filtros", np.ones(len(ev), bool)),
    ("+ calor>=1", (ev["calor"] >= 1).to_numpy()),
    ("+ sin gigantes", ((ev["calor"] >= 1) & (ev["liq_d"] < 100e6)).to_numpy()),
    ("+ sin <90d (cand.)", ((ev["calor"] >= 1) & (ev["liq_d"] < 100e6) & (ev["edad_d"] >= 90)).to_numpy()),
]
print(f"{'capa':22s} {'per':4s} {'n':>5s} {'p(TP+40%)':>10s} {'exp':>7s}")
for name, mask in capas:
    rows = {"A": [], "B": []}
    for k in np.flatnonzero(mask):
        e = ev.iloc[k]
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows[e["periodo"]].append(r)
    for p in ("A", "B"):
        rr = rows[p]
        if len(rr) < 20:
            continue
        rets = np.array([x[0] for x in rr])
        hits = [x[2] for x in rr]
        print(f"{name:22s} {p:4s} {len(rr):>5d} {hits.count('tp')/len(hits):>9.1%} {rets.mean():>+6.2%}")
