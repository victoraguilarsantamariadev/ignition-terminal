"""
¿Evaluar el gatillo de ignicion cada 15 min mejora la entrada vs esperar al
cierre de la vela de 1h?

Mismo gatillo (+10%/6h, vol 6h >= 4x mediana 30d, plano 5d, dedupe 72h) sobre
velas de 15m, evaluado de dos formas:
  A) cada cierre de 15m  (dispara antes; puede captar picos intra-hora)
  B) solo en cierres de hora (replica del sistema actual)

Se mide para cada variante: n, P(+25% mas), retorno 7d, ambos periodos; y para
los eventos comunes, cuantos minutos adelanta A sobre B y a que precio entra.
"""
import glob
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
S = requests.Session()
BAR_MS = 900_000
W6H, W5D, W30D = 24, 480, 2880          # barras de 15m
HOLD = 7 * 96                            # 7 dias
SPLIT = pd.Timestamp("2025-07-30")
CACHE = ".cache_15m"


def get(url, **params):
    for _ in range(6):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(3)
            continue
        if r.status_code in (418, 429):
            time.sleep(int(r.headers.get("Retry-After", 10)) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(url)


def klines_15m(symbol, days):
    cache = os.path.join(CACHE, f"{symbol}_15m_{days}.csv.gz")
    if os.path.exists(cache):
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    end = int(time.time() * 1000)
    start = end - days * 96 * BAR_MS
    rows, cursor = [], start
    for _ in range(90):
        if cursor >= end:
            break
        b = get(FAPI + "/fapi/v1/klines", symbol=symbol, interval="15m",
                startTime=cursor, limit=1500)
        if not b:
            break
        rows += b
        if len(b) < 1500:
            break
        cursor = max(b[-1][0] + BAR_MS, cursor + BAR_MS)
        time.sleep(0.22)
    cols = ["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    for k in ["o", "h", "l", "c", "qv"]:
        df[k] = df[k].astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates("t").set_index("t").sort_index()[["o", "h", "l", "c", "qv"]]
    df = df[df.index < pd.Timestamp.now("UTC").tz_localize(None).floor("15min")]
    df.to_csv(cache, compression="gzip")
    return df


def detect(df, hourly_only):
    c, qv = df["c"], df["qv"]
    ret = c / c.shift(W6H) - 1
    vol = qv.rolling(W6H).sum()
    volx = vol / vol.shift(1).rolling(W30D, min_periods=W30D // 2).median()
    flat = (c.shift(W6H) / c.shift(W6H + W5D) - 1).abs() < 0.15
    ign = (ret >= 0.10) & (volx >= 4.0) & flat
    if hourly_only:
        ign = ign & (df.index.minute == 45)  # barra que cierra la hora
    idxs = np.flatnonzero(ign.to_numpy())
    events, last, n = [], -10**9, len(df)
    for i in idxs:
        if i - last < 288 or i + 1 + HOLD >= n or i < W30D + 10:
            continue
        last = i
        entry = df.iloc[i + 1]["o"]
        fwd = df.iloc[i + 1:i + 1 + HOLD]
        events.append(dict(
            t=df.index[i], entry=entry,
            fwd_max=fwd["h"].max() / entry - 1,
            fwd_ret=df.iloc[i + HOLD]["c"] / entry - 1,
        ))
    return events


def stats(evs, label):
    for per, lo, hi in [("A", pd.Timestamp("2000-01-01"), SPLIT),
                        ("B", SPLIT, pd.Timestamp("2100-01-01"))]:
        sub = [e for e in evs if lo <= e["t"] < hi]
        if len(sub) < 30:
            continue
        fm = np.array([e["fwd_max"] for e in sub])
        fr = np.array([e["fwd_ret"] for e in sub])
        print(f"  {label:12s} {per}: n={len(sub):>5d}  P(+25%)={(fm>=0.25).mean():.1%}  "
              f"P(+40%)={(fm>=0.40).mean():.1%}  fwd_ret {fr.mean():+.2%}")


def main():
    os.makedirs(CACHE, exist_ok=True)
    syms = sorted({os.path.basename(f).split("_")[0]
                   for f in glob.glob(".cache_1h/*_perp_1h_1100.csv")})
    ev15, ev1h = [], []
    for n, sym in enumerate(syms, 1):
        try:
            df = klines_15m(sym, 1100)
            if len(df) < 200 * 96:
                print(f"[{n}/{len(syms)}] {sym}: historia corta, skip", file=sys.stderr, flush=True)
                continue
            a = detect(df, hourly_only=False)
            b = detect(df, hourly_only=True)
            for e in a:
                e["symbol"] = sym
            for e in b:
                e["symbol"] = sym
            ev15 += a
            ev1h += b
            print(f"[{n}/{len(syms)}] {sym}: 15m={len(a)} 1h={len(b)}", file=sys.stderr, flush=True)
        except Exception as ex:
            print(f"[{n}/{len(syms)}] {sym}: ERROR {ex}", file=sys.stderr, flush=True)

    print("=" * 76)
    print(f"Mismo gatillo evaluado cada 15m vs solo al cierre de hora ({len(syms)} pares):")
    stats(ev15, "cada 15m")
    stats(ev1h, "cierre 1h")

    # emparejar eventos comunes (mismo simbolo, 15m dispara <=2h antes del 1h)
    adv, px_adv = [], []
    b_by_sym = {}
    for e in ev1h:
        b_by_sym.setdefault(e["symbol"], []).append(e)
    for e in ev15:
        for eb in b_by_sym.get(e["symbol"], []):
            dt = (eb["t"] - e["t"]).total_seconds() / 60
            if 0 <= dt <= 120:
                adv.append(dt)
                px_adv.append(eb["entry"] / e["entry"] - 1)
                break
    if adv:
        print(f"\nEventos comunes: {len(adv)} — el 15m adelanta una mediana de "
              f"{np.median(adv):.0f} min y entra un {np.median(px_adv):+.1%} mas barato (mediana)")
    print("\ncache: .cache_15m (gzip)")


if __name__ == "__main__":
    main()
