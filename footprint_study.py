"""
Estudio caso-control EMPAREJADO del footprint previo a explosiones (+40%/7d).

Para cada explosion: descarga los aggTrades (todos los trades ejecutados) del
perpetuo en los 5 dias previos (D-4..D, la explosion empieza despues de D) y
lo mismo para un dia de control del MISMO par. Compara pares evento-control
con test de Wilcoxon (pareado).

Features del tape (ventana de 5 dias):
  vol_usd       volumen total                                   [log-ratio]
  n_trades      numero de trades                                [log-ratio]
  avg_trade     tamano medio del print                          [log-ratio]
  share_10k/50k fraccion del volumen en prints >=10k$ / >=50k$
  imb_10k/50k   imbalance comprador de los prints grandes (-1..1)
  imb_small     imbalance de prints <1k$ (retail)
  delta_share   delta total / volumen
  rango_5d      rango de precio de la ventana (volatilidad)
  absorcion     volumen / rango                                 [log-ratio]
  conc_precio   max fraccion del volumen en un bucket de 0.5% de precio
  trend_imb10k  pendiente diaria del imbalance grande (¿creciendo hacia D?)
  vol_ultimo_d  volumen del dia D / dia D-4                     [log-ratio]
  ret_ventana   retorno dentro de la ventana (control de deriva)

Uso: python footprint_study.py --n 50
"""
import argparse
import os
import sys
import zipfile

import numpy as np
import pandas as pd
import requests
from scipy.stats import wilcoxon

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
DIR = ".aggtrades"
S = requests.Session()


def fetch(sym, date):
    fn = f"{sym}-aggTrades-{date}.zip"
    path = os.path.join(DIR, fn)
    if os.path.exists(path) and os.path.getsize(path) > 200:
        return path
    try:
        r = S.get(f"{BASE}/{sym}/{fn}", timeout=90)
    except requests.RequestException:
        return None
    if r.status_code != 200 or len(r.content) < 200:
        return None
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def day_feats(path):
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            head = fh.read(64)
        hdr = head.startswith(b"agg")
        with z.open(name) as fh:
            if hdr:
                df = pd.read_csv(fh, usecols=["price", "quantity", "is_buyer_maker"])
            else:
                df = pd.read_csv(fh, header=None, usecols=[1, 2, 6],
                                 names=["price", "quantity", "is_buyer_maker"][0:3] if False else None)
                df.columns = ["price", "quantity", "is_buyer_maker"]
    if df.empty:
        return None
    p = df["price"].to_numpy(float)
    q = df["quantity"].to_numpy(float)
    ibm = df["is_buyer_maker"]
    if ibm.dtype == object:
        ibm = ibm.astype(str).str.lower().eq("true").to_numpy()
    else:
        ibm = ibm.to_numpy(bool)
    usd = p * q
    sign = np.where(~ibm, 1.0, -1.0)  # taker compra si el buyer NO es maker
    out = {"vol": usd.sum(), "n": len(usd), "delta": (usd * sign).sum(),
           "pmax": p.max(), "pmin": p.min(), "pfirst": p[0], "plast": p[-1]}
    for tag, lo in (("10k", 10_000), ("50k", 50_000)):
        m = usd >= lo
        out[f"v{tag}"] = usd[m].sum()
        out[f"d{tag}"] = (usd[m] * sign[m]).sum()
    m = usd < 1_000
    out["vsm"] = usd[m].sum()
    out["dsm"] = (usd[m] * sign[m]).sum()
    med = np.median(p)
    b = np.round(p / (0.005 * med)).astype(np.int64)
    out["hist"] = pd.Series(usd).groupby(b).sum()
    return out


def window_feats(sym, d0):
    days = []
    for k in range(4, -1, -1):
        path = fetch(sym, (d0 - pd.Timedelta(days=k)).date())
        if path is None:
            return None
        f = day_feats(path)
        if f is None:
            return None
        days.append(f)
    vol = sum(x["vol"] for x in days)
    n = sum(x["n"] for x in days)
    if vol <= 0 or n == 0:
        return None
    v10 = sum(x["v10k"] for x in days); d10 = sum(x["d10k"] for x in days)
    v50 = sum(x["v50k"] for x in days); d50 = sum(x["d50k"] for x in days)
    vsm = sum(x["vsm"] for x in days); dsm = sum(x["dsm"] for x in days)
    pmax = max(x["pmax"] for x in days); pmin = min(x["pmin"] for x in days)
    rng = (pmax - pmin) / ((pmax + pmin) / 2)
    hist = pd.concat([x["hist"] for x in days]).groupby(level=0).sum()
    imb_d = [x["d10k"] / x["v10k"] if x["v10k"] > 0 else np.nan for x in days]
    valid = [(i, v) for i, v in enumerate(imb_d) if np.isfinite(v)]
    trend = np.polyfit([i for i, _ in valid], [v for _, v in valid], 1)[0] if len(valid) >= 3 else np.nan
    return dict(
        vol_usd=vol, n_trades=n, avg_trade=vol / n,
        share_10k=v10 / vol, share_50k=v50 / vol,
        imb_10k=d10 / v10 if v10 > 0 else np.nan,
        imb_50k=d50 / v50 if v50 > 0 else np.nan,
        imb_small=dsm / vsm if vsm > 0 else np.nan,
        delta_share=sum(x["delta"] for x in days) / vol,
        rango_5d=rng, absorcion=vol / max(rng, 1e-4),
        conc_precio=hist.max() / vol, trend_imb10k=trend,
        vol_ultimo_d=days[-1]["vol"] / max(days[0]["vol"], 1),
        ret_ventana=days[-1]["plast"] / days[0]["pfirst"] - 1,
    )


LOG_FEATS = {"vol_usd", "n_trades", "avg_trade", "absorcion", "vol_ultimo_d"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)

    ev = pd.read_csv("explosions.csv", parse_dates=["date"]).sample(frac=1, random_state=7)
    ct = pd.read_csv("controls.csv", parse_dates=["date"])
    pairs = []
    for _, row in ev.iterrows():
        if len(pairs) >= a.n:
            break
        wf = window_feats(row["symbol"], row["date"])
        if wf is None:
            continue
        cands = ct[ct["symbol"] == row["symbol"]].sample(frac=1, random_state=len(pairs) + 1)
        cf, cdate = None, None
        for _, cr in cands.head(6).iterrows():
            cf = window_feats(row["symbol"], cr["date"])
            if cf is not None:
                cdate = cr["date"]
                break
        if cf is None:
            continue
        pairs.append(dict(symbol=row["symbol"], ev_date=row["date"].date(),
                          ct_date=cdate.date(), fwd_max=row["fwd_max"],
                          **{f"ev_{k}": v for k, v in wf.items()},
                          **{f"ct_{k}": v for k, v in cf.items()}))
        print(f"[{len(pairs)}/{a.n}] {row['symbol']} {row['date'].date()} ok",
              file=sys.stderr, flush=True)

    df = pd.DataFrame(pairs)
    df.to_csv("footprint_pairs.csv", index=False)
    feats = [c[3:] for c in df.columns if c.startswith("ev_") and c != "ev_date"]

    print(f"\n{'='*86}")
    print(f"{len(df)} pares explosion-control (mismo activo) | ventana: 5 dias previos al arranque")
    print(f"{'feature':14s} {'mediana_EXPL':>13s} {'mediana_CTRL':>13s} {'%expl>ctrl':>10s} {'p-Wilcoxon':>11s}")
    results = []
    for f in feats:
        aa = df[f"ev_{f}"].to_numpy(float)
        bb = df[f"ct_{f}"].to_numpy(float)
        ok = np.isfinite(aa) & np.isfinite(bb)
        aa, bb = aa[ok], bb[ok]
        if len(aa) < 15:
            continue
        diff = np.log(np.maximum(aa, 1e-12) / np.maximum(bb, 1e-12)) if f in LOG_FEATS else aa - bb
        nz = diff[diff != 0]
        p = wilcoxon(nz).pvalue if len(nz) >= 10 else np.nan
        share = (diff > 0).mean()
        results.append((f, np.median(aa), np.median(bb), share, p))
    results.sort(key=lambda x: (np.isnan(x[4]), x[4]))
    for f, ma, mb, share, p in results:
        fmt = "{:>13.3g} {:>13.3g}" if abs(ma) > 100 or abs(ma) < 0.01 else "{:>13.4f} {:>13.4f}"
        print(f"{f:14s} " + fmt.format(ma, mb) + f" {share:>9.0%} {p:>11.4f}")
    print("\nCSV de pares: footprint_pairs.csv")
    print("Nota: 13 features testeadas -> umbral honesto de significancia ~0.004 (Bonferroni).")


if __name__ == "__main__":
    main()
