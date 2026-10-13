"""
¿Se puede monetizar el hallazgo de la continuacion? Regla de GESTION por flujo:
a las 24h de la entrada, si el delta acumulado (taker buy-sell / volumen) de esas
24h es peor que un umbral -> salida anticipada; si no, se mantiene el plan
normal (stop 8%, TP 40%, 7d). Solo usa informacion disponible en ese momento.
"""
import glob
import os
import sys

import numpy as np

from momentum_ignition import detect, load, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEE = 0.003


def sim(hp, ev, thr=None):
    i, entry = ev["i"], ev["entry"]
    stop, tp = entry * 0.92, entry * 1.40
    win = hp.iloc[i + 1:i + 1 + 168]
    if len(win) < 168:
        return None
    for k, (_, r) in enumerate(win.iterrows()):
        if r["l"] <= stop:
            return stop / entry - 1 - FEE
        if r["h"] >= tp:
            return tp / entry - 1 - FEE
        if thr is not None and k == 23:
            w24 = win.iloc[:24]
            d24 = w24["delta"].sum() / max(w24["qv"].sum(), 1)
            if d24 < thr:
                return r["c"] / entry - 1 - FEE
    return win.iloc[-1]["c"] / entry - 1 - FEE


def main():
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)

    print(f"{'regla':34s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
    for name, thr in [("base (sin gestion por flujo)", None),
                      ("salir a 24h si delta24 < -4%", -0.04),
                      ("salir a 24h si delta24 < -2%", -0.02),
                      ("salir a 24h si delta24 < 0%", 0.0)]:
        rows = {"A": [], "B": []}
        for e in events:
            r = sim(frames[e["symbol"]], e, thr)
            if r is not None:
                rows["A" if e["t"] < SPLIT else "B"].append(r)
        for p in ("A", "B"):
            rr = np.array(rows[p])
            wins, losses = rr[rr > 0], rr[rr <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            print(f"{name:34s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")


if __name__ == "__main__":
    main()
