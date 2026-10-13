"""
Huella de CADENCIA (TWAP/VWAP) en la ventana de ignicion.

  burstiness   : (std-media)/(std+media) del volumen comprador POR MINUTO.
                 Multitud viral = rafagas (alto). TWAP dominante = liso (bajo).
  cv_gaps_2k   : coef. de variacion de los intervalos entre compras >=2k$.
                 TWAP = cadencia mecanica (bajo). Humanos = irregular (alto).
  smooth_share : fraccion de minutos con volumen comprador dentro de +-50% de
                 la mediana del propio evento (cuanto mas liso, mas alto).

Ganadoras vs basura, split A/B. Tapes ya cacheados (.aggtrades).
"""
import sys
import zipfile

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from ignition_tape import fetch
from momentum_ignition import SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def read_day(path):
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            head = fh.read(64)
        hdr = head.startswith(b"agg")
        with z.open(name) as fh:
            if hdr:
                df = pd.read_csv(fh, usecols=["price", "quantity", "transact_time", "is_buyer_maker"])
            else:
                df = pd.read_csv(fh, header=None, usecols=[1, 2, 5, 6])
                df.columns = ["price", "quantity", "transact_time", "is_buyer_maker"]
    return df


def cadence(sym, t0):
    t_start, t_end = t0 - pd.Timedelta(hours=6), t0 + pd.Timedelta(hours=1)
    parts = []
    for d in pd.date_range(t_start.floor("D"), t_end.floor("D"), freq="D"):
        p = fetch(sym, d.date())
        if p is None:
            return None
        parts.append(read_day(p))
    df = pd.concat(parts, ignore_index=True)
    ms0, ms1 = int(t_start.timestamp() * 1000), int(t_end.timestamp() * 1000)
    df = df[(df["transact_time"] >= ms0) & (df["transact_time"] < ms1)]
    if len(df) < 300:
        return None
    ibm = df["is_buyer_maker"]
    if ibm.dtype == object:
        ibm = ibm.astype(str).str.lower().eq("true")
    buys = df[~ibm.to_numpy()].copy()
    if len(buys) < 100:
        return None
    buys["usd"] = buys["price"].astype(float) * buys["quantity"].astype(float)
    buys["minuto"] = buys["transact_time"] // 60000
    per_min = buys.groupby("minuto")["usd"].sum()
    idx = np.arange(per_min.index.min(), per_min.index.max() + 1)
    per_min = per_min.reindex(idx, fill_value=0.0)
    mu, sd = per_min.mean(), per_min.std()
    burst = (sd - mu) / (sd + mu) if (sd + mu) > 0 else np.nan
    med = per_min[per_min > 0].median()
    smooth = ((per_min >= 0.5 * med) & (per_min <= 1.5 * med)).mean()
    big = buys[buys["usd"] >= 2000].sort_values("transact_time")
    cvg = np.nan
    if len(big) >= 20:
        gaps = np.diff(big["transact_time"].to_numpy()) / 1000.0
        gaps = gaps[gaps > 0]
        if len(gaps) >= 10 and gaps.mean() > 0:
            cvg = gaps.std() / gaps.mean()
    return dict(burstiness=burst, smooth_share=smooth, cv_gaps_2k=cvg)


def main():
    prev = pd.read_csv("ignition_tape.csv", parse_dates=["t"])
    rows = []
    for n, (_, e) in enumerate(prev.iterrows(), 1):
        ft = cadence(e["symbol"], pd.Timestamp(e["t"]))
        if ft:
            rows.append(dict(clase=e["clase"], t=e["t"], symbol=e["symbol"], **ft))
        if n % 25 == 0:
            print(f"  {n}/{len(prev)}", file=sys.stderr, flush=True)
    df = pd.DataFrame(rows)
    df["periodo"] = np.where(pd.to_datetime(df["t"]) < SPLIT, "A", "B")
    df.to_csv("algo_cadence.csv", index=False)
    g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
    print(f"\n{len(g)} ganadoras vs {len(b)} basura\n")
    print(f"{'feature':14s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
    for f in ["burstiness", "smooth_share", "cv_gaps_2k"]:
        aa, bb = g[f].dropna(), b[f].dropna()
        if len(aa) < 25 or len(bb) < 25:
            continue
        pv = mannwhitneyu(aa, bb).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
            bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
            dirs.append("+" if gm > bm else "-")
        print(f"{f:14s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")


if __name__ == "__main__":
    main()
