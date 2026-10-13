"""Examen de ascenso del filtro de liquidez (excluir pares gigantes >100M$/dia)
a nivel de trade real (stop 8%, TP 40%, fees), por periodo."""
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

liq_map = {}
for e in events:
    hp = frames[e["symbol"]]
    i = e["i"]
    liq_map[(e["symbol"], pd.Timestamp(e["t"]))] = \
        hp.iloc[max(0, i - 720):i]["qv"].resample("1D").sum().median()

print(f"{'filtro':28s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
for fname, lo, hi in [("todos", 0, np.inf),
                      ("sin gigantes (<100M$/d)", 0, 100e6),
                      ("medianos (5-100M$/d)", 5e6, 100e6),
                      ("solo gigantes (>100M$/d)", 100e6, np.inf)]:
    rows = {"A": [], "B": []}
    for e in events:
        liq = liq_map.get((e["symbol"], pd.Timestamp(e["t"])))
        if liq is None or not (lo <= liq < hi):
            continue
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows["A" if e["t"] < SPLIT else "B"].append(r[0])
    for p in ("A", "B"):
        rr = np.array(rows[p])
        if len(rr) < 25:
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        print(f"{fname:28s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")
