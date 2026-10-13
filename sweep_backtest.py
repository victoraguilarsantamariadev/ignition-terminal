"""
Backtest de "liquidity sweep + absorcion" en altcoins con perpetuo USDT en Binance.

Evento (dos variantes, --mode any las combina):
  - wick : el minimo del dia rompe el minimo de N dias previos pero el cierre
           recupera el nivel en la misma vela (el sweep clasico).
  - close: cierre por debajo del minimo de N dias y cierre de vuelta por encima
           en <= 2 velas siguientes.

Features en el dia del sweep (todas calculadas SOLO con datos previos o del
propio dia del evento; las medias/desviaciones moviles excluyen la vela actual):
  - vol_z        : z-score del volumen perp (ventana 60d, sin la vela actual)
  - absorcion_z  : z-score de volumen/rango (alto = mucho volumen, poco movimiento)
  - delta_perp   : (taker buy - taker sell) / volumen de la vela del sweep
  - cvd_spot_5d  : suma del delta spot de los 5 dias previos (compra real, no apalancada)
  - funding_3d   : funding medio de los 3 dias previos

score = z(vol_z) + z(absorcion_z) - z(delta_perp) - z(funding_3d) + z(cvd_spot_5d)
Se reporta en dos versiones: in-sample (z sobre toda la muestra, optimista) y
expanding (z solo con eventos anteriores en el tiempo, replicable en real).

Grupo de control: mismos pares, dias aleatorios sin evento, mismos retornos forward.
Bootstrap por SIMBOLO (no por evento) para el IC95 del ret_10d de Q4.

Uso:
  python sweep_backtest.py --top 100 --days 700 --mode any
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAPI = "https://fapi.binance.com"
SAPI = "https://api.binance.com"
S = requests.Session()
DAY_MS = 86_400_000


def get(url, **params):
    for attempt in range(6):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (418, 429):
            wait = int(r.headers.get("Retry-After", 10))
            time.sleep(wait + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"fallo persistente en {url}")


def klines(base, symbol, days, cache_dir):
    """Klines 1d paginados. Futures admite limit=1500, spot limit=1000."""
    kind = "perp" if base == FAPI else "spot"
    path = "/fapi/v1/klines" if base == FAPI else "/api/v3/klines"
    max_limit = 1500 if base == FAPI else 1000
    cache = os.path.join(cache_dir, f"{symbol}_{kind}_{days}.csv")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return df

    end = int(time.time() * 1000)
    start = end - days * DAY_MS
    rows = []
    cursor = start
    while cursor < end:
        batch = get(base + path, symbol=symbol, interval="1d",
                    startTime=cursor, limit=max_limit)
        if not batch:
            break
        rows += batch
        last_open = batch[-1][0]
        if len(batch) < max_limit:
            break
        cursor = last_open + DAY_MS
        time.sleep(0.1)

    cols = ["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]
    df = pd.DataFrame(rows, columns=cols)
    for k in ["o", "h", "l", "c", "v", "tbv"]:
        df[k] = df[k].astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates(subset="t").set_index("t").sort_index()
    df["delta"] = (2 * df["tbv"] - df["v"]) / df["v"].replace(0, np.nan)  # -1..1
    df = df[["o", "h", "l", "c", "v", "delta"]]
    # descarta la vela de hoy (incompleta)
    df = df[df.index < pd.Timestamp.now("UTC").tz_localize(None).normalize()]
    df.to_csv(cache)
    return df


def funding(symbol, days, cache_dir):
    """Funding paginado (1000 registros/llamada = ~333 dias)."""
    cache = os.path.join(cache_dir, f"{symbol}_funding_{days}.csv")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        return s
    end = int(time.time() * 1000)
    start = end - days * DAY_MS
    rows, cursor = [], start
    while cursor < end:
        batch = get(FAPI + "/fapi/v1/fundingRate", symbol=symbol,
                    startTime=cursor, limit=1000)
        if not batch:
            break
        rows += batch
        last = batch[-1]["fundingTime"]
        if len(batch) < 1000:
            break
        cursor = last + 1
        time.sleep(0.1)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(r["fundingRate"]) for r in rows],
                  index=pd.to_datetime([r["fundingTime"] for r in rows], unit="ms"))
    s = s.resample("1D").mean()
    s.to_frame("funding").to_csv(cache)
    return s


def perp_symbols(top):
    info = get(FAPI + "/fapi/v1/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"]
            if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"]
    tick = {t["symbol"]: float(t["quoteVolume"]) for t in get(FAPI + "/fapi/v1/ticker/24hr")}
    syms = sorted(syms, key=lambda x: -tick.get(x, 0.0))
    return [s for s in syms if s not in ("BTCUSDT", "ETHUSDT")][:top]


def build_features(p, sp, fr):
    """Features sin look-ahead: las ventanas moviles excluyen la vela actual."""
    p = p.copy()
    p["prior_low"] = p["l"].shift(1).rolling(LOOKBACK).min()
    v_prev = p["v"].shift(1)
    p["vol_z"] = (p["v"] - v_prev.rolling(60).mean()) / v_prev.rolling(60).std()
    rng = ((p["h"] - p["l"]) / p["c"]).replace(0, np.nan)
    absor = p["v"] / rng
    a_prev = absor.shift(1)
    p["absorcion_z"] = (absor - a_prev.rolling(60).mean()) / a_prev.rolling(60).std()
    if sp is not None and len(sp):
        p["cvd_spot_5d"] = sp["delta"].reindex(p.index).shift(1).rolling(5).sum()
    else:
        p["cvd_spot_5d"] = np.nan
    if len(fr):
        p["funding_3d"] = fr.reindex(p.index).shift(1).rolling(3).mean()
    else:
        p["funding_3d"] = np.nan
    return p


def events_for(symbol, days, mode, cache_dir, recover=2):
    p = klines(FAPI, symbol, days, cache_dir)
    if len(p) < LOOKBACK + 75:
        return [], None
    try:
        sp = klines(SAPI, symbol, days, cache_dir)
    except Exception:
        sp = None
    fr = funding(symbol, days, cache_dir)
    p = build_features(p, sp, fr)

    out, taken = [], set()
    i = max(LOOKBACK, 61)
    n = len(p)
    while i < n:
        row = p.iloc[i]
        pl = row["prior_low"]
        if not np.isfinite(pl) or row["l"] >= pl:
            i += 1
            continue
        rec = None
        kind = None
        if mode in ("wick", "any") and row["c"] > pl:
            rec, kind = i, "wick"
        elif mode in ("close", "any") and row["c"] < pl:
            for k in range(1, recover + 1):
                if i + k < n and p.iloc[i + k]["c"] > pl:
                    rec, kind = i + k, "close"
                    break
        if rec is None or rec + 10 >= n:
            i += 1
            continue
        entry = p.iloc[rec]["c"]
        out.append(dict(
            symbol=symbol, date=p.index[i].date(), kind=kind, entry=entry,
            vol_z=row["vol_z"], absorcion_z=row["absorcion_z"],
            delta_perp=row["delta"], cvd_spot_5d=row["cvd_spot_5d"],
            funding_3d=row["funding_3d"],
            ret_3d=p.iloc[rec + 3]["c"] / entry - 1,
            ret_5d=p.iloc[rec + 5]["c"] / entry - 1,
            ret_10d=p.iloc[rec + 10]["c"] / entry - 1,
            max_10d=p.iloc[rec + 1:rec + 11]["h"].max() / entry - 1,
            min_10d=p.iloc[rec + 1:rec + 11]["l"].min() / entry - 1,
        ))
        taken.update(range(i, rec + 11))
        i = rec + 1
    # grupo de control: dias aleatorios del mismo par, fuera de las ventanas de evento
    rng_ = np.random.default_rng(abs(hash(symbol)) % (2**32))
    eligible = [j for j in range(max(LOOKBACK, 61), n - 10) if j not in taken]
    ctrl = []
    if eligible and out:
        pick = rng_.choice(eligible, size=min(len(out), len(eligible)), replace=False)
        for j in pick:
            e = p.iloc[j]["c"]
            ctrl.append(dict(symbol=symbol,
                             ret_3d=p.iloc[j + 3]["c"] / e - 1,
                             ret_5d=p.iloc[j + 5]["c"] / e - 1,
                             ret_10d=p.iloc[j + 10]["c"] / e - 1))
    return out, ctrl


def expanding_z(df, col):
    """z-score usando solo eventos ANTERIORES en el tiempo (min 30 previos)."""
    vals = df[col].to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        prev = vals[:i]
        prev = prev[np.isfinite(prev)]
        if len(prev) >= 30 and np.isfinite(vals[i]):
            sd = prev.std()
            if sd > 0:
                out[i] = (vals[i] - prev.mean()) / sd
    return out


def bootstrap_ci(df, col, n_iter=1000, seed=7):
    """IC95 de la media, remuestreando simbolos enteros."""
    rng_ = np.random.default_rng(seed)
    syms = df["symbol"].unique()
    groups = {s: g[col].to_numpy() for s, g in df.groupby("symbol")}
    means = []
    for _ in range(n_iter):
        sample = rng_.choice(syms, size=len(syms), replace=True)
        vals = np.concatenate([groups[s] for s in sample])
        means.append(np.nanmean(vals))
    return np.percentile(means, [2.5, 97.5])


def main():
    global LOOKBACK
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--days", type=int, default=700)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--mode", choices=["wick", "close", "any"], default="any")
    ap.add_argument("--out", default="sweeps.csv")
    ap.add_argument("--cache-dir", default=".cache_binance")
    a = ap.parse_args()
    LOOKBACK = a.lookback
    os.makedirs(a.cache_dir, exist_ok=True)

    ev, ctrl = [], []
    symbols = perp_symbols(a.top)
    for n, s in enumerate(symbols, 1):
        try:
            e, c = events_for(s, a.days, a.mode, a.cache_dir)
            ev += e
            if c:
                ctrl += c
            print(f"[{n}/{len(symbols)}] {s}: {len(e)} sweeps", file=sys.stderr, flush=True)
        except Exception as ex:
            print(f"[{n}/{len(symbols)}] {s}: ERROR {ex}", file=sys.stderr, flush=True)
        time.sleep(0.15)

    df = pd.DataFrame(ev)
    if df.empty:
        print("sin eventos")
        return
    df = df.sort_values("date").reset_index(drop=True)
    cf = pd.DataFrame(ctrl)

    # cobertura de features
    feats = ["vol_z", "absorcion_z", "delta_perp", "cvd_spot_5d", "funding_3d"]
    cov = df[feats].notna().mean()

    # score in-sample (optimista) y expanding (replicable)
    zin = lambda c: ((df[c] - df[c].mean()) / df[c].std()).fillna(0)
    df["score_in"] = (zin("vol_z") + zin("absorcion_z") - zin("delta_perp")
                      - zin("funding_3d") + zin("cvd_spot_5d"))
    zexp = {c: expanding_z(df, c) for c in feats}
    df["score_exp"] = (np.nan_to_num(zexp["vol_z"]) + np.nan_to_num(zexp["absorcion_z"])
                       - np.nan_to_num(zexp["delta_perp"]) - np.nan_to_num(zexp["funding_3d"])
                       + np.nan_to_num(zexp["cvd_spot_5d"]))
    # marca los eventos sin historial suficiente para el expanding
    warm = np.isfinite(zexp["vol_z"])
    df.to_csv(a.out, index=False)

    print(f"\n{'='*72}")
    print(f"{len(df)} sweeps en {df.symbol.nunique()} pares | modo={a.mode} | "
          f"lookback={a.lookback}d | {a.days} dias")
    print(f"por tipo: {df['kind'].value_counts().to_dict()}")
    print(f"\nCobertura de features (fraccion de eventos con dato):")
    print(cov.round(3).to_string())

    print(f"\nBaseline (grupo de control, {len(cf)} dias aleatorios mismos pares):")
    if not cf.empty:
        print(cf[["ret_3d", "ret_5d", "ret_10d"]].agg(["mean", "median"]).round(4).to_string())
    print(f"\nTodos los sweeps (sin filtrar por score):")
    print(df[["ret_3d", "ret_5d", "ret_10d", "max_10d", "min_10d"]]
          .agg(["mean", "median"]).round(4).to_string())

    # IC de cada feature con ret_10d (Spearman)
    print(f"\nCorrelacion Spearman de cada feature con ret_10d:")
    for c in feats:
        sub = df[[c, "ret_10d"]].dropna()
        if len(sub) > 30:
            ic = sub[c].rank().corr(sub["ret_10d"].rank())
            print(f"  {c:14s} {ic:+.3f}  (n={len(sub)})")

    for label, col, sub in [("SCORE IN-SAMPLE (optimista)", "score_in", df),
                            ("SCORE EXPANDING (replicable)", "score_exp", df[warm])]:
        if len(sub) < 40:
            print(f"\n{label}: muestra insuficiente ({len(sub)})")
            continue
        sub = sub.copy()
        sub["q"] = pd.qcut(sub[col], 4, labels=["Q1 bajo", "Q2", "Q3", "Q4 alto"])
        res = sub.groupby("q", observed=True)[["ret_3d", "ret_5d", "ret_10d", "max_10d"]].mean()
        med = sub.groupby("q", observed=True)["ret_10d"].median().rename("med_10d")
        win = sub.groupby("q", observed=True)["ret_10d"].apply(lambda x: (x > 0).mean()).rename("winrate_10d")
        nn = sub.groupby("q", observed=True).size().rename("n")
        print(f"\n{label} — {len(sub)} eventos, por cuartil:")
        print(pd.concat([res, med, win, nn], axis=1).round(4).to_string())
        q4 = sub[sub["q"] == "Q4 alto"]
        q1 = sub[sub["q"] == "Q1 bajo"]
        lo, hi = bootstrap_ci(q4, "ret_10d")
        print(f"  Q4 ret_10d medio: {q4['ret_10d'].mean():+.4f}  IC95 bootstrap-por-simbolo [{lo:+.4f}, {hi:+.4f}]")
        print(f"  Spread Q4-Q1 ret_10d: {q4['ret_10d'].mean() - q1['ret_10d'].mean():+.4f}")

    print(f"\nCSV: {a.out}")
    print("Avisos: universo = perpetuos vivos hoy (sesgo de supervivencia); sin comisiones/slippage.")


if __name__ == "__main__":
    LOOKBACK = 20
    main()
