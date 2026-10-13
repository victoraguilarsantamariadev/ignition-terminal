"""
Curva antelacion-precision del gatillo de ignicion.

Variantes (ret minimo, ventana horas, multiplo de volumen), de mas temprana a
mas tardia. Para cada una: n senales, P(+25% mas desde la entrada), retorno
medio 7d, retroceso medio, y todo partido en periodo A (2023-25) y B (2025-26).
Entrada siempre: open de la hora siguiente al disparo. Dedupe 72h.
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

HOLD_H = 7 * 24
SPLIT = pd.Timestamp("2025-07-30")
FLAT = 0.15
CONFIGS = [
    ("muy temprana", 0.05, 3, 3.0),
    ("temprana",     0.07, 4, 3.0),
    ("rapida",       0.10, 3, 4.0),
    ("ACTUAL",       0.10, 6, 4.0),
    ("tardia",       0.15, 6, 4.0),
]

frames = []
for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
    hp = pd.read_csv(f, index_col=0, parse_dates=True)
    if len(hp) < 45 * 24:
        continue
    hp.attrs["sym"] = os.path.basename(f).split("_")[0]
    frames.append(hp)
print(f"{len(frames)} pares cargados", file=sys.stderr, flush=True)

print(f"{'config':13s} {'per':4s} {'n':>5s} {'P(+25%)':>8s} {'P(+40%)':>8s} {'fwd_ret':>8s} "
      f"{'fwd_min':>8s} {'entrada vs max7d':>17s}")
for name, thr, win, volx_min in CONFIGS:
    rows = {"A": [], "B": []}
    for hp in frames:
        c, qv = hp["c"], hp["qv"]
        retw = c / c.shift(win) - 1
        volw = qv.rolling(win).sum()
        volx = volw / volw.shift(1).rolling(720, min_periods=360).median()
        flat = (c.shift(win) / c.shift(win + 120) - 1).abs() < FLAT
        ign = (retw >= thr) & (volx >= volx_min) & flat
        idxs = np.flatnonzero(ign.to_numpy())
        last, n = -10**9, len(hp)
        for i in idxs:
            if i - last < 72 or i + 1 + HOLD_H >= n or i < 726:
                continue
            last = i
            entry = hp.iloc[i + 1]["o"]
            fwd = hp.iloc[i + 1:i + 1 + HOLD_H]
            fmax = fwd["h"].max() / entry - 1
            fmin = fwd["l"].min() / entry - 1
            fret = hp.iloc[i + HOLD_H]["c"] / entry - 1
            per = "A" if hp.index[i] < SPLIT else "B"
            # cuanta subida total capturas: entrada vs maximo posterior
            rows[per].append((fmax, fmin, fret))
    for per in ("A", "B"):
        r = rows[per]
        if len(r) < 30:
            continue
        fmax = np.array([x[0] for x in r])
        fmin = np.array([x[1] for x in r])
        fret = np.array([x[2] for x in r])
        print(f"{name:13s} {per:4s} {len(r):>5d} {(fmax>=0.25).mean():>7.1%} {(fmax>=0.40).mean():>7.1%} "
              f"{fret.mean():>+7.2%} {fmin.mean():>+7.2%} {np.median(fmax):>+16.1%}")
