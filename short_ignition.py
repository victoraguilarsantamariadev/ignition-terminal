"""
IGNICION BAJISTA -> continuacion en corto (el espejo nunca testeado).

Deteccion: ret 6h <= -10%, volumen 6h >= 4x mediana 30d, venia plano
(|ret 5d previos| < 15%), sin otra en 72h. Entrada: short al open siguiente.

Se mide: P(el minimo de los 7d siguientes <= -25%) vs baseline de horas planas,
delta de la ignicion (¿venta agresiva = MM vendiendo?), y rejilla stop x TP
en corto con split A/B. Fees 0.3%. Funding NO incluido (en crashes el funding
se vuelve negativo y el corto LO PAGA: resta extra en real).
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

from momentum_ignition import load, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HOLD_H = 7 * 24


def detect_down(hp, symbol):
    c, qv = hp["c"], hp["qv"]
    ret6 = c / c.shift(6) - 1
    vol6 = qv.rolling(6).sum()
    volx = vol6 / vol6.shift(1).rolling(720, min_periods=360).median()
    flat = (c.shift(6) / c.shift(6 + 120) - 1).abs() < 0.15
    ign = (ret6 <= -0.10) & (volx >= 4.0) & flat
    idxs = np.flatnonzero(ign.to_numpy())
    events, last, n = [], -10**9, len(hp)
    for i in idxs:
        if i - last < 72 or i + 1 + HOLD_H >= n or i < 726:
            continue
        last = i
        w = hp.iloc[i - 5:i + 1]
        entry = hp.iloc[i + 1]["o"]
        events.append(dict(
            symbol=symbol, t=hp.index[i], i=i, entry=entry,
            ign_ret=ret6.iloc[i], volx=volx.iloc[i],
            delta_share=w["delta"].sum() / max(w["qv"].sum(), 1),
            high_base=w["h"].max(),
            fwd_min=hp.iloc[i + 1:i + 1 + HOLD_H]["l"].min() / entry - 1,
            fwd_max=hp.iloc[i + 1:i + 1 + HOLD_H]["h"].max() / entry - 1,
            fwd_ret=hp.iloc[i + HOLD_H]["c"] / entry - 1,
        ))
    return events


def sim_short(hp, ev, stop_kind, tp_pct, fee=0.003):
    i, entry = ev["i"], ev["entry"]
    if stop_kind == "estructural":
        stop = ev["high_base"] * 1.01
    else:
        stop = entry * (1 + stop_kind)
    risk = (stop - entry) / entry
    if risk <= 0.005 or risk > 0.5:
        return None
    tp = entry * (1 - tp_pct) if tp_pct else None
    win = hp.iloc[i + 1:i + 1 + HOLD_H]
    exit_px, hit = None, "tiempo"
    for _, r in win.iterrows():
        if r["h"] >= stop:
            exit_px, hit = stop, "stop"
            break
        if tp is not None and r["l"] <= tp:
            exit_px, hit = tp, "tp"
            break
    if exit_px is None:
        exit_px = win.iloc[-1]["c"]
    ret = (entry / exit_px - 1) if False else -(exit_px / entry - 1)
    return ret - fee, hit


def main():
    frames, events, base = {}, [], []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect_down(hp, sym)
        b = hp[hp["flat5d"] & hp["fwd_min"].notna()].iloc[::24]
        base.append(b[["fwd_min", "fwd_ret"]])
    ev = pd.DataFrame(events)
    base = pd.concat(base)
    ev.to_csv("ignitions_short.csv", index=False)

    print("=" * 74)
    print(f"[A] {len(ev)} igniciones BAJISTAS en {ev['symbol'].nunique()} pares")
    print(f"  baseline horas planas: P(min7d<=-25%)={(base['fwd_min']<=-0.25).mean():.1%}"
          f"  fwd_ret medio {base['fwd_ret'].mean():+.2%}")
    print(f"  tras ignicion bajista: P(min7d<=-25%)={(ev['fwd_min']<=-0.25).mean():.1%}"
          f"  fwd_ret medio {ev['fwd_ret'].mean():+.2%}  fwd_max medio {ev['fwd_max'].mean():+.2%}")
    ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
    for p, g in ev.groupby("periodo"):
        print(f"    {p}: n={len(g):>4d}  P(-25%)={(g['fwd_min']<=-0.25).mean():.1%}"
              f"  fwd_ret {g['fwd_ret'].mean():+.2%}")

    print(f"\n[B] ¿venta agresiva (MM vendiendo) predice continuacion? tercil de delta")
    ev["q"] = pd.qcut(ev["delta_share"], 3, labels=["venta agresiva", "medio", "compra (dip-buyers)"])
    for q, g in ev.groupby("q", observed=True):
        print(f"  {str(q):22s} n={len(g):>4d}  delta {g['delta_share'].mean():+.2f}"
              f"  P(-25%)={(g['fwd_min']<=-0.25).mean():.1%}  fwd_ret {g['fwd_ret'].mean():+.2%}")

    print(f"\n[C] REJILLA EN CORTO (ganancia = caida; fees 0.3%; funding NO incluido)")
    print(f"{'per':3s} {'stop':>12s} {'tp':>6s} {'n':>5s} {'exp':>7s} {'med':>7s} {'wr':>6s} {'PF':>5s} {'%stop':>6s}")
    for stop_kind in ["estructural", 0.08, 0.12]:
        for tp_pct in [0.25, 0.40, None]:
            rows = {"A": [], "B": []}
            for _, e in ev.iterrows():
                r = sim_short(frames[e["symbol"]], e, stop_kind, tp_pct)
                if r:
                    rows[e["periodo"]].append(r)
            for p in ("A", "B"):
                rr = rows[p]
                if len(rr) < 20:
                    continue
                rets = np.array([x[0] for x in rr])
                hits = [x[1] for x in rr]
                wins, losses = rets[rets > 0], rets[rets <= 0]
                pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
                sk = f"{stop_kind:.0%}" if isinstance(stop_kind, float) else stop_kind
                tk = f"{tp_pct:.0%}" if tp_pct else "no"
                print(f"{p:3s} {sk:>12s} {tk:>6s} {len(rets):>5d} {rets.mean():>+6.2%} "
                      f"{np.median(rets):>+6.2%} {(rets>0).mean():>5.1%} {pf:>5.2f} "
                      f"{hits.count('stop')/len(hits):>5.1%}")


if __name__ == "__main__":
    main()
