"""Examen de ascenso del filtro 'calor de mercado' (>=2 igniciones el mismo dia)
al nivel de trade real (stop 8%, TP 40%, 7d, fees)."""
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

frames, events = {}, []
for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    hp = load(f)
    if hp is None:
        continue
    frames[sym] = hp
    events += detect(hp, sym)

ev = pd.DataFrame(events)
ev["dia"] = pd.to_datetime(ev["t"]).dt.date
ev["n_dia"] = ev.groupby("dia")["symbol"].transform("count")
# OJO anti-lookahead: n_dia cuenta igniciones de TODO el dia; en vivo, al entrar
# a las 10:00 no sabes si a las 20:00 habra otra. Version causal: igniciones en
# las 24h ANTERIORES al disparo.
ev = ev.sort_values("t").reset_index(drop=True)
times = pd.to_datetime(ev["t"])
n_prev = []
for k, t in enumerate(times):
    n_prev.append(((times >= t - pd.Timedelta(hours=24)) & (times < t)).sum())
ev["calor_causal"] = np.array(n_prev)

print(f"{'filtro':26s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
for fname, mask in [("todos", np.ones(len(ev), bool)),
                    ("calor causal >=1 en 24h", (ev["calor_causal"] >= 1).to_numpy()),
                    ("calor causal >=3 en 24h", (ev["calor_causal"] >= 3).to_numpy()),
                    ("solitaria (0 en 24h)", (ev["calor_causal"] == 0).to_numpy())]:
    rows = {"A": [], "B": []}
    for k in np.flatnonzero(mask):
        e = ev.iloc[k]
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows["A" if e["t"] < SPLIT else "B"].append(r[0])
    for p in ("A", "B"):
        rr = np.array(rows[p])
        if len(rr) < 25:
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        print(f"{fname:26s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")
