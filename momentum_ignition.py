"""
Backtest de IGNICION -> CONTINUACION en los 95 perpetuos (cache 1h, ~3 anyos).

Ignicion (detectable en tiempo real, sin mirar futuro):
  - ret 6h >= +10%
  - volumen 6h >= 4x su mediana de 30 dias
  - venia plano: |ret 5d previos (terminando antes de la ignicion)| < 15%
  - sin otra ignicion en las 72h anteriores (primera chispa, no re-entrada)

Entrada simulada: open de la hora siguiente a la deteccion. Costes 0.3%
ida+vuelta (persiguiendo momentum el slippage es peor).

Se responde:
  A) descriptivo: ¿continuan? P(+25% mas desde la entrada en 7d) vs baseline
     de horas planas del mismo universo; cuanto retrocede antes de continuar.
  B) ¿importa QUIEN enciende? continuacion condicionada al delta agresor de la
     ventana de ignicion (tesis MM: delta muy comprador deberia continuar mas).
  C) operable: rejilla stop x TP con split temporal A (2023-09..2025-07) /
     B (2025-08..hoy) reportado SIEMPRE en paralelo — sin elegir la mejor celda
     de un solo periodo.
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

FEE = 0.003
HOLD_H = 7 * 24
SPLIT = pd.Timestamp("2025-07-30")
RET_IGN = 0.10
VOLX_MIN = 4.0
FLAT = 0.15


def load(f):
    hp = pd.read_csv(f, index_col=0, parse_dates=True)
    if len(hp) < 45 * 24:
        return None
    c, qv = hp["c"], hp["qv"]
    hp["ret6"] = c / c.shift(6) - 1
    vol6 = qv.rolling(6).sum()
    hp["volx"] = vol6 / vol6.shift(1).rolling(720, min_periods=360).median()
    hp["flat5d"] = (c.shift(6) / c.shift(6 + 120) - 1).abs() < FLAT
    hp["fwd_max"] = hp["h"].rolling(HOLD_H).max().shift(-HOLD_H) / c - 1
    hp["fwd_min"] = hp["l"].rolling(HOLD_H).min().shift(-HOLD_H) / c - 1
    hp["fwd_ret"] = c.shift(-HOLD_H) / c - 1
    return hp


def detect(hp, symbol):
    ign = (hp["ret6"] >= RET_IGN) & (hp["volx"] >= VOLX_MIN) & hp["flat5d"]
    idxs = np.flatnonzero(ign.to_numpy())
    events, last = [], -10**9
    n = len(hp)
    for i in idxs:
        if i - last < 72 or i + 1 + HOLD_H >= n or i < 726:
            continue
        last = i
        w = hp.iloc[i - 5:i + 1]
        entry = hp.iloc[i + 1]["o"]
        events.append(dict(
            symbol=symbol, t=hp.index[i], i=i, entry=entry,
            ign_ret=hp.iloc[i]["ret6"], volx=hp.iloc[i]["volx"],
            delta_share=w["delta"].sum() / max(w["qv"].sum(), 1),
            low_base=w["l"].min(),
            fwd_max=hp.iloc[i + 1:i + 1 + HOLD_H]["h"].max() / entry - 1,
            fwd_min=hp.iloc[i + 1:i + 1 + HOLD_H]["l"].min() / entry - 1,
            fwd_ret=hp.iloc[i + HOLD_H]["c"] / entry - 1,
        ))
    return events


def simulate(hp, ev, stop_kind, tp_pct):
    i, entry = ev["i"], ev["entry"]
    if stop_kind == "estructural":
        stop = ev["low_base"] * 0.99
    else:
        stop = entry * (1 - stop_kind)
    risk = (entry - stop) / entry
    if risk <= 0.005 or risk > 0.5:
        return None
    tp = entry * (1 + tp_pct) if tp_pct else None
    win = hp.iloc[i + 1:i + 1 + HOLD_H]
    exit_px, hit = None, "tiempo"
    for _, r in win.iterrows():
        if r["l"] <= stop:
            exit_px, hit = stop, "stop"
            break
        if tp is not None and r["h"] >= tp:
            exit_px, hit = tp, "tp"
            break
    if exit_px is None:
        exit_px = win.iloc[-1]["c"]
    ret = exit_px / entry - 1 - FEE
    return ret, ret / risk, hit


def main():
    frames, all_events = {}, []
    files = sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv"))
    for f in files:
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        all_events += detect(hp, sym)
    ev = pd.DataFrame(all_events)
    ev.to_csv("ignitions.csv", index=False)

    # baseline: todas las horas planas y completas (muestreadas cada 24h)
    base = []
    for sym, hp in frames.items():
        b = hp[hp["flat5d"] & hp["fwd_max"].notna()].iloc[::24]
        base.append(b[["fwd_max", "fwd_min", "fwd_ret"]])
    base = pd.concat(base)

    print("=" * 80)
    print(f"[A] {len(ev)} igniciones en {ev['symbol'].nunique()} pares "
          f"(+{RET_IGN:.0%}/6h, vol {VOLX_MIN:.0f}x, desde plano)")
    for label, sub in [("baseline horas planas", base), ("tras ignicion", ev)]:
        print(f"  {label:22s} n={len(sub):>6d}  P(max7d>=+25%)={ (sub['fwd_max']>=0.25).mean():.1%}"
              f"  P(>=+40%)={(sub['fwd_max']>=0.40).mean():.1%}"
              f"  fwd_ret medio {sub['fwd_ret'].mean():+.2%}  fwd_min medio {sub['fwd_min'].mean():+.2%}")
    ev["periodo"] = np.where(ev["t"] < SPLIT, "A(23-25)", "B(25-26)")
    print("\n  por periodo (¿estable?):")
    for p, g in ev.groupby("periodo"):
        print(f"    {p}: n={len(g):>4d}  P(+25%)={(g['fwd_max']>=0.25).mean():.1%}"
              f"  fwd_ret {g['fwd_ret'].mean():+.2%}  mediana {g['fwd_ret'].median():+.2%}")

    print(f"\n[B] ¿Importa quien enciende? continuacion por tercil de delta de la ignicion")
    ev["q_delta"] = pd.qcut(ev["delta_share"], 3, labels=["venta/hueco", "medio", "compra agresiva"])
    for q, g in ev.groupby("q_delta", observed=True):
        print(f"  {str(q):16s} n={len(g):>4d}  delta medio {g['delta_share'].mean():+.2f}"
              f"  P(+25%)={(g['fwd_max']>=0.25).mean():.1%}  fwd_ret {g['fwd_ret'].mean():+.2%}")
    print("  (tambien por tamano de la chispa)")
    ev["q_magn"] = pd.qcut(ev["ign_ret"], 3, labels=["+10-12%", "media", "grande"])
    for q, g in ev.groupby("q_magn", observed=True):
        print(f"  chispa {str(q):10s} n={len(g):>4d}  P(+25%)={(g['fwd_max']>=0.25).mean():.1%}"
              f"  fwd_ret {g['fwd_ret'].mean():+.2%}")

    print(f"\n[C] OPERABLE — rejilla con ambos periodos SIEMPRE (fees 0.3%)")
    print(f"{'per':3s} {'stop':>12s} {'tp':>5s} {'n':>5s} {'exp':>7s} {'med':>7s} {'wr':>6s} {'PF':>5s} {'%stop':>6s} {'%tp':>5s}")
    for stop_kind in ["estructural", 0.08, 0.12]:
        for tp_pct in [0.25, 0.40, None]:
            rows = {"A": [], "B": []}
            for _, e in ev.iterrows():
                r = simulate(frames[e["symbol"]], e, stop_kind, tp_pct)
                if r:
                    rows["A" if e["t"] < SPLIT else "B"].append(r)
            for p in ("A", "B"):
                rr = rows[p]
                if len(rr) < 15:
                    continue
                rets = np.array([x[0] for x in rr])
                hits = [x[2] for x in rr]
                wins, losses = rets[rets > 0], rets[rets <= 0]
                pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
                sk = f"{stop_kind:.0%}" if isinstance(stop_kind, float) else stop_kind
                tk = f"{tp_pct:.0%}" if tp_pct else "no"
                print(f"{p:3s} {sk:>12s} {tk:>5s} {len(rets):>5d} {rets.mean():>+6.2%} "
                      f"{np.median(rets):>+6.2%} {(rets>0).mean():>5.1%} {pf:>5.2f} "
                      f"{hits.count('stop')/len(hits):>5.1%} {hits.count('tp')/len(hits):>4.1%}")

    print("\nCSV: ignitions.csv | avisos: supervivencia del universo, funding no incluido.")


if __name__ == "__main__":
    main()
