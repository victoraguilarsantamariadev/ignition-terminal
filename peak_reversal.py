"""
SEPTIMO y ultimo juicio al corto: el ROUND-TRIP post-pico.

Evento (pre-registrado, sin rejilla):
  1) ARMADO: el precio alcanza +40% vs hace 7 dias (pico de pump en curso)
  2) DISPARO: primer cierre 1h por debajo del minimo de las 24h previas
     (rotura de estructura confirmada), dentro de los 5 dias tras armarse
  3) CORTO al open siguiente · stop = maximo del pump +2% · TP -20% o -30%
     · salida por tiempo 7 dias · fees 0.3% · dedupe 7d por simbolo

Tambien descriptivo: ¿la rotura post-pico voltea la deriva de +1.97%/3d?
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

SPLIT = pd.Timestamp("2025-07-30")
FEE = 0.003


def eventos(hp, sym):
    c, l, h = hp["c"].to_numpy(), hp["l"].to_numpy(), hp["h"].to_numpy()
    idx = hp.index
    n = len(hp)
    ret168 = hp["c"] / hp["c"].shift(168) - 1
    out = []
    j = 200
    while j < n - 200:
        if ret168.iloc[j] >= 0.40:
            maxhigh = h[j]
            armado_en = j
            trig = None
            k = j + 1
            while k < min(j + 120, n - 180):
                maxhigh = max(maxhigh, h[k])
                low24 = l[max(0, k - 24):k].min()
                if c[k] < low24:
                    trig = k
                    break
                k += 1
            if trig is not None:
                out.append(dict(symbol=sym, t=idx[trig], i=trig, maxhigh=maxhigh,
                                pump_ret=float(ret168.iloc[armado_en])))
                j = trig + 168
                continue
            j = k + 1
        else:
            j += 1
    return out


def sim_short(hp, ev, tp_pct):
    i = ev["i"]
    entry = hp.iloc[i + 1]["o"]
    stop = ev["maxhigh"] * 1.02
    risk = stop / entry - 1
    if risk <= 0.01 or risk > 0.40:
        return None
    tp = entry * (1 - tp_pct)
    win = hp.iloc[i + 1:i + 1 + 168]
    for _, r in win.iterrows():
        if r["h"] >= stop:
            return -(stop / entry - 1) - FEE, risk
        if r["l"] <= tp:
            return tp_pct - FEE, risk
    return -(win.iloc[-1]["c"] / entry - 1) - FEE, risk


def main():
    frames, evs = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = pd.read_csv(f, index_col=0, parse_dates=True)
        if len(hp) < 500:
            continue
        frames[sym] = hp
        evs += eventos(hp, sym)
    ev = pd.DataFrame(evs)
    ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
    print(f"{len(ev)} roturas post-pico en {ev['symbol'].nunique()} pares "
          f"(A: {(ev['periodo']=='A').sum()}, B: {(ev['periodo']=='B').sum()})\n")

    # descriptivo: deriva tras la rotura
    fwd3, fwd7 = [], []
    for _, e in ev.iterrows():
        hp = frames[e["symbol"]]
        i = e["i"]
        if i + 168 < len(hp):
            base = hp.iloc[i + 1]["o"]
            fwd3.append(hp.iloc[i + 72]["c"] / base - 1)
            fwd7.append(hp.iloc[i + 168]["c"] / base - 1)
    print(f"deriva tras la rotura: 3d medio {np.mean(fwd3):+.2%} (mediana {np.median(fwd3):+.2%}) | "
          f"7d medio {np.mean(fwd7):+.2%} (mediana {np.median(fwd7):+.2%})")
    print(f"(recordatorio: la deriva post-pump SIN rotura era +1.97%/3d)\n")

    print(f"{'tp':>5s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s} {'R medio':>8s}")
    for tp in (0.20, 0.30):
        rows = {"A": [], "B": []}
        for _, e in ev.iterrows():
            r = sim_short(frames[e["symbol"]], e, tp)
            if r:
                rows[e["periodo"]].append(r)
        for p in ("A", "B"):
            rr = rows[p]
            if len(rr) < 20:
                continue
            rets = np.array([x[0] for x in rr])
            rmul = rets / np.array([x[1] for x in rr])
            wins, losses = rets[rets > 0], rets[rets <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            print(f"{tp:>4.0%} {p:4s} {len(rets):>5d} {rets.mean():>+6.2%} "
                  f"{(rets>0).mean():>5.1%} {pf:>5.2f} {rmul.mean():>+7.2f}")


if __name__ == "__main__":
    main()
