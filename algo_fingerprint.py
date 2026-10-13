"""
¿Hay huella de OPERADOR ALGORITMICO (ordenes troceadas) en las igniciones?

Una multitud real produce tamanos de trade caoticos. Un operador con TWAP/
iceberg reutiliza clips: tamanos exactos repetidos, poca diversidad.

Features por ventana de ignicion (t0-6h..t0), de los tapes ya cacheados:
  top_size_share : cuota del volumen en EL tamano de orden mas repetido
  dup_share      : cuota del volumen en tamanos que se repiten >=20 veces
  uniq_ratio     : tamanos unicos / numero de trades (1 = caos total)
  consec_same    : fraccion de trades consecutivos con tamano identico

Comparacion ganadoras vs basura (mismas 170 del estudio del tape), split A/B.
"""
import os
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


def read_day_q(path):
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            head = fh.read(64)
        hdr = head.startswith(b"agg")
        with z.open(name) as fh:
            if hdr:
                df = pd.read_csv(fh, usecols=["price", "quantity", "transact_time"])
            else:
                df = pd.read_csv(fh, header=None, usecols=[1, 2, 5])
                df.columns = ["price", "quantity", "transact_time"]
    return df


def fingerprint(sym, t0):
    t_start, t_end = t0 - pd.Timedelta(hours=6), t0 + pd.Timedelta(hours=1)
    parts = []
    for d in pd.date_range(t_start.floor("D"), t_end.floor("D"), freq="D"):
        p = fetch(sym, d.date())
        if p is None:
            return None
        parts.append(read_day_q(p))
    df = pd.concat(parts, ignore_index=True)
    ms0, ms1 = int(t_start.timestamp() * 1000), int(t_end.timestamp() * 1000)
    df = df[(df["transact_time"] >= ms0) & (df["transact_time"] < ms1)]
    if len(df) < 200:
        return None
    q = df["quantity"].to_numpy(float)
    usd = q * df["price"].to_numpy(float)
    vol = usd.sum()
    vc = pd.Series(q).value_counts()
    sizes_vol = pd.Series(usd).groupby(pd.Series(q).values).sum()
    top_size_share = sizes_vol.max() / vol
    rep = vc[vc >= 20].index
    dup_share = sizes_vol.loc[sizes_vol.index.isin(rep)].sum() / vol if len(rep) else 0.0
    uniq_ratio = len(vc) / len(q)
    consec_same = (q[1:] == q[:-1]).mean()
    return dict(top_size_share=top_size_share, dup_share=dup_share,
                uniq_ratio=uniq_ratio, consec_same=consec_same)


def main():
    prev = pd.read_csv("ignition_tape.csv", parse_dates=["t"])
    rows = []
    for n, (_, e) in enumerate(prev.iterrows(), 1):
        ft = fingerprint(e["symbol"], pd.Timestamp(e["t"]))
        if ft:
            rows.append(dict(clase=e["clase"], t=e["t"], symbol=e["symbol"], **ft))
        if n % 25 == 0:
            print(f"  {n}/{len(prev)}", file=sys.stderr, flush=True)
    df = pd.DataFrame(rows)
    df["periodo"] = np.where(pd.to_datetime(df["t"]) < SPLIT, "A", "B")
    df.to_csv("algo_fingerprint.csv", index=False)
    g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
    print(f"\n{len(g)} ganadoras vs {len(b)} basura\n")
    print(f"{'feature':16s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
    for f in ["top_size_share", "dup_share", "uniq_ratio", "consec_same"]:
        aa, bb = g[f].dropna(), b[f].dropna()
        pv = mannwhitneyu(aa, bb).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
            bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
            dirs.append("+" if gm > bm else "-")
        print(f"{f:16s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")


if __name__ == "__main__":
    main()
