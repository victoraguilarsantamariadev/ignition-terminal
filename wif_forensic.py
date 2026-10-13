"""
Autopsia del movimiento de WIFUSDT: ¿quien inicio el pump y como estaba
posicionado el mercado antes?

Datos (todos gratis, API publica de Binance):
  - klines 1h perp y spot (delta agresor por vela via taker-buy volume)
  - open interest horario (solo ultimos 30 dias)
  - funding
  - topLongShortPositionRatio (posicion de las cuentas top, 30 dias)
  - takerlongshortRatio (agresion compradora/vendedora global, 30 dias)

Logica del veredicto en el pump:
  - OI CAE mientras el precio sube fuerte  -> cierre de cortos (squeeze)
  - OI SUBE mientras el precio sube fuerte -> dinero nuevo entrando largo
  - CVD spot sube antes que el perp        -> compra real previa (acumulacion)
"""
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
SYM = "WIFUSDT"
H_MS = 3_600_000


def get(url, **params):
    print(f"  GET {url.split('binance.com')[1]} {params.get('startTime','')}", file=sys.stderr, flush=True)
    for attempt in range(5):
        r = S.get(url, params=params, timeout=30)
        if r.status_code in (418, 429):
            time.sleep(int(r.headers.get("Retry-After", 10)) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(url)


def klines_1h(base, days):
    path = "/fapi/v1/klines" if base == FAPI else "/api/v3/klines"
    max_limit = 1500 if base == FAPI else 1000
    end = int(time.time() * 1000)
    start = end - days * 24 * H_MS
    rows, cursor = [], start
    for _ in range(20):
        if cursor >= end:
            break
        b = get(base + path, symbol=SYM, interval="1h", startTime=cursor, limit=max_limit)
        if not b:
            break
        rows += b
        if len(b) < max_limit:
            break
        cursor = max(b[-1][0] + H_MS, cursor + H_MS)
        time.sleep(0.1)
    cols = ["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"]
    df = pd.DataFrame(rows, columns=cols)
    for k in ["o", "h", "l", "c", "v", "qv", "tbv", "tbqv"]:
        df[k] = df[k].astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.drop_duplicates("t").set_index("t").sort_index()
    # delta en USDT: compras agresivas - ventas agresivas
    df["delta_usd"] = 2 * df["tbqv"] - df["qv"]
    return df[["o", "h", "l", "c", "v", "qv", "delta_usd"]]


def oi_hist():
    end = int(time.time() * 1000)
    start = end - 29 * 24 * H_MS
    rows, cursor = [], start
    for _ in range(20):
        if cursor >= end:
            break
        b = get(FAPI + "/futures/data/openInterestHist", symbol=SYM, period="1h",
                startTime=cursor, endTime=min(cursor + 499 * H_MS, end), limit=500)
        if not b:
            cursor += 499 * H_MS
            continue
        rows += b
        cursor = max(b[-1]["timestamp"] + H_MS, cursor + H_MS)
        time.sleep(0.1)
    df = pd.DataFrame(rows).drop_duplicates("timestamp")
    df["t"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["oi"] = df["sumOpenInterest"].astype(float)
    df["oi_usd"] = df["sumOpenInterestValue"].astype(float)
    return df.set_index("t")[["oi", "oi_usd"]].sort_index()


def ratio(path, field_num, field_den=None, col="ratio"):
    end = int(time.time() * 1000)
    start = end - 29 * 24 * H_MS
    rows, cursor = [], start
    for _ in range(20):
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
    if field_den:
        df[col] = df[field_num].astype(float) / df[field_den].astype(float)
    else:
        df[col] = df[field_num].astype(float)
    return df.set_index("t")[[col]].sort_index()


def funding(days):
    end = int(time.time() * 1000)
    start = end - days * 24 * H_MS
    rows = get(FAPI + "/fapi/v1/fundingRate", symbol=SYM, startTime=start, limit=1000)
    s = pd.Series([float(r["fundingRate"]) for r in rows],
                  index=pd.to_datetime([r["fundingTime"] for r in rows], unit="ms"))
    return s


def fmt_usd(x):
    return f"{x/1e6:+.2f}M$" if abs(x) >= 1e6 else f"{x/1e3:+.0f}k$"


def main():
    perp = klines_1h(FAPI, 35)
    spot = klines_1h(SAPI, 35)
    oi = oi_hist()
    fr = funding(35)
    top_pos = ratio("/futures/data/topLongShortPositionRatio", "longShortRatio", col="top_ls")
    taker = ratio("/futures/data/takerlongshortRatio", "buySellRatio", col="taker_bs")

    # ---- localizar el pump: mejor retorno en ventana de 24h ----
    r24 = perp["c"].pct_change(24)
    peak_t = r24.idxmax()
    # inicio: primera hora de la racha alcista que culmina en peak_t
    win = perp.loc[:peak_t].tail(48)
    ret1h = win["c"].pct_change()
    # inicio = hora dentro de las 24 previas al pico con mayor salto
    start_t = ret1h.tail(24).idxmax()
    i0 = perp.index.get_loc(start_t)
    pump = perp.iloc[i0:i0 + 12]  # primeras 12h del movimiento

    print("=" * 70)
    print(f"MOVIMIENTO DETECTADO en {SYM}")
    print(f"  mejor retorno 24h: {r24.max()*100:+.1f}%  (fin: {peak_t} UTC)")
    print(f"  vela de ignicion:  {start_t} UTC  ({ret1h[start_t]*100:+.1f}% en 1h)")
    print(f"  precio: {perp.loc[start_t,'o']:.4f} -> {perp.loc[peak_t,'c']:.4f}")

    # ---- 1) ¿squeeze o dinero nuevo? OI durante las primeras horas ----
    print("\n[1] OPEN INTEREST (¿cierre de cortos o entradas nuevas?)")
    oi_w = oi.reindex(perp.index).interpolate(limit=2)
    if start_t in oi_w.index and np.isfinite(oi_w.loc[start_t, "oi"]):
        oi_start = oi_w.loc[start_t, "oi"]
        for h in (3, 6, 12, 24):
            t = start_t + pd.Timedelta(hours=h)
            if t in oi_w.index and np.isfinite(oi_w.loc[t, "oi"]):
                chg = oi_w.loc[t, "oi"] / oi_start - 1
                px = perp["c"].reindex([t]).iloc[0] / perp.loc[start_t, "o"] - 1
                print(f"  +{h:2d}h: OI {chg*100:+6.1f}%  | precio {px*100:+6.1f}%")
        oi_pre5d = oi_w["oi"].loc[:start_t].tail(120)
        if len(oi_pre5d) > 24:
            print(f"  OI 5 dias antes del pump: {oi_pre5d.iloc[-1]/oi_pre5d.iloc[0]-1:+.1%}"
                  f"  (cortos apilandose si sube con precio cayendo)")
    else:
        print("  (el movimiento cae fuera de la ventana de 30d del historico de OI)")

    # ---- 2) ¿quien fue el agresor en la ignicion? spot vs perp ----
    print("\n[2] AGRESION EN LA IGNICION (primeras 6h): ¿spot o perp?")
    p6 = perp.iloc[i0:i0 + 6]
    s6 = spot.reindex(p6.index)
    print(f"  delta perp 6h: {fmt_usd(p6['delta_usd'].sum())}  sobre volumen {fmt_usd(p6['qv'].sum())}")
    print(f"  delta spot 6h: {fmt_usd(s6['delta_usd'].sum())}  sobre volumen {fmt_usd(s6['qv'].sum())}")

    # ---- 3) ¿acumulacion previa? CVD spot vs perp en los 5 dias antes ----
    print("\n[3] LOS 5 DIAS PREVIOS (¿acumulacion en spot?)")
    pre = slice(start_t - pd.Timedelta(days=5), start_t - pd.Timedelta(hours=1))
    dp, ds = perp.loc[pre, "delta_usd"].sum(), spot.loc[pre, "delta_usd"].sum()
    vp, vs = perp.loc[pre, "qv"].sum(), spot.loc[pre, "qv"].sum()
    px_pre = perp.loc[pre, "c"]
    print(f"  precio en esos 5d: {px_pre.iloc[0]:.4f} -> {px_pre.iloc[-1]:.4f} ({px_pre.iloc[-1]/px_pre.iloc[0]-1:+.1%})")
    print(f"  CVD perp: {fmt_usd(dp)}  ({dp/vp*100:+.1f}% del volumen)")
    print(f"  CVD spot: {fmt_usd(ds)}  ({ds/vs*100:+.1f}% del volumen)")
    basis = (perp.loc[pre, "c"] / spot.loc[pre, "c"].reindex(px_pre.index) - 1) * 100
    print(f"  basis perp-spot medio: {basis.mean():+.3f}%  (negativo = perp descontado, cortos presionando)")

    # ---- 4) funding y posicionamiento top traders ----
    print("\n[4] FUNDING Y TOP TRADERS antes del pump")
    fr_pre = fr[(fr.index > start_t - pd.Timedelta(days=3)) & (fr.index <= start_t)]
    print(f"  funding medio 3d antes: {fr_pre.mean()*100:+.4f}% por periodo"
          f" ({fr_pre.mean()*3*365*100:+.0f}% anualizado)")
    for name, df_r, col in [("top traders long/short (posiciones)", top_pos, "top_ls"),
                            ("taker buy/sell global", taker, "taker_bs")]:
        r = df_r[col]
        pre_v = r.loc[:start_t].tail(72).mean()
        base_v = r.loc[:start_t - pd.Timedelta(days=7)].tail(240).mean()
        at_v = r.reindex([start_t]).iloc[0] if start_t in r.index else np.nan
        print(f"  {name}: 3d antes {pre_v:.3f} | baseline previa {base_v:.3f} | en ignicion {at_v:.3f}")

    # ---- 5) tamano medio de trade (proxy de manos grandes sin aggTrades) ----
    print("\n[5] TAMANO MEDIO POR TRADE (volumen/num_trades, proxy de prints grandes)")
    raw = get(FAPI + "/fapi/v1/klines", symbol=SYM, interval="1h",
              startTime=int((start_t - pd.Timedelta(days=7)).timestamp() * 1000), limit=1500)
    dfn = pd.DataFrame(raw, columns=["t","o","h","l","c","v","ct","qv","n","tbv","tbqv","x"])
    dfn["t"] = pd.to_datetime(dfn["t"], unit="ms")
    dfn = dfn.set_index("t")
    dfn["avg_trade"] = dfn["qv"].astype(float) / dfn["n"].astype(int).replace(0, np.nan)
    base_sz = dfn["avg_trade"].loc[:start_t - pd.Timedelta(days=1)].mean()
    ign_sz = dfn["avg_trade"].loc[start_t:start_t + pd.Timedelta(hours=6)].mean()
    pre_sz = dfn["avg_trade"].loc[start_t - pd.Timedelta(days=1):start_t].mean()
    print(f"  baseline 7d: {base_sz:,.0f}$ | 24h previas: {pre_sz:,.0f}$ | ignicion 6h: {ign_sz:,.0f}$")

    perp.to_csv("wif_perp_1h.csv"); spot.to_csv("wif_spot_1h.csv"); oi.to_csv("wif_oi_1h.csv")
    print("\nCSVs: wif_perp_1h.csv, wif_spot_1h.csv, wif_oi_1h.csv")


if __name__ == "__main__":
    main()
