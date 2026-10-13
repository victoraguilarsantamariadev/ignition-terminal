"""
Simulador de operaciones sobre las senales del consensus_backtest, LARGOS y CORTOS.

LARGOS (firma "comprador pasivo"):
  L_A = F3_divergencia & F4_grind      (precio sube con CVD negativo + grind 48h)
  L_B = F3_divergencia & F7_compresion (divergencia + rango comprimido)

CORTOS (espejo + las senales que salieron anti-alcistas):
  S_A = ret_2d < -3% con CVD positivo & grind bajista 48h con CVD positivo
        (vendedor pasivo distribuyendo: compradores agresivos absorbidos)
  S_B = funding_3d negativo & basis perp negativo, cerca de minimos
        (la "moneda muriendo": F6+F8, que predijo ausencia de pumps)
  S_C = barrido del maximo de 20d rechazado con volumen (espejo de F1)

Ejecucion simulada con velas 1h (path-dependent):
  - entrada: open de la primera hora del dia siguiente a la senal
  - stop:    pct fijo (5/8/12%) o estructural (minimo del setup -1%, para
             cortos el maximo del setup +1%)
  - salida:  take-profit fijo (15/25%), o salida por tiempo a los 7 dias
  - si stop y TP se tocan en la misma vela 1h -> se asume STOP (conservador)
  - costes: 0.15% ida+vuelta (taker 2x0.05% + slippage). Funding no incluido.

Uso: python trade_rules.py --top 100 --days 400   (usa la cache .cache_1h)
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

from consensus_backtest import FAPI, SAPI, klines_1h, funding, perp_symbols, zshift

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEE = 0.0015
HOLD_H = 7 * 24


def build(symbol, days, cache_dir):
    hp = klines_1h(FAPI, symbol, days, cache_dir)
    if hp.empty or len(hp) < 100 * 24:
        return None
    try:
        hs = klines_1h(SAPI, symbol, days, cache_dir)
    except Exception:
        hs = pd.DataFrame()
    fr = funding(symbol, days, cache_dir)

    hp = hp.copy()
    hp["delta_z"] = zshift(hp["delta"], 24 * 30, 24 * 10)
    hp["up"] = (hp["c"] > hp["o"]).astype(float)
    hp["up_share_48"] = hp["up"].rolling(48).mean()
    hp["cvd_48"] = hp["delta"].rolling(48).sum()

    d = pd.DataFrame({
        "o": hp["o"].resample("1D").first(), "h": hp["h"].resample("1D").max(),
        "l": hp["l"].resample("1D").min(), "c": hp["c"].resample("1D").last(),
        "qv": hp["qv"].resample("1D").sum(), "delta": hp["delta"].resample("1D").sum(),
        "nh": hp["c"].resample("1D").count(),
        "up_share_48": hp["up_share_48"].resample("1D").last(),
        "cvd_48": hp["cvd_48"].resample("1D").last(),
    })
    d = d[d["nh"] >= 20].drop(columns="nh")
    if len(d) < 150:
        return None
    if not hs.empty:
        d["c_spot"] = hs["c"].resample("1D").last().reindex(d.index)
    else:
        d["c_spot"] = np.nan
    d["funding"] = fr.reindex(d.index)

    low20 = d["l"].shift(1).rolling(20).min()
    high20 = d["h"].shift(1).rolling(20).max()
    d["low20"] = low20
    d["high20"] = high20
    d["near_low"] = d["c"] / low20 - 1
    d["near_high"] = d["c"] / high20 - 1
    d["vol_z"] = zshift(d["qv"], 60, 30)
    d["ret_2d"] = d["c"].pct_change(2)
    d["cvd_2d"] = d["delta"].rolling(2).sum()
    rng10 = (d["h"].rolling(10).max() - d["l"].rolling(10).min()) / d["c"]
    d["rng_pctl"] = rng10.rolling(120, min_periods=60).rank(pct=True)
    d["vol_dry"] = d["qv"].rolling(5).mean() / d["qv"].rolling(20).mean()
    d["funding_3d"] = d["funding"].shift(1).rolling(3).mean()
    d["basis_3d"] = (d["c"] / d["c_spot"] - 1).rolling(3).mean()

    F3 = (d["ret_2d"] > 0.03) & (d["cvd_2d"] < 0)
    F4 = (d["up_share_48"] >= 0.60) & (d["cvd_48"] < 0)
    F7 = (d["rng_pctl"] < 0.20) & (d["vol_dry"] < 0.7) & (d["near_low"] < 0.15)

    sig = pd.DataFrame(index=d.index)
    sig["L_A"] = F3 & F4
    sig["L_B"] = F3 & F7
    sig["S_A"] = (d["ret_2d"] < -0.03) & (d["cvd_2d"] > 0) & (d["up_share_48"] <= 0.40) & (d["cvd_48"] > 0)
    sig["S_B"] = (d["funding_3d"] < -0.0001) & (d["basis_3d"] < -0.0005) & (d["near_low"] < 0.10)
    sig["S_C"] = (d["h"] > high20) & (d["c"] < high20) & (d["vol_z"] > 1)
    sig = sig.fillna(False)
    # disparo nuevo: off -> on
    for c in sig.columns:
        sig[c] = sig[c] & ~sig[c].shift(1).fillna(False).astype(bool)
    sig = sig.iloc[65:]
    return d, sig, hp[["o", "h", "l", "c"]]


def simulate(d, hp, days_fired, side, stop_kind, tp_pct):
    """side +1 largo, -1 corto. Devuelve lista de retornos netos y R."""
    res = []
    hidx = hp.index
    for t in days_fired:
        t_entry = t + pd.Timedelta(days=1)
        pos = hidx.searchsorted(t_entry)
        if pos >= len(hidx) - 1:
            continue
        entry = hp.iloc[pos]["o"]
        row = d.loc[t]
        if stop_kind == "estructural":
            if side > 0:
                stop = min(row["l"], row["low20"]) * 0.99
            else:
                stop = max(row["h"], row["high20"]) * 1.01
        else:
            stop = entry * (1 - side * stop_kind)
        risk = abs(entry - stop) / entry
        if not np.isfinite(risk) or risk <= 0.001 or risk > 0.5:
            continue
        tp = entry * (1 + side * tp_pct) if tp_pct else None
        exit_px, hit = None, "tiempo"
        win = hp.iloc[pos:pos + HOLD_H]
        for _, hrow in win.iterrows():
            stop_hit = hrow["l"] <= stop if side > 0 else hrow["h"] >= stop
            tp_hit = tp is not None and (hrow["h"] >= tp if side > 0 else hrow["l"] <= tp)
            if stop_hit:                       # conservador: stop gana el empate
                exit_px, hit = stop, "stop"
                break
            if tp_hit:
                exit_px, hit = tp, "tp"
                break
        if exit_px is None:
            exit_px = win.iloc[-1]["c"]
        ret = side * (exit_px / entry - 1) - FEE
        res.append((ret, ret / risk, hit, t))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--cache-dir", default=".cache_1h")
    ap.add_argument("--signals", default="L_A,L_B,S_A,S_B,S_C",
                    help="senales a simular, separadas por coma")
    ap.add_argument("--split", default=None,
                    help="fecha YYYY-MM-DD: separa out-of-sample (antes) de in-sample (despues)")
    a = ap.parse_args()
    split = pd.Timestamp(a.split) if a.split else None

    data = []
    for n, s in enumerate(perp_symbols(a.top), 1):
        try:
            r = build(s, a.days, a.cache_dir)
            if r:
                data.append((s, *r))
        except Exception as ex:
            print(f"{s}: ERROR {ex}", file=sys.stderr, flush=True)
    print(f"{len(data)} pares cargados", file=sys.stderr, flush=True)

    signals = [s.strip() for s in a.signals.split(",")]
    stops = [0.05, 0.08, 0.12, "estructural"]
    tps = [0.15, 0.25, None]

    print("\nLeyenda: exp=retorno neto medio/trade, med=mediana, wr=winrate, "
          "PF=profit factor, R=multiplo de riesgo medio, %stop/%tp/%tiempo=como salio")
    for sname in signals:
        side = 1 if sname.startswith("L") else -1
        total_fires = sum(int(sig[sname].sum()) for _, _, sig, _ in data)
        print(f"\n===== {sname} ({'LARGO' if side>0 else 'CORTO'}) — {total_fires} disparos =====")
        print(f"{'stop':>12s} {'tp':>6s} {'n':>5s} {'exp':>7s} {'med':>7s} {'wr':>6s} "
              f"{'PF':>5s} {'R':>6s} {'%stop':>6s} {'%tp':>5s} {'%tiem':>6s}")
        for stop_kind in stops:
            for tp_pct in tps:
                allr = []
                for _, d, sig, hp in data:
                    fired = sig.index[sig[sname]]
                    allr += simulate(d, hp, fired, side, stop_kind, tp_pct)
                if len(allr) < 20:
                    continue
                periods = [("", allr)]
                if split is not None:
                    periods = [("OOS", [x for x in allr if x[3] < split]),
                               ("IS ", [x for x in allr if x[3] >= split])]
                for plabel, rows in periods:
                    if len(rows) < 15:
                        continue
                    rets = np.array([x[0] for x in rows])
                    rmul = np.array([x[1] for x in rows])
                    hits = [x[2] for x in rows]
                    wins, losses = rets[rets > 0], rets[rets <= 0]
                    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
                    sk = f"{stop_kind:.0%}" if isinstance(stop_kind, float) else stop_kind
                    tk = f"{tp_pct:.0%}" if tp_pct else "no"
                    print(f"{plabel:3s} {sk:>12s} {tk:>6s} {len(rets):>5d} {rets.mean():>+6.2%} {np.median(rets):>+6.2%} "
                          f"{(rets>0).mean():>5.1%} {pf:>5.2f} {rmul.mean():>+5.2f} "
                          f"{hits.count('stop')/len(hits):>5.1%} {hits.count('tp')/len(hits):>4.1%} "
                          f"{hits.count('tiempo')/len(hits):>5.1%}")


if __name__ == "__main__":
    main()
