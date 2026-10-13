"""
Estudio de EJECUCION: entrada a mercado vs orden limite.

  mercado    : open de la hora siguiente, coste 0.30% i/v (taker + slippage)
  limite 0%  : limite al cierre de la vela de deteccion, valida 6h, coste 0.20%
  limite -1% : limite 1% por debajo, valida 6h, coste 0.20%
  limite -2% : limite 2% por debajo, valida 6h, coste 0.20%

Comparacion POR SEnAL (las no ejecutadas cuentan 0): es la metrica justa,
porque el limite gana fee pero pierde los trenes que no vuelven.
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


def sim_from(hp, i_fill, entry, fee):
    stop, tp = entry * 0.92, entry * 1.40
    win = hp.iloc[i_fill:i_fill + 168]
    if len(win) < 30:
        return None
    for _, r in win.iterrows():
        if r["l"] <= stop:
            return stop / entry - 1 - fee
        if r["h"] >= tp:
            return tp / entry - 1 - fee
    return win.iloc[-1]["c"] / entry - 1 - fee


def main():
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)

    print(f"{'modo':12s} {'per':4s} {'senales':>8s} {'ejecuta':>8s} {'exp/senal':>10s} "
          f"{'exp/trade':>10s} {'%+40% perdidos':>14s}")
    for mode, disc, fee in [("mercado", None, 0.003), ("limite 0%", 0.0, 0.002),
                            ("limite -1%", 0.01, 0.002), ("limite -2%", 0.02, 0.002)]:
        res = {"A": {"rets": [], "miss_win": 0, "miss": 0, "n": 0},
               "B": {"rets": [], "miss_win": 0, "miss": 0, "n": 0}}
        for e in events:
            hp = frames[e["symbol"]]
            i = e["i"]
            per = "A" if e["t"] < SPLIT else "B"
            res[per]["n"] += 1
            if disc is None:
                r = sim_from(hp, i + 1, hp.iloc[i + 1]["o"], fee)
                if r is not None:
                    res[per]["rets"].append(r)
                continue
            limit = hp.iloc[i]["c"] * (1 - disc)
            fill = None
            for k in range(1, 7):
                if i + k >= len(hp):
                    break
                if hp.iloc[i + k]["l"] <= limit:
                    fill = i + k
                    break
            if fill is None:
                res[per]["miss"] += 1
                if e["fwd_max"] >= 0.40:
                    res[per]["miss_win"] += 1
                continue
            entry = min(limit, hp.iloc[fill]["o"])
            r = sim_from(hp, fill, entry, fee)
            if r is not None:
                res[per]["rets"].append(r)
        for p in ("A", "B"):
            d = res[p]
            rets = np.array(d["rets"])
            if not len(rets):
                continue
            exp_senal = rets.sum() / d["n"]  # las perdidas cuentan 0
            missed_wins = f"{d['miss_win']}/{d['miss']}" if d["miss"] else "-"
            print(f"{mode:12s} {p:4s} {d['n']:>8d} {len(rets)/d['n']:>7.1%} "
                  f"{exp_senal:>+9.2%} {rets.mean():>+9.2%} {missed_wins:>14s}")


if __name__ == "__main__":
    main()
