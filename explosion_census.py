"""
Censo de explosiones en los ~95 perpetuos con cache de 1100 dias.

Explosion: desde el cierre del dia D, el maximo de los 7 dias siguientes
sube >= +40%, y el precio NO venia ya disparado (|ret 5d previos| < 15%)
para capturar el ARRANQUE, no la continuacion. Eventos no solapados (>7d).

Control: mismo par, dia con fwd_max < +20%, tambien plano antes, y a mas de
7 dias de cualquier explosion.

Salida: explosions.csv, controls.csv y resumen en consola.
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

THRESH = 0.40
FLAT = 0.15
FWD = 7

events, controls = [], []
files = sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv"))
for f in files:
    sym = os.path.basename(f).split("_")[0]
    hp = pd.read_csv(f, index_col=0, parse_dates=True)
    d = pd.DataFrame({
        "h": hp["h"].resample("1D").max(),
        "l": hp["l"].resample("1D").min(),
        "c": hp["c"].resample("1D").last(),
        "qv": hp["qv"].resample("1D").sum(),
        "nh": hp["c"].resample("1D").count(),
    })
    d = d[d["nh"] >= 20]
    if len(d) < 60:
        continue
    d["fwd_max"] = d["h"].rolling(FWD).max().shift(-FWD) / d["c"] - 1
    d["ret5"] = d["c"].pct_change(5)
    d = d.dropna(subset=["fwd_max", "ret5"])

    cand = d[(d["fwd_max"] >= THRESH) & (d["ret5"].abs() < FLAT)].index
    ev_days, last = [], pd.Timestamp("2000-01-01")
    for t in cand:
        if (t - last).days > FWD:
            ev_days.append(t)
            last = t
    for t in ev_days:
        events.append(dict(symbol=sym, date=t.date(), fwd_max=d.loc[t, "fwd_max"],
                           vol_usd_d=d.loc[t, "qv"]))
    ctrl_ok = d[(d["fwd_max"] < 0.20) & (d["ret5"].abs() < FLAT)].index
    for t in ctrl_ok:
        if all(abs((t - e).days) > FWD for e in ev_days):
            controls.append(dict(symbol=sym, date=t.date(), fwd_max=d.loc[t, "fwd_max"],
                                 vol_usd_d=d.loc[t, "qv"]))

ev = pd.DataFrame(events)
ct = pd.DataFrame(controls)
ev.to_csv("explosions.csv", index=False)
ct.to_csv("controls.csv", index=False)

print(f"{len(ev)} explosiones (+{THRESH:.0%} en 7d, arrancando de plano) "
      f"en {ev['symbol'].nunique()} pares | {len(ct)} dias de control")
ev["date"] = pd.to_datetime(ev["date"])
by_year = ev.groupby(ev["date"].dt.year).size()
print("por anyo:", by_year.to_dict())
print("top pares:", ev["symbol"].value_counts().head(10).to_dict())
print(f"magnitud: mediana +{ev['fwd_max'].median():.0%}, p90 +{ev['fwd_max'].quantile(0.9):.0%}, "
      f"max +{ev['fwd_max'].max():.0%}")
