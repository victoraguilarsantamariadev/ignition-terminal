"""Simulacion de trades (stop/TP reales) con y sin filtro delta>=+0.03, por periodo."""
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
print(f"{len(events)} igniciones", file=sys.stderr, flush=True)

print(f"{'config':22s} {'filtro':10s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
for stop_kind, tp in [(0.08, 0.40), ("estructural", 0.40), (0.08, None)]:
    for fname, cond in [("todos", lambda e: True), ("delta>=.03", lambda e: e["delta_share"] >= 0.03)]:
        rows = {"A": [], "B": []}
        for e in events:
            if not cond(e):
                continue
            r = simulate(frames[e["symbol"]], e, stop_kind, tp)
            if r:
                rows["A" if e["t"] < SPLIT else "B"].append(r)
        for p in ("A", "B"):
            rr = rows[p]
            if len(rr) < 15:
                continue
            rets = np.array([x[0] for x in rr])
            wins, losses = rets[rets > 0], rets[rets <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            sk = f"{stop_kind:.0%}" if isinstance(stop_kind, float) else stop_kind
            tk = f"TP{tp:.0%}" if tp else "sin TP"
            print(f"{sk+' / '+tk:22s} {fname:10s} {p:4s} {len(rets):>5d} "
                  f"{rets.mean():>+6.2%} {(rets>0).mean():>5.1%} {pf:>5.2f}")
