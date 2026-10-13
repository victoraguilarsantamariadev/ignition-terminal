"""
Ingenieria de RR: entrada en RETROCESO con stop estructural apretado.

Variantes (por senal de ignicion):
  base          : entrada inmediata, stop 8%, TP +40% (referencia)
  pullback 3%   : espera retroceso >=3% desde el cierre de deteccion (max 48h),
                  entra cuando el cierre reconquista ese nivel (max 72h),
                  stop = minimo del retroceso -0.5%, TP +40% desde la entrada
  pullback 5%   : igual con retroceso >=5%

Metrica clave: R por SEnAL (retorno/riesgo, senales perdidas = 0) — es lo que
alimenta el sizing/Kelly. Tambien $/senal, fill rate, riesgo medio.
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


def sim(hp, j, entry, stop):
    risk = (entry - stop) / entry
    if risk <= 0.004 or risk > 0.25:
        return None
    tp = entry * 1.40
    win = hp.iloc[j + 1:j + 1 + 168]
    if len(win) < 24:
        return None
    for _, r in win.iterrows():
        if r["l"] <= stop:
            return stop / entry - 1 - FEE, risk
        if r["h"] >= tp:
            return tp / entry - 1 - FEE, risk
    return win.iloc[-1]["c"] / entry - 1 - FEE, risk


def main():
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)

    print(f"{'variante':14s} {'per':4s} {'senales':>7s} {'entra':>6s} {'riesgo':>7s} "
          f"{'$/senal':>8s} {'R/senal':>8s} {'wr':>6s}")
    for name, pb in [("base", None), ("pullback 3%", 0.03), ("pullback 5%", 0.05)]:
        res = {"A": {"rets": [], "rs": [], "n": 0}, "B": {"rets": [], "rs": [], "n": 0}}
        for e in events:
            hp = frames[e["symbol"]]
            i, c0 = e["i"], frames[e["symbol"]].iloc[e["i"]]["c"]
            per = "A" if e["t"] < SPLIT else "B"
            res[per]["n"] += 1
            if pb is None:
                entry = hp.iloc[i + 1]["o"]
                r = sim(hp, i + 1, entry, entry * 0.92)
            else:
                r = None
                phase, plow = 0, None
                for j in range(i + 1, min(i + 73, len(hp) - 170)):
                    row = hp.iloc[j]
                    if phase == 0:
                        if row["l"] <= c0 * (1 - pb) and j <= i + 48:
                            phase, plow = 1, row["l"]
                        elif j > i + 48:
                            break
                    else:
                        plow = min(plow, row["l"])
                        if row["c"] > c0:
                            r = sim(hp, j, row["c"], plow * 0.995)
                            break
            if r is not None:
                res[per]["rets"].append(r[0])
                res[per]["rs"].append(r[0] / r[1])
        for p in ("A", "B"):
            d = res[p]
            rets, rs = np.array(d["rets"]), np.array(d["rs"])
            if not len(rets):
                continue
            print(f"{name:14s} {p:4s} {d['n']:>7d} {len(rets)/d['n']:>5.1%} "
                  f"{np.mean([r for r in (np.array(d['rets'])/np.array(d['rs']))]):>6.1%} "
                  f"{rets.sum()/d['n']:>+7.2%} {rs.sum()/d['n']:>+7.2f} "
                  f"{(rets>0).mean():>5.1%}")


if __name__ == "__main__":
    main()
