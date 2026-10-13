"""
Ingenieria de salidas sobre las igniciones (senal fija, solo cambia la gestion).

Variantes (todas con entrada open siguiente, fees 0.3%):
  base        : stop 8%, TP +40%, 7 dias           (referencia)
  breakeven   : igual + tras tocar +10% el stop sube a entrada
  trailing12  : stop 8% inicial, trailing 12% desde el maximo, sin TP, 7d
  trail_act   : stop 8% fijo hasta tocar +10%, luego trailing 12%, sin TP, 7d
  parcial     : 50% sale en +15% (stop 8%), 50% con trail_act
  corte48h    : base + si a las 48h esta bajo la entrada, salida a mercado
  base14d     : stop 8%, TP +40%, 14 dias

Juicio por consistencia A/B, no por mejor celda.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

from momentum_ignition import detect, load, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEE = 0.003


def sim(hp, ev, variant):
    i, entry = ev["i"], ev["entry"]
    hold = 336 if variant == "base14d" else 168
    win = hp.iloc[i + 1:i + 1 + hold]
    if len(win) < hold:
        return None
    stop = entry * 0.92
    tp = entry * 1.40 if variant in ("base", "breakeven", "corte48h", "base14d") else None
    maxhigh, trail_on = entry, variant == "trailing12"
    for k, (_, r) in enumerate(win.iterrows()):
        if r["l"] <= stop:
            return stop / entry - 1 - FEE
        if tp is not None and r["h"] >= tp:
            return tp / entry - 1 - FEE
        if variant == "corte48h" and k == 47 and r["c"] < entry:
            return r["c"] / entry - 1 - FEE
        maxhigh = max(maxhigh, r["h"])
        if variant == "breakeven" and maxhigh >= entry * 1.10:
            stop = max(stop, entry * 1.001)
        if variant in ("trailing12", "trail_act"):
            if variant == "trail_act" and maxhigh >= entry * 1.10:
                trail_on = True
            if trail_on:
                stop = max(stop, maxhigh * 0.88)
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
    print(f"{len(events)} igniciones", file=sys.stderr, flush=True)

    variants = ["base", "breakeven", "trailing12", "trail_act", "parcial", "corte48h", "base14d"]
    print(f"{'variante':11s} {'per':4s} {'n':>5s} {'exp':>7s} {'med':>7s} {'wr':>6s} {'PF':>5s}")
    for v in variants:
        rows = {"A": [], "B": []}
        for e in events:
            hp = frames[e["symbol"]]
            if v == "parcial":
                r1 = sim(hp, e, "base_p15")  # pierna TP15
                # pierna 1: stop8 TP15
                i, entry = e["i"], e["entry"]
                win = hp.iloc[i + 1:i + 1 + 168]
                if len(win) < 168:
                    continue
                stop, tp1, r1 = entry * 0.92, entry * 1.15, None
                for _, rr in win.iterrows():
                    if rr["l"] <= stop:
                        r1 = stop / entry - 1 - FEE
                        break
                    if rr["h"] >= tp1:
                        r1 = tp1 / entry - 1 - FEE
                        break
                if r1 is None:
                    r1 = win.iloc[-1]["c"] / entry - 1 - FEE
                r2 = sim(hp, e, "trail_act")
                if r2 is None:
                    continue
                ret = 0.5 * r1 + 0.5 * r2
            else:
                ret = sim(hp, e, v)
                if ret is None:
                    continue
            rows["A" if e["t"] < SPLIT else "B"].append(ret)
        for p in ("A", "B"):
            rr = np.array(rows[p])
            if len(rr) < 30:
                continue
            wins, losses = rr[rr > 0], rr[rr <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            print(f"{v:11s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {np.median(rr):>+6.2%} "
                  f"{(rr>0).mean():>5.1%} {pf:>5.2f}")

    # ¿importa cuantas igniciones hay el mismo dia? (calor de mercado)
    ev = pd.DataFrame(events)
    ev["dia"] = pd.to_datetime(ev["t"]).dt.date
    ev["n_dia"] = ev.groupby("dia")["symbol"].transform("count")
    ev["periodo"] = np.where(pd.to_datetime(ev["t"]) < SPLIT, "A", "B")
    ev["calor"] = pd.cut(ev["n_dia"], [0, 1, 3, 99], labels=["solitaria", "2-3/dia", "4+/dia"])
    print("\nCalor de mercado (igniciones simultaneas el mismo dia):")
    for (p, c), g in ev.groupby(["periodo", "calor"], observed=True):
        if len(g) < 30:
            continue
        print(f"  {p} {str(c):10s} n={len(g):>4d}  P(+25%)={(g['fwd_max']>=0.25).mean():.1%}  "
              f"fwd_ret {g['fwd_ret'].mean():+.2%}")


if __name__ == "__main__":
    main()
