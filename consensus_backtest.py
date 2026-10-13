"""
Backtest de CONSENSO de firmas de "mano grande" en altcoins (Binance perp USDT).

En cada dia y cada par se evaluan 8 formulas independientes (datos 1h agregados,
todas calculadas solo con informacion disponible al cierre del dia):

  F1_sweep      : barrido del minimo de 20d recuperado en la vela + volumen z>1
  F2_absorcion  : alguna hora del dia con delta agresor z<-2.5 que cierra plana
                  o verde (venta masiva absorbida), con precio a <5% del minimo 20d
  F3_divergencia: precio +3% o mas en 2 dias con CVD perp negativo (comprador pasivo)
  F4_grind      : >=60%% de las ultimas 48 horas cierran verdes con CVD 48h negativo
                  (la firma de WIF: subida sostenida sin compra agresiva)
  F5_spot_lidera: CVD spot 5d con z>0.5 mientras CVD perp 5d tiene z<0
  F6_squeeze    : funding medio 3d negativo con precio a <10%% del minimo 20d
  F7_compresion : rango 10d en percentil <20 de 120d + volumen secandose (Wyckoff)
  F8_basis      : perp cotizando con descuento >=0.05%% vs spot cerca de minimos

Objetivo: P(el maximo de los 7 dias siguientes >= +25%%) y retornos forward,
por formula individual y por nivel de consenso (numero de formulas activas).

Anti-trampas: ventanas moviles excluyen el dia actual; "disparo" = la condicion
pasa de falsa a verdadera (no se cuentan rachas); bootstrap por simbolo.

Uso: python consensus_backtest.py --top 100 --days 400
"""
import argparse
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
H_MS = 3_600_000
TARGET = 0.25          # subida "gigante": +25% en el maximo de los 7d siguientes
FWD = 7                # dias forward


def get(url, **params):
    for attempt in range(6):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (418, 429):
            time.sleep(int(r.headers.get("Retry-After", 10)) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"fallo persistente {url}")


def klines_1h(base, symbol, days, cache_dir):
    kind = "perp" if base == FAPI else "spot"
    path = "/fapi/v1/klines" if base == FAPI else "/api/v3/klines"
    max_limit = 1500 if base == FAPI else 1000
    cache = os.path.join(cache_dir, f"{symbol}_{kind}_1h_{days}.csv")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    end = int(time.time() * 1000)
    start = end - days * 24 * H_MS
    rows, cursor = [], start
    for _ in range(60):
        if cursor >= end:
            break
        b = get(base + path, symbol=symbol, interval="1h", startTime=cursor, limit=max_limit)
        if not b:
            break
        rows += b
        if len(b) < max_limit:
            break
        cursor = max(b[-1][0] + H_MS, cursor + H_MS)
        time.sleep(0.08)
    cols = ["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    for k in ["o", "h", "l", "c", "qv", "tbqv"]:
        df[k] = df[k].astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates("t").set_index("t").sort_index()
    df["delta"] = 2 * df["tbqv"] - df["qv"]
    df = df[["o", "h", "l", "c", "qv", "delta"]]
    df = df[df.index < pd.Timestamp.now("UTC").tz_localize(None).floor("h")]
    df.to_csv(cache)
    return df


def funding(symbol, days, cache_dir):
    cache = os.path.join(cache_dir, f"{symbol}_funding_{days}.csv")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        return pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
    end = int(time.time() * 1000)
    start = end - days * 24 * H_MS
    rows, cursor = [], start
    for _ in range(10):
        if cursor >= end:
            break
        b = get(FAPI + "/fapi/v1/fundingRate", symbol=symbol, startTime=cursor, limit=1000)
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cursor = max(b[-1]["fundingTime"] + 1, cursor + 1)
        time.sleep(0.08)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([float(r["fundingRate"]) for r in rows],
                  index=pd.to_datetime([r["fundingTime"] for r in rows], unit="ms"))
    s = s.resample("1D").mean()
    s.to_frame("f").to_csv(cache)
    return s


def perp_symbols(top):
    info = get(FAPI + "/fapi/v1/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"]
            if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"]
    tick = {t["symbol"]: float(t["quoteVolume"]) for t in get(FAPI + "/fapi/v1/ticker/24hr")}
    syms = sorted(syms, key=lambda x: -tick.get(x, 0.0))
    return [s for s in syms if s not in ("BTCUSDT", "ETHUSDT")][:top]


def zshift(s, win, minp):
    prev = s.shift(1)
    return (s - prev.rolling(win, min_periods=minp).mean()) / prev.rolling(win, min_periods=minp).std()


def features_for(symbol, days, cache_dir):
    hp = klines_1h(FAPI, symbol, days, cache_dir)
    if hp.empty or len(hp) < 100 * 24:
        return None
    try:
        hs = klines_1h(SAPI, symbol, days, cache_dir)
    except Exception:
        hs = pd.DataFrame()
    fr = funding(symbol, days, cache_dir)

    # ---- señales horarias ----
    hp = hp.copy()
    hp["delta_z"] = zshift(hp["delta"], 24 * 30, 24 * 10)
    hp["absorb_h"] = (hp["delta_z"] < -2.5) & (hp["c"] >= hp["o"])
    hp["up"] = (hp["c"] > hp["o"]).astype(float)
    hp["up_share_48"] = hp["up"].rolling(48).mean()
    hp["cvd_48"] = hp["delta"].rolling(48).sum()

    # ---- agregado diario ----
    d = pd.DataFrame({
        "o": hp["o"].resample("1D").first(),
        "h": hp["h"].resample("1D").max(),
        "l": hp["l"].resample("1D").min(),
        "c": hp["c"].resample("1D").last(),
        "qv": hp["qv"].resample("1D").sum(),
        "delta": hp["delta"].resample("1D").sum(),
        "nh": hp["c"].resample("1D").count(),
        "absorb_day": hp["absorb_h"].resample("1D").max(),
        "up_share_48": hp["up_share_48"].resample("1D").last(),
        "cvd_48": hp["cvd_48"].resample("1D").last(),
    })
    d = d[d["nh"] >= 20].drop(columns="nh")
    if len(d) < 150:
        return None
    if not hs.empty:
        d["delta_spot"] = hs["delta"].resample("1D").sum().reindex(d.index)
        d["c_spot"] = hs["c"].resample("1D").last().reindex(d.index)
    else:
        d["delta_spot"] = np.nan
        d["c_spot"] = np.nan
    d["funding"] = fr.reindex(d.index)

    # ---- features (sin mirar el futuro) ----
    low20 = d["l"].shift(1).rolling(20).min()
    d["near_low"] = d["c"] / low20 - 1
    d["vol_z"] = zshift(d["qv"], 60, 30)
    d["ret_2d"] = d["c"].pct_change(2)
    d["cvd_2d"] = d["delta"].rolling(2).sum()
    cvd5p = d["delta"].rolling(5).sum()
    cvd5s = d["delta_spot"].rolling(5).sum()
    d["cvd5p_z"] = zshift(cvd5p, 60, 30)
    d["cvd5s_z"] = zshift(cvd5s, 60, 30)
    d["funding_3d"] = d["funding"].shift(1).rolling(3).mean()
    rng10 = (d["h"].rolling(10).max() - d["l"].rolling(10).min()) / d["c"]
    d["rng_pctl"] = rng10.rolling(120, min_periods=60).rank(pct=True)
    d["vol_dry"] = d["qv"].rolling(5).mean() / d["qv"].rolling(20).mean()
    d["basis_3d"] = (d["c"] / d["c_spot"] - 1).rolling(3).mean()

    # ---- las 8 formulas ----
    F = pd.DataFrame(index=d.index)
    F["F1_sweep"] = (d["l"] < low20) & (d["c"] > low20) & (d["vol_z"] > 1)
    F["F2_absorcion"] = d["absorb_day"].astype(bool) & (d["near_low"] < 0.05)
    F["F3_divergencia"] = (d["ret_2d"] > 0.03) & (d["cvd_2d"] < 0)
    F["F4_grind"] = (d["up_share_48"] >= 0.60) & (d["cvd_48"] < 0)
    F["F5_spot_lidera"] = (d["cvd5s_z"] > 0.5) & (d["cvd5p_z"] < 0)
    F["F6_squeeze"] = (d["funding_3d"] < -0.0001) & (d["near_low"] < 0.10)
    F["F7_compresion"] = (d["rng_pctl"] < 0.20) & (d["vol_dry"] < 0.7) & (d["near_low"] < 0.15)
    F["F8_basis"] = (d["basis_3d"] < -0.0005) & (d["near_low"] < 0.10)
    F = F.fillna(False)

    # ---- outcomes forward ----
    out = pd.DataFrame(index=d.index)
    out["fwd_max"] = d["h"].rolling(FWD).max().shift(-FWD) / d["c"] - 1
    out["fwd_min"] = d["l"].rolling(FWD).min().shift(-FWD) / d["c"] - 1
    out["fwd_ret"] = d["c"].shift(-FWD) / d["c"] - 1
    out["target"] = out["fwd_max"] >= TARGET

    res = pd.concat([F, out], axis=1)
    res["symbol"] = symbol
    res["consenso"] = F.sum(axis=1)
    # descarta warm-up y dias sin forward completo
    res = res.iloc[65:].dropna(subset=["fwd_max"])
    return res


def bootstrap_p(df, n_iter=800, seed=7):
    rng = np.random.default_rng(seed)
    syms = df["symbol"].unique()
    groups = {s: g["target"].to_numpy(dtype=float) for s, g in df.groupby("symbol")}
    ps = []
    for _ in range(n_iter):
        pick = rng.choice(syms, size=len(syms), replace=True)
        vals = np.concatenate([groups[s] for s in pick])
        ps.append(vals.mean())
    return np.percentile(ps, [2.5, 97.5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--out", default="consensus.csv")
    ap.add_argument("--cache-dir", default=".cache_1h")
    a = ap.parse_args()
    os.makedirs(a.cache_dir, exist_ok=True)

    frames = []
    symbols = perp_symbols(a.top)
    for n, s in enumerate(symbols, 1):
        try:
            r = features_for(s, a.days, a.cache_dir)
            if r is not None:
                frames.append(r)
            print(f"[{n}/{len(symbols)}] {s}: {'ok ' + str(len(r)) + 'd' if r is not None else 'skip'}",
                  file=sys.stderr, flush=True)
        except Exception as ex:
            print(f"[{n}/{len(symbols)}] {s}: ERROR {ex}", file=sys.stderr, flush=True)
    df = pd.concat(frames)
    df.to_csv(a.out)

    fcols = [c for c in df.columns if c.startswith("F")]
    base_p = df["target"].mean()
    print("\n" + "=" * 78)
    print(f"{len(df)} dias-par en {df['symbol'].nunique()} pares | objetivo: max 7d >= +{TARGET:.0%}")
    print(f"BASELINE: P(subida gigante) = {base_p:.3%} | fwd_ret medio {df['fwd_ret'].mean():+.2%} "
          f"| fwd_max medio {df['fwd_max'].mean():+.2%}")

    print(f"\n--- FORMULAS INDIVIDUALES (solo disparos nuevos: pasa de off a on) ---")
    print(f"{'formula':16s} {'n':>6s} {'P(target)':>10s} {'lift':>6s} {'fwd_ret':>8s} {'fwd_max':>8s} {'fwd_min':>8s}")
    for c in fcols:
        new = df[c] & ~df.groupby("symbol")[c].shift(1).fillna(False).astype(bool)
        sub = df[new]
        if len(sub) < 20:
            print(f"{c:16s} {len(sub):>6d}   (muestra insuficiente)")
            continue
        p = sub["target"].mean()
        print(f"{c:16s} {len(sub):>6d} {p:>9.2%} {p/base_p:>5.1f}x {sub['fwd_ret'].mean():>+7.2%} "
              f"{sub['fwd_max'].mean():>+7.2%} {sub['fwd_min'].mean():>+7.2%}")

    print(f"\n--- CONSENSO (numero de formulas activas a la vez, disparos nuevos) ---")
    print(f"{'nivel':16s} {'n':>6s} {'P(target)':>10s} {'lift':>6s} {'fwd_ret':>8s} {'fwd_max':>8s} {'fwd_min':>8s}  IC95 P(target)")
    for k in (1, 2, 3, 4):
        cond = df["consenso"] >= k
        new = cond & ~cond.groupby(df["symbol"]).shift(1).fillna(False).astype(bool)
        sub = df[new]
        if len(sub) < 15:
            print(f"consenso >= {k:d}    {len(sub):>6d}   (muestra insuficiente)")
            continue
        p = sub["target"].mean()
        lo, hi = bootstrap_p(sub)
        print(f"consenso >= {k:d}    {len(sub):>6d} {p:>9.2%} {p/base_p:>5.1f}x {sub['fwd_ret'].mean():>+7.2%} "
              f"{sub['fwd_max'].mean():>+7.2%} {sub['fwd_min'].mean():>+7.2%}  [{lo:.2%}, {hi:.2%}]")

    print(f"\n--- COMBINACIONES DE 2 FORMULAS (top 10 por lift, min 30 disparos) ---")
    combos = []
    for i in range(len(fcols)):
        for j in range(i + 1, len(fcols)):
            cond = df[fcols[i]] & df[fcols[j]]
            new = cond & ~cond.groupby(df["symbol"]).shift(1).fillna(False).astype(bool)
            sub = df[new]
            if len(sub) >= 30:
                combos.append((fcols[i], fcols[j], len(sub), sub["target"].mean(),
                               sub["fwd_ret"].mean(), sub["fwd_max"].mean()))
    combos.sort(key=lambda x: -x[3])
    for f1, f2, n, p, fret, fmax in combos[:10]:
        print(f"  {f1} + {f2:16s} n={n:<5d} P={p:.2%} ({p/base_p:.1f}x) fwd_ret {fret:+.2%} fwd_max {fmax:+.2%}")

    print(f"\nCSV completo: {a.out}")
    print("Avisos: sesgo de supervivencia (solo perps vivos hoy); sin costes; "
          "target basado en el maximo (no ejecutable sin regla de salida).")


if __name__ == "__main__":
    main()
