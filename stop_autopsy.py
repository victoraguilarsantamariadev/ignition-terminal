"""
Autopsia del stop del 8%: para cada ignicion, ¿que toco primero el precio?

Clasifica cada evento en:
  ganador limpio   : alcanza +40% sin haber tocado antes -8%
  ganador matado   : toca -8% primero Y despues habria alcanzado +40% en los 7d
  perdedor cazado  : toca -8% y nunca habria llegado a +40% (el stop hace su trabajo)
  chop             : ni -8% ni +40% en 7 dias (salida por tiempo)

Tambien la version con umbral +25% para ver la sensibilidad.
"""
import glob
import os
import sys

import numpy as np

from momentum_ignition import detect, load

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HOLD = 168


def clasificar(hp, ev, stop_pct, tp_pct):
    i, entry = ev["i"], ev["entry"]
    stop = entry * (1 - stop_pct)
    tp = entry * (1 + tp_pct)
    win = hp.iloc[i + 1:i + 1 + HOLD]
    hit_stop_first, reached_tp_after, reached_tp_before = False, False, False
    stopped = False
    for _, r in win.iterrows():
        if not stopped and r["l"] <= stop:
            stopped = True
            continue
        if r["h"] >= tp:
            if stopped:
                reached_tp_after = True
            else:
                reached_tp_before = True
            break
    if reached_tp_before:
        return "ganador limpio"
    if stopped and reached_tp_after:
        return "ganador matado por stop"
    if stopped:
        return "perdedor cazado (stop OK)"
    return "chop / salida por tiempo"


def main():
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)
    print(f"{len(events)} igniciones\n")

    for tp_pct in (0.40, 0.25):
        counts = {}
        for e in events:
            c = clasificar(frames[e["symbol"]], e, 0.08, tp_pct)
            counts[c] = counts.get(c, 0) + 1
        n = sum(counts.values())
        print(f"--- stop 8%, objetivo +{tp_pct:.0%} ---")
        for k in ["ganador limpio", "ganador matado por stop",
                  "perdedor cazado (stop OK)", "chop / salida por tiempo"]:
            v = counts.get(k, 0)
            print(f"  {k:26s} {v:>5d}  ({v/n:.1%})")
        matados = counts.get("ganador matado por stop", 0)
        ganadores = matados + counts.get("ganador limpio", 0)
        if ganadores:
            print(f"  -> de los que llegan a +{tp_pct:.0%}, el stop mata al {matados/ganadores:.0%}")
        print()


if __name__ == "__main__":
    main()
