"""
Posicionamiento historico DIARIO (Coinalyze, cobertura completa A+B).

Features SIN lookahead (todo de dias anteriores a la ignicion):
  oi_buildup_5d : OI(D-1) / OI(D-6) - 1        (posiciones apilandose antes)
  oi_chg_prev   : OI(D-1) / OI(D-2) - 1        (aceleracion de OI la vispera)
  liq_short_5d  : liq de cortos D-5..D-1 / mediana diaria del par
  liq_long_5d   : liq de largos D-5..D-1 / mediana diaria del par (capitulacion)
Diagnostico (CON lookahead intradia, no operable, solo para entender):
  oi_chg_dia    : OI(D) / OI(D-1) - 1          (el dia de la ignicion)
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
        time.sleep(1.6)
        return r.json()
    return None


def series_daily(path, ca_sym, col_map, cache_name):
    cache = os.path.join(CACHE, cache_name)
    if os.path.exists(cache):
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    j = get(path, symbols=ca_sym, interval="daily",
            **{"from": int(pd.Timestamp("2023-08-01").timestamp()), "to": int(time.time())})
    if not j or not isinstance(j, list) or not j[0].get("history"):
        return None
    df = pd.DataFrame(j[0]["history"]).drop_duplicates("t")
    df["dt"] = pd.to_datetime(df["t"], unit="s").dt.normalize()
    df = df.set_index("dt").sort_index().rename(columns=col_map)[list(col_map.values())]
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
            ca_map[m["symbol"].split("_PERP")[0].split(".")[0]] = m["symbol"]

    rows = []
    syms = sorted(ev["symbol"].unique())
    for n, sym in enumerate(syms, 1):
        ca = ca_map.get(sym)
        if not ca:
            continue
        oi = series_daily("open-interest-history", ca, {"c": "oi"}, f"{sym}_oid.csv")
        lq = series_daily("liquidation-history", ca, {"l": "liq_long", "s": "liq_short"}, f"{sym}_liqd.csv")
        print(f"[{n}/{len(syms)}] {sym}: oi={'ok '+str(len(oi)) if oi is not None else 'NO'}",
              file=sys.stderr, flush=True)
        if oi is None:
            continue
        o = oi["oi"]
        med_ls = lq["liq_short"].replace(0, np.nan).median() if lq is not None else np.nan
        med_ll = lq["liq_long"].replace(0, np.nan).median() if lq is not None else np.nan
        for _, e in ev[ev["symbol"] == sym].iterrows():
            d0 = pd.Timestamp(e["t"]).normalize()
            def oi_at(days):
                v = o.asof(d0 - pd.Timedelta(days=days))
                return v if np.isfinite(v) and v > 0 else np.nan
            o1, o2, o6, o0 = oi_at(1), oi_at(2), oi_at(6), o.asof(d0)
            if not np.isfinite(o1):
                continue
            row = dict(symbol=sym, t=e["t"], clase=e["clase"],
                       oi_buildup_5d=o1 / o6 - 1 if np.isfinite(o6) else np.nan,
                       oi_chg_prev=o1 / o2 - 1 if np.isfinite(o2) else np.nan,
                       oi_chg_dia=o0 / o1 - 1 if np.isfinite(o0) else np.nan)
            if lq is not None and np.isfinite(med_ls) and np.isfinite(med_ll):
                w5 = lq[(lq.index >= d0 - pd.Timedelta(days=5)) & (lq.index < d0)]
                row["liq_short_5d"] = w5["liq_short"].sum() / (med_ls * 5)
                row["liq_long_5d"] = w5["liq_long"].sum() / (med_ll * 5)
            rows.append(row)

    df = pd.DataFrame(rows)
    df["periodo"] = np.where(pd.to_datetime(df["t"]) < pd.Timestamp("2025-07-30"), "A", "B")
    df.to_csv("positioning_daily.csv", index=False)
    g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
    print(f"\n{len(g)} ganadoras vs {len(b)} basura | por periodo: "
          f"{df.groupby('periodo').size().to_dict()}\n")
    print(f"{'feature':16s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
    for f in ["oi_buildup_5d", "oi_chg_prev", "liq_short_5d", "liq_long_5d", "oi_chg_dia"]:
        aa, bb = g[f].dropna(), b[f].dropna()
        if len(aa) < 40 or len(bb) < 40:
            continue
        pv = mannwhitneyu(aa, bb).pvalue
        dirs = []
        for per in ("A", "B"):
            gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
            bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
            dirs.append("+" if gm > bm else "-")
        tag = " (diagnostico)" if f == "oi_chg_dia" else ""
        print(f"{f:16s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}{tag}")


if __name__ == "__main__":
    main()
