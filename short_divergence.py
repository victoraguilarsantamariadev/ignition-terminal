"""
CORTOS por firma de DISTRIBUCION dentro de la ventana post-ignicion (7 dias):

  S1 divergencia : delta perp 24h comprador (>+1% del vol) mientras el delta
                   spot 24h es vendedor (<-1%). Inflan perp, vacian spot.
  S2 hueco       : el delta acumulado desde la ignicion devolvio >=80% de su
                   maximo pero el precio aguanta >=+10% sobre la entrada.
                   El dinero salio, el precio aun no lo sabe.

Primera ocurrencia por evento. Corto al open siguiente, stop +8%, TP -20% o
sin TP, 5 dias, fees 0.3%. Split A/B. Baseline: mismas ventanas sin senal.
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
HOLD = 5 * 24


def sim_short(hp, j, tp_pct):
    entry = hp.iloc[j + 1]["o"]
    stop = entry * 1.08
    tp = entry * (1 - tp_pct) if tp_pct else None
    win = hp.iloc[j + 1:j + 1 + HOLD]
    if len(win) < 24:
        return None
    for _, r in win.iterrows():
        if r["h"] >= stop:
            return -(stop / entry - 1) - FEE
        if tp is not None and r["l"] <= tp:
            return -(tp / entry - 1) - FEE
    return -(win.iloc[-1]["c"] / entry - 1) - FEE


def main():
    frames, spot, events = {}, {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        sp_f = f".cache_1h/{sym}_spot_1h_1100.csv"
        if os.path.exists(sp_f):
            spot[sym] = pd.read_csv(sp_f, index_col=0, parse_dates=True)
        events += detect(hp, sym)
    print(f"{len(events)} igniciones", file=sys.stderr, flush=True)

    trig = {"S1": [], "S2": []}
    base_fwd = []
    for e in events:
        sym, i = e["symbol"], e["i"]
        hp = frames[sym]
        sp = spot.get(sym)
        entry0 = e["entry"]
        n = len(hp)
        end = min(i + 1 + 168, n - HOLD - 2)
        cum_delta, cum_max = 0.0, 0.0
        s1_done = s2_done = False
        for j in range(i + 1, end):
            cum_delta += hp.iloc[j]["delta"]
            cum_max = max(cum_max, cum_delta)
            if j < i + 12:
                continue
            if not s1_done and sp is not None:
                w = slice(hp.index[j - 23], hp.index[j])
                dp = hp.loc[w, "delta"].sum() / max(hp.loc[w, "qv"].sum(), 1)
                sw = sp.loc[w] if len(sp.loc[w]) >= 20 else None
                if sw is not None:
                    ds = sw["delta"].sum() / max(sw["qv"].sum(), 1)
                    if dp > 0.01 and ds < -0.01:
                        trig["S1"].append((sym, hp.index[j], j))
                        s1_done = True
            if not s2_done and cum_max > 0 and cum_delta < 0.2 * cum_max \
                    and hp.iloc[j]["c"] >= entry0 * 1.10:
                trig["S2"].append((sym, hp.index[j], j))
                s2_done = True
            if s1_done and s2_done:
                break
        # baseline: mitad de la ventana, sin condicion
        j = i + 84
        if j < end:
            base_fwd.append(hp.iloc[min(j + 72, n - 1)]["c"] / hp.iloc[j]["c"] - 1)

    print(f"baseline (hora media de la ventana post-pump): fwd 3d medio "
          f"{np.mean(base_fwd):+.2%} (n={len(base_fwd)})\n")
    print(f"{'senal':4s} {'tp':>5s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
    for s in ("S1", "S2"):
        for tp in (0.20, None):
            rows = {"A": [], "B": []}
            for sym, t, j in trig[s]:
                r = sim_short(frames[sym], j, tp)
                if r is not None:
                    rows["A" if t < SPLIT else "B"].append(r)
            for p in ("A", "B"):
                rr = np.array(rows[p])
                if len(rr) < 15:
                    print(f"{s:4s} {str(tp or 'no'):>5s} {p:4s} {len(rr):>5d}   (muestra corta)")
                    continue
                wins, losses = rr[rr > 0], rr[rr <= 0]
                pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
                print(f"{s:4s} {str(tp or 'no'):>5s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} "
                      f"{(rr>0).mean():>5.1%} {pf:>5.2f}")


if __name__ == "__main__":
    main()
