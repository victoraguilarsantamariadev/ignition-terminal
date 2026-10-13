"""
Microscopio 2: el TAPE (aggTrades) de la ventana de ignicion (6h), ganadoras
(+40% en 7d) vs basura (stop sin +40%). ¿Quien empuja en las buenas?

Features del tape de la ventana:
  share_10k / share_50k   cuota del volumen en prints >=10k$ / >=50k$
  imb_10k / imb_50k       imbalance comprador de esos prints (-1..1)
  imb_small               imbalance de prints <1k$ (retail)
  delta_share             delta total / volumen
  avg_trade               tamano medio del print
  max_print               mayor print de la ventana (log10 $)

Muestra: hasta 85 de cada clase, aleatoria (seed fija). MW + direccion A/B.
"""
import glob
import os
import sys
import zipfile

import numpy as np
import pandas as pd
import requests
from scipy.stats import mannwhitneyu

from momentum_ignition import detect, load, SPLIT
from stop_autopsy import clasificar

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
DIR = ".aggtrades"
S = requests.Session()
N_POR_CLASE = 85


def fetch(sym, date):
    fn = f"{sym}-aggTrades-{date}.zip"
    path = os.path.join(DIR, fn)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        return path
    try:
        r = S.get(f"{BASE}/{sym}/{fn}", timeout=120)
    except requests.RequestException:
        return None
    if r.status_code != 200 or len(r.content) < 200:
        return None
    with open(path, "wb") as f:
        f.write(r.content)
    return path


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


def tape_feats(sym, t_start, t_end):
    dates = pd.date_range(t_start.floor("D"), t_end.floor("D"), freq="D")
    parts = []
    for d in dates:
        p = fetch(sym, d.date())
        if p is None:
            return None
        parts.append(read_day(p))
    df = pd.concat(parts, ignore_index=True)
    ms0 = int(t_start.timestamp() * 1000)
    ms1 = int(t_end.timestamp() * 1000)
    df = df[(df["transact_time"] >= ms0) & (df["transact_time"] < ms1)]
    if len(df) < 100:
        return None
    p = df["price"].to_numpy(float)
    q = df["quantity"].to_numpy(float)
    ibm = df["is_buyer_maker"]
    if ibm.dtype == object:
        ibm = ibm.astype(str).str.lower().eq("true").to_numpy()
    else:
        ibm = ibm.to_numpy(bool)
    usd = p * q
    sign = np.where(~ibm, 1.0, -1.0)
    vol = usd.sum()
    out = {"delta_share": (usd * sign).sum() / vol,
           "avg_trade": vol / len(usd),
           "max_print": np.log10(max(usd.max(), 1))}
    for tag, lo in (("10k", 10_000), ("50k", 50_000)):
        m = usd >= lo
        v = usd[m].sum()
        out[f"share_{tag}"] = v / vol
        out[f"imb_{tag}"] = (usd[m] * sign[m]).sum() / v if v > 0 else np.nan
    m = usd < 1_000
    v = usd[m].sum()
    out["imb_small"] = (usd[m] * sign[m]).sum() / v if v > 0 else np.nan
    return out


def main():
    os.makedirs(DIR, exist_ok=True)
    frames, events = {}, []
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)
    gan, bas = [], []
    for e in events:
        c = clasificar(frames[e["symbol"]], e, 0.08, 0.40)
        if c.startswith("ganador"):
            gan.append(e)
        elif c.startswith("perdedor"):
            bas.append(e)
    rng = np.random.default_rng(7)
    rng.shuffle(gan)
    rng.shuffle(bas)
    print(f"{len(gan)} ganadoras, {len(bas)} basura; muestreo {N_POR_CLASE}+{N_POR_CLASE}",
          file=sys.stderr, flush=True)

    rows = []
    for clase, lst in (("ganadora", gan), ("basura", bas)):
        done = 0
        for e in lst:
            if done >= N_POR_CLASE:
                break
            hp = frames[e["symbol"]]
            i = e["i"]
            t0, t1 = hp.index[i - 5], hp.index[i] + pd.Timedelta(hours=1)
            ft = tape_feats(e["symbol"], t0, t1)
            if ft is None:
                continue
            rows.append(dict(clase=clase, symbol=e["symbol"], t=e["t"], **ft))
            done += 1
            print(f"  {clase} {done}/{N_POR_CLASE} {e['symbol']} {e['t']}", file=sys.stderr, flush=True)

    df = pd.DataFrame(rows)
    df.to_csv("ignition_tape.csv", index=False)
    df["periodo"] = np.where(pd.to_datetime(df["t"]) < SPLIT, "A", "B")
    g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
    feats = ["share_10k", "share_50k", "imb_10k", "imb_50k", "imb_small",
             "delta_share", "avg_trade", "max_print"]
    print(f"\n{len(g)} ganadoras vs {len(b)} basura | 8 features -> Bonferroni ~0.006\n")
    print(f"{'feature':12s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
    for f in feats:
        aa, bb = g[f].dropna(), b[f].dropna()
        if len(aa) < 25 or len(bb) < 25:
            continue
        pv = mannwhitneyu(aa, bb).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
            bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
            dirs.append("+" if gm > bm else "-")
        print(f"{f:12s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")
    print("\nCSV: ignition_tape.csv")


if __name__ == "__main__":
    main()
