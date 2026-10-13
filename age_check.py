"""¿Las igniciones ganadoras ocurren en pares recien listados?
Fecha de listado = primera vela 1d del perpetuo. Tercil de edad + examen trade."""
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
CACHE = "listing_dates.json"


def listing_dates(symbols):
    if os.path.exists(CACHE):
        return {k: pd.Timestamp(v) for k, v in json.load(open(CACHE)).items()}
    out = {}
    for n, sym in enumerate(symbols, 1):
        r = S.get("https://fapi.binance.com/fapi/v1/klines",
                  params=dict(symbol=sym, interval="1d", startTime=0, limit=1), timeout=20)
        k = r.json()
        if k:
            out[sym] = int(k[0][0])
        print(f"[{n}/{len(symbols)}] {sym}", file=sys.stderr, flush=True)
        time.sleep(0.1)
    json.dump(out, open(CACHE, "w"))
    return {k: pd.Timestamp(v, unit="ms") for k, v in out.items()}


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

ld = listing_dates(sorted(ev["symbol"].unique()))
ev["edad_d"] = [(t - ld[s]).days if s in ld else np.nan
                for s, t in zip(ev["symbol"], ev["t"])]
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
ev["ganadora"] = ev["fwd_max"] >= 0.40

print(f"\nEdad del perpetuo en la ignicion: mediana {ev['edad_d'].median():.0f} dias")
ev["q_edad"] = pd.cut(ev["edad_d"], [0, 90, 365, 10000],
                      labels=["<90d (nuevo)", "90-365d", ">1 anyo"])
print(f"\n{'edad':14s} {'per':4s} {'n':>5s} {'P(+40%)':>8s} {'fwd_ret':>8s}")
for (p, q), g in ev.groupby(["periodo", "q_edad"], observed=True):
    if len(g) < 20:
        continue
    print(f"{str(q):14s} {p:4s} {len(g):>5d} {g['ganadora'].mean():>7.1%} {g['fwd_ret'].mean():>+7.2%}")

print(f"\nExamen trade real (stop 8% / TP40) por grupo de edad:")
print(f"{'grupo':14s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
for gname, mask in [("<90d", ev["edad_d"] < 90),
                    ("90-365d", (ev["edad_d"] >= 90) & (ev["edad_d"] < 365)),
                    (">1 anyo", ev["edad_d"] >= 365)]:
    rows = {"A": [], "B": []}
    for k in np.flatnonzero(mask.fillna(False).to_numpy()):
        e = ev.iloc[k]
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows[e["periodo"]].append(r[0])
    for p in ("A", "B"):
        rr = np.array(rows[p])
        if len(rr) < 20:
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        print(f"{gname:14s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")
