"""Examen de ascenso de la categoria MEME: trade real, sola y apilada al sistema."""
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
ev["base"] = (ev["symbol"].str.replace("USDT", "", regex=False)
              .str.replace(r"^1000+", "", regex=True).str.lower())
cats = json.load(open("categorias.json"))
ev["cat"] = ev["base"].map(cats).fillna("OTRO")
times = ev["t"]
ev["calor"] = [((times >= t - pd.Timedelta(hours=24)) & (times < t)).sum() for t in times]
liq = []
for _, e in ev.iterrows():
    hp = frames[e["symbol"]]
    liq.append(hp.iloc[max(0, e["i"] - 720):e["i"]]["qv"].resample("1D").sum().median())
ev["liq_d"] = liq
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")

base_mask = (ev["calor"] >= 1) & (ev["liq_d"] < 100e6)
print(f"{'grupo':30s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
for name, mask in [
    ("sistema actual (referencia)", base_mask),
    ("solo MEME (sin otros filtros)", ev["cat"] == "MEME"),
    ("sistema + solo MEME", base_mask & (ev["cat"] == "MEME")),
    ("sistema sin MEME", base_mask & (ev["cat"] != "MEME")),
]:
    rows = {"A": [], "B": []}
    for k in np.flatnonzero(mask.to_numpy()):
        e = ev.iloc[k]
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows[e["periodo"]].append(r[0])
    for p in ("A", "B"):
        rr = np.array(rows[p])
        if len(rr) < 20:
            print(f"{name:30s} {p:4s} {len(rr):>5d}   (muestra corta)")
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        print(f"{name:30s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")
