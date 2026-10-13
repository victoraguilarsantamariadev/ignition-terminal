"""
Amplitud entre exchanges: ¿las igniciones ganadoras meten volumen tambien en
Bybit (estampida global) mientras las basura solo tienen volumen en Binance
(pump local/manipulacion)?

Para cada ignicion: klines 1h de Bybit del mes previo -> volx_bybit (volumen 6h
de la ventana vs su mediana 30d) y cuota de Bybit sobre el volumen conjunto.
Comparacion ganadoras vs basura + examen trade por encima/debajo de mediana.
"""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd
import requests
from scipy.stats import mannwhitneyu

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
BYBIT = "https://api.bybit.com/v5/market/kline"


def bybit_1h(symbol, start_ms, end_ms):
    try:
        r = S.get(BYBIT, params=dict(category="linear", symbol=symbol, interval="60",
                                     start=start_ms, end=end_ms, limit=1000), timeout=20)
        rows = r.json().get("result", {}).get("list") or []
    except Exception:
        return None
    if len(rows) < 200:
        return None
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "turnover"])
    df["t"] = pd.to_datetime(df["t"].astype(np.int64), unit="ms")
    df["turnover"] = df["turnover"].astype(float)
    return df.set_index("t").sort_index()


def main():
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)
    ev = pd.DataFrame(events)
    ev["t"] = pd.to_datetime(ev["t"])
    ev["ganadora"] = ev["fwd_max"] >= 0.40

    volx_b, share_b = [], []
    for n, (_, e) in enumerate(ev.iterrows(), 1):
        t = e["t"]
        bb = bybit_1h(e["symbol"], int((t - pd.Timedelta(days=31)).timestamp() * 1000),
                      int((t + pd.Timedelta(hours=1)).timestamp() * 1000))
        if bb is None or t not in bb.index:
            volx_b.append(np.nan)
            share_b.append(np.nan)
        else:
            vol6 = bb["turnover"].rolling(6).sum()
            med = vol6.iloc[:-6].median()
            vx = vol6.loc[t] / med if med and med > 0 else np.nan
            hp = frames[e["symbol"]]
            i = e["i"]
            bin6 = hp.iloc[i - 5:i + 1]["qv"].sum()
            byb6 = bb["turnover"].loc[:t].tail(6).sum()
            volx_b.append(vx)
            share_b.append(byb6 / (byb6 + bin6) if (byb6 + bin6) > 0 else np.nan)
        if n % 50 == 0:
            print(f"  {n}/{len(ev)}", file=sys.stderr, flush=True)
        time.sleep(0.06)
    ev["volx_bybit"] = volx_b
    ev["share_bybit"] = share_b
    ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
    ev.to_csv("ignitions_bybit.csv", index=False)

    ok = ev.dropna(subset=["volx_bybit"])
    print(f"\n{len(ok)} de {len(ev)} igniciones con datos Bybit")
    g, b = ok[ok["ganadora"]], ok[~ok["ganadora"]]
    for f in ["volx_bybit", "share_bybit"]:
        p = mannwhitneyu(g[f].dropna(), b[f].dropna()).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = ok[(ok["periodo"] == per) & ok["ganadora"]][f].median()
            bm = ok[(ok["periodo"] == per) & ~ok["ganadora"]][f].median()
            dirs.append("+" if gm > bm else "-")
        print(f"  {f:12s} med_GANA={g[f].median():.3f}  med_BASURA={b[f].median():.3f}  "
              f"p={p:.4f}  dir A/B: {dirs[0]}/{dirs[1]}")

    print(f"\nExamen trade (8%/TP40) por amplitud Bybit (volx_bybit sobre/bajo mediana):")
    med = ok["volx_bybit"].median()
    print(f"{'grupo':18s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
    for gname, mask in [("amplia (>=med)", ok["volx_bybit"] >= med),
                        ("estrecha (<med)", ok["volx_bybit"] < med)]:
        rows = {"A": [], "B": []}
        sub = ok[mask]
        for _, e in sub.iterrows():
            r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
            if r:
                rows[e["periodo"]].append(r[0])
        for p in ("A", "B"):
            rr = np.array(rows[p])
            if len(rr) < 20:
                continue
            wins, losses = rr[rr > 0], rr[rr <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            print(f"{gname:18s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")


if __name__ == "__main__":
    main()
