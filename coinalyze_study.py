"""
Capa de POSICIONAMIENTO historico (Coinalyze) sobre las 1.011 igniciones.

Features por evento (definidas antes de mirar, todas conocibles al entrar):
  oi_chg_ign    : OI al cierre de la ignicion / OI 6h antes - 1
                  (>0 dinero nuevo entra; <0 cierre de posiciones/cortos)
  oi_buildup_5d : OI 6h antes / OI 5 dias antes - 1 (posiciones apiladas)
  liq_short_ign : liquidaciones de CORTOS en la ventana de ignicion,
                  normalizadas por la mediana horaria del par (gasolina quemada)
  liq_long_5d   : liquidaciones de largos 5d previos (capitulacion previa)

Comparacion ganadoras (fwd_max>=40%) vs basura (fwd_max<10%), split A/B.
Rate limit Coinalyze: 40 llamadas/min -> sleep 1.6s.
"""
import os
import sys
import time

import numpy as np
import pandas as pd
import requests
from scipy.stats import mannwhitneyu

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY = open(".coinalyze_key").read().strip()
S = requests.Session()
S.headers["api_key"] = KEY
BASE = "https://api.coinalyze.net/v1"
CACHE = ".cache_coinalyze"
os.makedirs(CACHE, exist_ok=True)


def get(path, **params):
    for _ in range(6):
        r = S.get(f"{BASE}/{path}", params=params, timeout=40)
        if r.status_code == 429:
            time.sleep(20)
            continue
        if r.status_code != 200:
            return None
        time.sleep(1.6)  # 40/min
        return r.json()
    return None


def series(path, ca_sym, col_map, cache_name):
    cache = os.path.join(CACHE, cache_name)
    if os.path.exists(cache):
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    frm = int(pd.Timestamp("2023-08-01").timestamp())
    to = int(time.time())
    rows, cursor = [], frm
    for _ in range(30):
        j = get(path, symbols=ca_sym, interval="1hour", **{"from": cursor, "to": to})
        if not j or not isinstance(j, list) or not j[0].get("history"):
            break
        h = j[0]["history"]
        rows += h
        last = h[-1]["t"]
        if last >= to - 7200 or len(h) < 100:
            break
        cursor = last + 3600
    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates("t")
    df["dt"] = pd.to_datetime(df["t"], unit="s")
    df = df.set_index("dt").sort_index()
    df = df.rename(columns=col_map)[list(col_map.values())]
    df.to_csv(cache)
    return df


def main():
    ev = pd.read_csv("ignitions.csv", parse_dates=["t"])
    ev["clase"] = np.where(ev["fwd_max"] >= 0.40, "ganadora",
                           np.where(ev["fwd_max"] < 0.10, "basura", "media"))
    ev = ev[ev["clase"] != "media"]

    mk = get("future-markets") or []
    exch = get("exchanges") or []
    bcode = next((e["code"] for e in exch if e["name"].lower() == "binance"), "A")
    ca_map = {}
    for m in mk:
        if m.get("is_perpetual") and m.get("exchange") == bcode and m.get("symbol", "").endswith("." + bcode):
            base_sym = m["symbol"].split("_PERP")[0].split(".")[0]
            ca_map[base_sym] = m["symbol"]
    print(f"{len(ca_map)} perps de Binance en Coinalyze", file=sys.stderr, flush=True)

    rows = []
    syms = sorted(ev["symbol"].unique())
    for n, sym in enumerate(syms, 1):
        ca = ca_map.get(sym)
        if not ca:
            print(f"[{n}/{len(syms)}] {sym}: no mapeado", file=sys.stderr, flush=True)
            continue
        oi = series("open-interest-history", ca, {"c": "oi"}, f"{sym}_oi.csv")
        lq = series("liquidation-history", ca, {"l": "liq_long", "s": "liq_short"}, f"{sym}_liq.csv")
        print(f"[{n}/{len(syms)}] {sym}: oi={'ok' if oi is not None else 'NO'} "
              f"liq={'ok' if lq is not None else 'NO'}", file=sys.stderr, flush=True)
        if oi is None:
            continue
        med_ls = lq["liq_short"].replace(0, np.nan).median() if lq is not None else np.nan
        med_ll = lq["liq_long"].replace(0, np.nan).median() if lq is not None else np.nan
        for _, e in ev[ev["symbol"] == sym].iterrows():
            t0 = pd.Timestamp(e["t"])
            o = oi["oi"]
            try:
                oi_t0 = o.asof(t0)
                oi_6h = o.asof(t0 - pd.Timedelta(hours=6))
                oi_5d = o.asof(t0 - pd.Timedelta(hours=126))
            except Exception:
                continue
            if not (np.isfinite(oi_t0) and np.isfinite(oi_6h) and oi_6h > 0):
                continue
            row = dict(symbol=sym, t=e["t"], clase=e["clase"],
                       oi_chg_ign=oi_t0 / oi_6h - 1,
                       oi_buildup_5d=oi_6h / oi_5d - 1 if np.isfinite(oi_5d) and oi_5d > 0 else np.nan)
            if lq is not None and np.isfinite(med_ls):
                w = lq[(lq.index > t0 - pd.Timedelta(hours=6)) & (lq.index <= t0)]
                w5 = lq[(lq.index > t0 - pd.Timedelta(hours=126)) & (lq.index <= t0 - pd.Timedelta(hours=6))]
                row["liq_short_ign"] = w["liq_short"].sum() / (med_ls * 6)
                row["liq_long_5d"] = w5["liq_long"].sum() / (med_ll * 120) if np.isfinite(med_ll) else np.nan
            rows.append(row)

    df = pd.DataFrame(rows)
    df["periodo"] = np.where(pd.to_datetime(df["t"]) < pd.Timestamp("2025-07-30"), "A", "B")
    df.to_csv("positioning_study.csv", index=False)
    g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
    print(f"\n{len(g)} ganadoras vs {len(b)} basura con datos de posicionamiento\n")
    print(f"{'feature':14s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
    for f in ["oi_chg_ign", "oi_buildup_5d", "liq_short_ign", "liq_long_5d"]:
        if f not in df:
            continue
        aa, bb = g[f].dropna(), b[f].dropna()
        if len(aa) < 30 or len(bb) < 30:
            continue
        pv = mannwhitneyu(aa, bb).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
            bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
            dirs.append("+" if gm > bm else "-")
        print(f"{f:14s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")
    # cuadrantes de OI: dinero nuevo vs cierre de cortos
    print("\nP(ganadora) por tipo de ignicion (cuadrante de OI), por periodo:")
    df["tipo_oi"] = pd.cut(df["oi_chg_ign"], [-np.inf, -0.02, 0.03, np.inf],
                           labels=["cierre posiciones", "neutral", "dinero nuevo"])
    for (per, q), gg in df.groupby(["periodo", "tipo_oi"], observed=True):
        if len(gg) < 15:
            continue
        print(f"  {per} {str(q):18s} n={len(gg):>4d}  P(ganadora)={(gg['clase']=='ganadora').mean():.1%}")


if __name__ == "__main__":
    main()
