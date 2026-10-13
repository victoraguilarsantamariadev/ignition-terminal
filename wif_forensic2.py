"""Fase 2: anclar el analisis en el MINIMO real (el sweep del grafico),
no en la pata final. Usa los CSVs ya descargados + funding/ratios."""
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
SYM = "WIFUSDT"
H_MS = 3_600_000


def get(url, **params):
    r = S.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def ratio(path, col):
    end = int(time.time() * 1000)
    start = end - 29 * 24 * H_MS
    rows, cursor = [], start
    for _ in range(10):
        if cursor >= end:
            break
        b = get(FAPI + path, symbol=SYM, period="1h",
                startTime=cursor, endTime=min(cursor + 499 * H_MS, end), limit=500)
        if not b:
            cursor += 499 * H_MS
            continue
        rows += b
        cursor = max(b[-1]["timestamp"] + H_MS, cursor + H_MS)
        time.sleep(0.1)
    df = pd.DataFrame(rows).drop_duplicates("timestamp")
    df["t"] = pd.to_datetime(df["timestamp"], unit="ms")
    df[col] = df["longShortRatio" if "Position" in path else "buySellRatio"].astype(float)
    return df.set_index("t")[col].sort_index()


perp = pd.read_csv("wif_perp_1h.csv", index_col=0, parse_dates=True)
spot = pd.read_csv("wif_spot_1h.csv", index_col=0, parse_dates=True)
oi = pd.read_csv("wif_oi_1h.csv", index_col=0, parse_dates=True)["oi"]

end = int(time.time() * 1000)
fr_rows = get(FAPI + "/fapi/v1/fundingRate", symbol=SYM, startTime=end - 35 * 24 * H_MS, limit=1000)
fr = pd.Series([float(r["fundingRate"]) for r in fr_rows],
               index=pd.to_datetime([r["fundingTime"] for r in fr_rows], unit="ms"))
top_pos = ratio("/futures/data/topLongShortPositionRatio", "top_ls")

# ---- el suelo real ----
last30 = perp.tail(30 * 24)
t_low = last30["l"].idxmin()
p_low = last30.loc[t_low, "l"]
print("=" * 70)
print(f"SUELO REAL: {t_low} UTC  minimo {p_low:.4f}")

# ---- pelicula hora a hora: 6h antes del minimo a 18h despues ----
print(f"\n[A] HORA A HORA alrededor del minimo (delta en k$, OI en % vs hora del minimo)")
oi_h = oi.reindex(perp.index).interpolate(limit=3)
oi0 = oi_h.loc[t_low]
i_low = perp.index.get_loc(t_low)
print(f"{'hora':>17s} {'cierre':>8s} {'ret1h':>7s} {'dPerp':>8s} {'dSpot':>8s} {'OI%':>7s}")
for j in range(i_low - 6, i_low + 19):
    t = perp.index[j]
    r = perp.iloc[j]
    ds = spot["delta_usd"].reindex([t]).iloc[0] if t in spot.index else np.nan
    oi_chg = (oi_h.loc[t] / oi0 - 1) * 100 if np.isfinite(oi_h.loc[t]) else np.nan
    mark = " <== MINIMO" if t == t_low else ""
    print(f"{str(t)[:16]:>17s} {r['c']:8.4f} {(r['c']/r['o']-1)*100:+6.1f}% "
          f"{r['delta_usd']/1e3:+8.0f} {ds/1e3:+8.0f} {oi_chg:+6.1f}%{mark}")

# ---- OI en horizonte largo desde el suelo ----
print(f"\n[B] OI Y PRECIO desde el suelo (la rally completa)")
for h in (6, 12, 24, 48, 72, 120):
    t = t_low + pd.Timedelta(hours=h)
    if t in oi_h.index and np.isfinite(oi_h.loc[t]):
        px = perp["c"].reindex([t]).iloc[0] / p_low - 1
        print(f"  +{h:3d}h: OI {(oi_h.loc[t]/oi0-1)*100:+6.1f}%  precio {px*100:+6.1f}%")
oi_pre = oi_h.loc[:t_low].dropna()
if len(oi_pre) > 48:
    print(f"  OI en los 2 dias previos al suelo: {(oi_pre.iloc[-1]/oi_pre.iloc[-48]-1)*100:+.1f}%")

# ---- acumulacion previa ----
print(f"\n[C] LOS 5 DIAS ANTES DEL SUELO")
pre = slice(t_low - pd.Timedelta(days=5), t_low - pd.Timedelta(hours=1))
dp, vp = perp.loc[pre, "delta_usd"].sum(), perp.loc[pre, "qv"].sum()
ds_, vs = spot.loc[pre, "delta_usd"].sum(), spot.loc[pre, "qv"].sum()
print(f"  CVD perp: {dp/1e6:+.2f}M$ ({dp/vp*100:+.1f}% del vol) | CVD spot: {ds_/1e6:+.2f}M$ ({ds_/vs*100:+.1f}% del vol)")
fr_pre = fr[(fr.index > t_low - pd.Timedelta(days=3)) & (fr.index <= t_low)]
fr_post = fr[(fr.index > t_low) & (fr.index <= t_low + pd.Timedelta(days=3))]
print(f"  funding 3d antes: {fr_pre.mean()*100:+.4f}%/periodo | 3d despues: {fr_post.mean()*100:+.4f}%/periodo")
tp_pre = top_pos.loc[:t_low].tail(72)
tp_post = top_pos.loc[t_low:].head(72)
print(f"  top traders L/S: 3d antes {tp_pre.mean():.2f} -> 3d despues {tp_post.mean():.2f}")

# ---- quien empujo la rally 0.1357 -> 0.20 (los 4 dias post-suelo) ----
print(f"\n[D] LA RALLY COMPLETA (suelo -> +4 dias): ¿quien compro?")
post = slice(t_low, t_low + pd.Timedelta(days=4))
dp2, vp2 = perp.loc[post, "delta_usd"].sum(), perp.loc[post, "qv"].sum()
ds2, vs2 = spot.loc[post, "delta_usd"].sum(), spot.loc[post, "qv"].sum()
print(f"  delta perp: {dp2/1e6:+.2f}M$ ({dp2/vp2*100:+.1f}% del vol {vp2/1e6:.0f}M$)")
print(f"  delta spot: {ds2/1e6:+.2f}M$ ({ds2/vs2*100:+.1f}% del vol {vs2/1e6:.0f}M$)")
