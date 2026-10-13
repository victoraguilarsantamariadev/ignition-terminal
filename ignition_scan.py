"""
Escaner EN VIVO de igniciones en todos los perpetuos USDT de Binance.

Regla (la misma del backtest momentum_ignition.py, computable en tiempo real):
  - ret 6h >= +10%
  - volumen 6h >= 4x su mediana de 30 dias
  - venia plano: |ret 5d previos| < 15%
  - sin otra ignicion en las 72h anteriores

Para cada ignicion de las ultimas HORAS_VENTANA horas imprime: cuando disparo,
precio actual, cuanto ha corrido ya desde la deteccion, calidad de la chispa
(delta agresor: "compra agresiva" continuo mejor en el backtest), stop
estructural y 8%, TP de referencia +40%, y tamano de posicion para RIESGO_PCT
de una cuenta CUENTA_USD.

Uso:  python ignition_scan.py            (escanea todo, ~2-4 min)
      python ignition_scan.py --horas 24 (igniciones de las ultimas 24h)
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
S = requests.Session()

RET_IGN = 0.10
VOLX_MIN = 4.0
FLAT = 0.15


def get(url, **params):
    for _ in range(5):
        r = S.get(url, params=params, timeout=30)
        if r.status_code in (418, 429):
            time.sleep(int(r.headers.get("Retry-After", 10)) + 1)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(url)


def scan_symbol(sym, horas):
    rows = get(FAPI + "/fapi/v1/klines", symbol=sym, interval="1h", limit=800)
    if len(rows) < 750:
        return []
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"])
    for k in ["o", "h", "l", "c", "qv", "tbqv"]:
        df[k] = df[k].astype(float)
    df["n"] = df["n"].astype(int)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.set_index("t").sort_index().iloc[:-1]  # fuera la vela en formacion
    df["delta"] = 2 * df["tbqv"] - df["qv"]
    c, qv = df["c"], df["qv"]
    ret6 = c / c.shift(6) - 1
    vol6 = qv.rolling(6).sum()
    volx = vol6 / vol6.shift(1).rolling(720, min_periods=600).median()
    flat = (c.shift(6) / c.shift(6 + 120) - 1).abs() < FLAT
    ign = (ret6 >= RET_IGN) & (volx >= VOLX_MIN) & flat
    # pre-aviso (radar): +7% en 4h con volumen 3x — aun no es entrada
    ret4 = c / c.shift(4) - 1
    vol4 = qv.rolling(4).sum()
    volx4 = vol4 / vol4.shift(1).rolling(720, min_periods=600).median()
    flat4 = (c.shift(4) / c.shift(4 + 120) - 1).abs() < FLAT
    pre = (ret4 >= 0.07) & (volx4 >= 3.0) & flat4 & ~ign

    out = []
    idxs = np.flatnonzero(ign.to_numpy())
    last = -10**9
    for i in idxs:
        if i - last < 72:
            continue
        last = i
        if i < len(df) - horas:
            continue
        w = df.iloc[i - 5:i + 1]
        px_det = df.iloc[i]["c"]
        px_now = df.iloc[-1]["c"]
        liq = df["qv"].resample("1D").sum().median()
        # firma multitud vs actor unico: print medio de la ignicion vs base 30d
        avg_ign = w["qv"].sum() / max(w["n"].sum(), 1)
        avg_base = (df["qv"] / df["n"].replace(0, 1)).iloc[:-6].median()
        out.append(dict(
            tipo="ENTRADA", liq_d=liq, print_ratio=avg_ign / max(avg_base, 1e-9),
            spark=[round(float(x), 8) for x in df["c"].iloc[-48:]],
            symbol=sym, hora=df.index[i], px_deteccion=px_det,
            px_actual=px_now, corrido=px_now / px_det - 1,
            chispa=ret6.iloc[i], volx=volx.iloc[i],
            delta=w["delta"].sum() / max(w["qv"].sum(), 1),
            stop_estruct=w["l"].min() * 0.99,
            hace_h=int((df.index[-1] - df.index[i]).total_seconds() // 3600),
        ))
    # pre-avisos: solo los de las ultimas 3h y sin ENTRADA reciente en el par
    if not out and (len(idxs) == 0 or len(df) - 1 - idxs[-1] > 72):
        pidx = np.flatnonzero(pre.to_numpy())
        for i in pidx:
            if i < len(df) - 3:
                continue
            w = df.iloc[i - 3:i + 1]
            px_now = df.iloc[-1]["c"]
            avg_ign_p = w["qv"].sum() / max(w["n"].sum(), 1)
            avg_base_p = (df["qv"] / df["n"].replace(0, 1)).iloc[:-6].median()
            out.append(dict(
                tipo="PRE-AVISO", symbol=sym, hora=df.index[i],
                px_deteccion=df.iloc[i]["c"], px_actual=px_now,
                corrido=px_now / df.iloc[i]["c"] - 1,
                chispa=ret4.iloc[i], volx=volx4.iloc[i],
                delta=w["delta"].sum() / max(w["qv"].sum(), 1),
                stop_estruct=w["l"].min() * 0.99,
                liq_d=float(df["qv"].resample("1D").sum().median()),
                print_ratio=avg_ign_p / max(avg_base_p, 1e-9),
                spark=[round(float(x), 8) for x in df["c"].iloc[-48:]],
                trigger_px=float(df["c"].iloc[max(i - 6, 0)] * 1.10),
                hace_h=int((df.index[-1] - df.index[i]).total_seconds() // 3600),
            ))
            break
    return out


def edad_dias(sym):
    """Dias desde el listado; cachea la fecha en listing_dates.json."""
    import json
    ld = {}
    if os.path.exists("listing_dates.json"):
        try:
            ld = json.load(open("listing_dates.json"))
        except Exception:
            ld = {}
    if sym not in ld:
        try:
            k = get(FAPI + "/fapi/v1/klines", symbol=sym, interval="1d", startTime=0, limit=1)
            ld[sym] = int(k[0][0])
            json.dump(ld, open("listing_dates.json", "w"))
        except Exception:
            return None
    return (pd.Timestamp.now("UTC").tz_localize(None) - pd.Timestamp(ld[sym], unit="ms")).days


def _volx_from(vols):
    """Expansion: volumen de las ultimas 6h vs mediana de ventanas 6h del mes."""
    if not vols or len(vols) < 240:
        return None
    s = pd.Series(vols, dtype=float)
    v6 = s.rolling(6).sum()
    med = v6.iloc[:-6].median()
    return float(v6.iloc[-1] / med) if med and med > 0 else None


def gate_volx(sym):
    try:
        r = S.get("https://api.gateio.ws/api/v4/futures/usdt/candlesticks",
                  params=dict(contract=sym.replace("USDT", "_USDT"), interval="1h", limit=744),
                  timeout=12)
        rows = r.json()
        return _volx_from([float(x.get("v", 0)) for x in rows]) if isinstance(rows, list) else None
    except Exception:
        return None


def mexc_volx(sym):
    try:
        end = int(time.time())
        r = S.get(f"https://contract.mexc.com/api/v1/contract/kline/{sym.replace('USDT','_USDT')}",
                  params=dict(interval="Min60", start=end - 31 * 86400, end=end), timeout=12)
        d = r.json().get("data") or {}
        return _volx_from(d.get("vol") or [])
    except Exception:
        return None


def bybit_volx(sym):
    """Expansion de volumen en Bybit: vol 6h actual vs su mediana de 30d."""
    try:
        r = S.get("https://api.bybit.com/v5/market/kline",
                  params=dict(category="linear", symbol=sym, interval="60", limit=744),
                  timeout=15)
        rows = r.json().get("result", {}).get("list") or []
        if len(rows) < 200:
            return None
        s = pd.Series([float(x[6]) for x in rows][::-1])  # turnover, viejo->nuevo
        vol6 = s.rolling(6).sum()
        med = vol6.iloc[:-6].median()
        return float(vol6.iloc[-1] / med) if med and med > 0 else None
    except Exception:
        return None


def fetch_news(base):
    """Titulares de Google News RSS para el token (gratis, sin key)."""
    import xml.etree.ElementTree as ET
    try:
        r = S.get("https://news.google.com/rss/search",
                  params={"q": f"{base} crypto", "hl": "es"}, timeout=8)
        root = ET.fromstring(r.content)
        out = []
        for item in root.iter("item"):
            t = item.findtext("title") or ""
            l = item.findtext("link") or ""
            d = (item.findtext("pubDate") or "")[:16]
            out.append((t, l, d))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


def _spark_svg(closes, det_px, W=250, H=54):
    if not closes or len(closes) < 5:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1e-12
    pts = " ".join(f"{k*W/(len(closes)-1):.1f},{H-3-(c-lo)/rng*(H-6):.1f}"
                   for k, c in enumerate(closes))
    color = "#3fb950" if closes[-1] >= closes[0] else "#f85149"
    y_det = H - 3 - (det_px - lo) / rng * (H - 6) if lo <= det_px <= hi else None
    det_line = (f'<line x1="0" y1="{y_det:.1f}" x2="{W}" y2="{y_det:.1f}" '
                f'stroke="#e0a94e" stroke-width="1" stroke-dasharray="3,3"/>' if y_det else "")
    return (f'<svg width="{W}" height="{H}" style="display:block">{det_line}'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/></svg>')


def write_html(hits, stamp, cuenta, riesgo):
    """Terminal oscuro estilo desk: senales, sparklines, recon y logica."""
    frescas = [h for h in hits if h["tipo"].startswith("ENTRADA") and h["hace_h"] <= 2]
    viejas = [h for h in hits if h["tipo"].startswith("ENTRADA") and h["hace_h"] > 2]
    radar = [h for h in hits if h["tipo"] == "PRE-AVISO"]
    GRN, RED, AMB, MUT = "#3fb950", "#f85149", "#e0a94e", "#8b949e"

    def badge(txt, color):
        return (f'<span style="border:1px solid {color};color:{color};border-radius:3px;'
                f'padding:1px 7px;font-size:11px;margin-right:6px;letter-spacing:.5px">{txt}</span>')

    def card(h, fresca):
        salta = "SOLITARIA" in h["tipo"] or h.get("liq_d", 0) > 100e6
        base = h["symbol"].replace("USDT", "")
        for pre in ("1000000", "1000"):
            if base.startswith(pre):
                base = base[len(pre):]
        d = h["delta"]
        b = []
        b.append(badge("COMPRA AGRESIVA", GRN) if d > 0.03 else
                 badge("CHISPA HUECA", RED) if d < -0.01 else badge("MIXTA", MUT))
        if h.get("edad") is not None:
            e = h["edad"]
            b.append(badge(f"EDAD {e}D" + (" ⚠" if e < 90 else " ✓" if e < 365 else ""),
                           RED if e < 90 else GRN if e < 365 else MUT))
        if h.get("bvx"):
            b.append(badge(f"BYBIT {h['bvx']:.0f}X" + (" ✓" if h["bvx"] >= 6 else ""),
                           GRN if h["bvx"] >= 6 else MUT))
        if h.get("print_ratio"):
            pr = h["print_ratio"]
            b.append(badge("MULTITUD ✓" if pr < 1.2 else "ACTOR UNICO ⚠" if pr > 2
                           else f"PRINT {pr:.1f}X", GRN if pr < 1.2 else RED if pr > 2 else MUT))
        if "SOLITARIA" in h["tipo"]:
            b.append(badge("SOLITARIA — SISTEMA LA SALTA", RED))
        if h.get("liq_d", 0) > 100e6:
            b.append(badge("GIGANTE >100M — SISTEMA LA SALTA", RED))
        risk_e = (h["px_actual"] - h["stop_estruct"]) / h["px_actual"]
        pos_e = cuenta * riesgo / max(risk_e, 1e-9)
        pos_8 = cuenta * riesgo / 0.08
        est_ok = 0.06 <= risk_e <= 0.12
        links = (
            f'<a href="https://es.tradingview.com/chart/?symbol=BINANCE%3A{h["symbol"]}.P" target="_blank">GRAFICO</a>'
            f'<a href="https://x.com/search?q=%24{base}&f=live" target="_blank">X LIVE</a>'
            f'<a href="https://news.google.com/search?q={base}%20crypto" target="_blank">NEWS</a>'
            f'<a href="https://dexscreener.com/search?q={base}" target="_blank">DEXSCREENER</a>'
            f'<a href="https://www.coingecko.com/es/search?query={base}" target="_blank">COINGECKO</a>')
        news_html = ""
        if h.get("news"):
            items = "".join(f'<div class="nw">▸ <a href="{l}" target="_blank">{t[:95]}</a>'
                            f' <span style="color:{MUT}">{d}</span></div>'
                            for t, l, d in h["news"])
            news_html = f'<div style="margin-top:7px">{items}</div>'
        borde = MUT if salta else (GRN if fresca else AMB)
        op = ".5" if salta else "1"
        estado = "ENTRABLE" if fresca and not salta else ("SALTAR" if salta else "YA CORRIDA")
        return f"""
<div class="card" style="border-left:3px solid {borde};opacity:{op}">
 <div class="chead">
  <div>
   <span class="sym">{h['symbol']}</span>
   <span class="est" style="color:{borde}">{estado}</span>
   <span class="meta">T-{h['hace_h']}h · +{h['chispa']:.0%}/6h · VOL {h['volx']:.0f}X ·
   Δ{d:+.2f} · corrido {h['corrido']:+.1%} · liq {h.get('liq_d',0)/1e6:.0f}M$/d</span>
  </div>
  {_spark_svg(h.get('spark'), h['px_deteccion'])}
 </div>
 <div style="margin:7px 0 5px">{''.join(b)}</div>
 <table class="dt"><tr>
  <td><s1>ENTRADA LIM</s1><s2>{h['px_deteccion']:.6g}</s2></td>
  <td><s1>STOP 8%</s1><s2>{h['px_deteccion']*0.92:.6g} <em>({pos_8:.0f}$)</em></s2></td>
  <td><s1>STOP ESTRUCT {'✓' if est_ok else '✗'}</s1><s2>{h['stop_estruct']:.6g} <em>({risk_e:.0%} · {pos_e:.0f}$)</em></s2></td>
  <td><s1>TP +40%</s1><s2>{h['px_deteccion']*1.40:.6g}</s2></td>
  <td><s1>SALIDA</s1><s2>7 dias</s2></td>
 </tr></table>
 <div class="links">{links}</div>{news_html}
</div>"""

    def rcard(h):
        base = h["symbol"].replace("USDT", "")
        for pre in ("1000000", "1000"):
            if base.startswith(pre):
                base = base[len(pre):]
        d = h["delta"]
        b = [badge("COMPRA AGRESIVA", GRN) if d > 0.03 else
             badge("CHISPA HUECA", RED) if d < -0.01 else badge("MIXTA", MUT)]
        trig = h.get("trigger_px", h["px_deteccion"] * 1.03)
        falta = trig / h["px_actual"] - 1
        return f"""
<div class="card rcard">
 <div class="chead">
  <div>
   <span class="sym" style="color:{AMB}">{h['symbol']}</span>
   <span class="est" style="color:{AMB}">A VIGILAR</span>
   <span class="meta">hace {h['hace_h']}h · +{h['chispa']:.0%}/4h · VOL {h['volx']:.0f}X · Δ{d:+.2f}</span>
  </div>
  {_spark_svg(h.get('spark'), trig)}
 </div>
 <div style="margin:7px 0 5px">{''.join(b)}</div>
 <table class="dt"><tr>
  <td><s1>PRECIO AHORA</s1><s2>{h['px_actual']:.6g}</s2></td>
  <td><s1>CONFIRMA EN ≈</s1><s2 style="color:{AMB}">{trig:.6g} <em>({falta:+.1%})</em></s2></td>
  <td><s1>SI CONFIRMA</s1><s2>pasa a ENTRABLE con su tarjeta completa</s2></td>
 </tr></table>
 <div class="links">
  <a href="https://es.tradingview.com/chart/?symbol=BINANCE%3A{h['symbol']}.P" target="_blank">GRAFICO</a>
  <a href="https://x.com/search?q=%24{base}&f=live" target="_blank">X LIVE</a>
  <a href="https://dexscreener.com/search?q={base}" target="_blank">DEXSCREENER</a>
 </div>
</div>"""

    main_col = []
    if frescas:
        main_col.append(f'<div class="sec" style="color:{GRN}">▮ ENTRABLES ({len(frescas)})</div>'
                        + "".join(card(h, True) for h in frescas))
    else:
        main_col.append(f'<div class="sec" style="color:{MUT}">▮ SIN SEÑALES ENTRABLES AHORA '
                        '<span style="font-weight:400">— media ~1/dia; el vacio es normal, no un fallo</span></div>')
    if radar:
        main_col.append(f'<div class="sec" style="color:{AMB}">▮ A VIGILAR — RADAR +7%/4H ({len(radar)}) '
                        '<span style="font-weight:400;color:' + MUT + '">tu ventana para mirar el grafico '
                        'ANTES de que confirme</span></div>'
                        + "".join(rcard(h) for h in radar))
    if viejas:
        main_col.append(f'<div class="sec" style="color:{MUT}">▮ YA CORRIDAS ({len(viejas)}) — contexto, no entrada</div>'
                        + "".join(card(h, False) for h in viejas))

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>IGNITION TERMINAL</title><style>
body{{background:#0a0d12;color:#c8d1dc;font-family:Consolas,'Cascadia Mono',monospace;margin:0}}
a{{color:#58a6ff;text-decoration:none;margin-right:14px;font-size:11px;letter-spacing:.5px}}
a:hover{{text-decoration:underline}}
.top{{background:#10141b;border-bottom:1px solid #232b36;padding:10px 22px;display:flex;
 justify-content:space-between;align-items:baseline}}
.top .t{{color:{AMB};font-size:16px;font-weight:700;letter-spacing:2px}}
.top .s{{color:{MUT};font-size:11px}}
.wrap{{display:grid;grid-template-columns:1fr 295px;gap:16px;padding:16px 22px;max-width:1280px;margin:auto}}
.card{{background:#10141b;border:1px solid #232b36;border-radius:4px;padding:12px 16px;margin-bottom:12px;transition:border-color .15s}}
.card:hover{{border-color:#3a4656}}
.rcard{{border-left:3px dashed {AMB}!important;background:#12130f}}
.chead{{display:flex;justify-content:space-between;align-items:center}}
.sym{{font-size:19px;font-weight:700;color:#e6edf3;letter-spacing:1px}}
.est{{font-size:11px;font-weight:700;margin-left:9px;letter-spacing:1px}}
.meta{{font-size:11px;color:{MUT};margin-left:9px}}
.dt{{width:100%;border-collapse:collapse;margin-top:3px}}
.dt td{{padding:3px 14px 3px 0}}
s1{{display:block;font-size:9.5px;color:{MUT};letter-spacing:1px}}
s2{{display:block;font-size:14px;color:#e6edf3}} s2 em{{color:{MUT};font-style:normal;font-size:11px}}
.links{{margin-top:7px;border-top:1px dashed #232b36;padding-top:6px}}
.nw{{font-size:11px;padding:1px 0}} .nw a{{color:#9ecbff}}
.sec{{font-size:12px;letter-spacing:2px;margin:6px 0 9px;font-weight:700}}
.panel{{background:#10141b;border:1px solid #232b36;border-radius:4px;padding:12px 14px;margin-bottom:14px}}
.panel h3{{margin:0 0 8px;font-size:11px;color:{AMB};letter-spacing:2px}}
.panel .r{{font-size:11.5px;padding:2.5px 0;color:#c8d1dc}} .panel .r b{{color:#e6edf3}}
.rrow{{font-size:12px;padding:6px 0;border-bottom:1px dashed #232b36}}
</style></head><body>
<div class="top">
 <span class="t">⚡ IGNITION TERMINAL</span>
 <span class="s">{stamp} · escaneo /15min · {len(frescas)} entrable(s) · {len(viejas)} corrida(s) ·
 {len(radar)} radar · cuenta {cuenta:.0f}$ · riesgo {riesgo:.0%}/trade</span>
</div>
<div class="wrap">
<div>{''.join(main_col)}</div>
<div>
 <div class="panel"><h3>LOGICA DEL SISTEMA</h3>
  <div class="r"><b>Señal:</b> +10%/6h · vol≥4x mediana 30d · plano 5d (±15%) · sin ignición 72h</div>
  <div class="r"><b>Filtros:</b> ≥1 ignición más en 24h (no solitaria) · par &lt;100M$/día</div>
  <div class="r"><b>Entrada:</b> LÍMITE al precio de detección (post-only), válida 6h</div>
  <div class="r"><b>Stop:</b> −8% fijo · o estructural si cae entre 6-12% (✓/✗ en tarjeta)</div>
  <div class="r"><b>Salida:</b> TP +40% · o 7 días · NO SE TOCA entre medias</div>
  <div class="r"><b>Tamaño:</b> riesgo/distancia_stop · máx 3-4 posiciones · desempate: mayor Δ</div>
 </div>
 <div class="panel"><h3>QUE ESPERAR (BACKTEST)</h3>
  <div class="r">P(+25% más) ≈ <b>31%</b> · TP+40% ≈ <b>15%</b></div>
  <div class="r">Exp. <b>+1.5%/trade</b> · mediana NEGATIVA</div>
  <div class="r">Retroceso medio <b>−15%</b> antes de resolver</div>
  <div class="r">Rachas de 8-12 rojas = rutina, no error</div>
  <div class="r" style="color:{MUT}">revision: python revision.py</div>
 </div>
</div></div></body></html>"""
    with open("senales.html", "w", encoding="utf-8") as f:
        f.write(html)


from dashboard import fetch_news, write_html  # capa visual v3


def _historial(dias=7):
    """Senales del log de los ultimos N dias + precio actual (1 llamada bulk)."""
    import csv
    if not os.path.exists("senales_log.csv"):
        return []
    with open("senales_log.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    try:
        precios = {t["symbol"]: float(t["price"])
                   for t in get(FAPI + "/fapi/v1/ticker/price")}
    except Exception:
        precios = {}
    import json
    ld = {}
    if os.path.exists("listing_dates.json"):
        try:
            ld = json.load(open("listing_dates.json"))
        except Exception:
            ld = {}
    lim = pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(days=dias)
    out, vistos = [], set()
    for r in rows:
        try:
            h = pd.Timestamp(r["hora"])
            px = float(r["px_deteccion"])
        except Exception:
            continue
        if h < lim or (r["symbol"], r["hora"]) in vistos:
            continue
        vistos.add((r["symbol"], r["hora"]))
        now = precios.get(r["symbol"])
        edad = None
        if r["symbol"] in ld:
            edad = int((h - pd.Timestamp(ld[r["symbol"]], unit="ms")).days)
        def _f(k):
            try:
                return float(r.get(k) or 0)
            except Exception:
                return 0.0
        out.append(dict(symbol=r["symbol"], hora=h, px=px,
                        chg=(now / px - 1) if now else None, tipo=r.get("tipo", ""),
                        delta=_f("delta"), liq_d=_f("liq_d"),
                        print_ratio=_f("print_ratio"), edad=edad,
                        bvx=_f("bvx"), gvx=_f("gvx"), mvx=_f("mvx")))
    out.sort(key=lambda x: x["hora"], reverse=True)
    return out


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=int, default=12, help="mirar igniciones de las ultimas N horas")
    ap.add_argument("--cuenta", type=float, default=1000.0)
    ap.add_argument("--riesgo", type=float, default=0.02)
    a = ap.parse_args()

    info = get(FAPI + "/fapi/v1/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"]
            if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING" and s["symbol"] not in ("BTCUSDT", "ETHUSDT")]
    print(f"escaneando {len(syms)} perpetuos...", file=sys.stderr, flush=True)

    hits = []
    for n, sym in enumerate(syms, 1):
        try:
            hits += scan_symbol(sym, a.horas)
        except Exception as ex:
            print(f"{sym}: error {ex}", file=sys.stderr, flush=True)
        if n % 50 == 0:
            print(f"  {n}/{len(syms)}", file=sys.stderr, flush=True)
        time.sleep(0.12)

    print("=" * 100)
    stamp = pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC")
    if not hits:
        print(f"[{stamp}] Sin igniciones en las ultimas {a.horas}h. "
              f"(media historica: ~1/dia en el universo; habra dias vacios)")
        write_html([], stamp, a.cuenta, a.riesgo, historial=_historial())
        return
    hits.sort(key=lambda x: (x["tipo"] != "ENTRADA", -x["delta"]))
    n_ent = sum(1 for h in hits if h["tipo"] == "ENTRADA")
    # regla de calor: una ignicion sin ninguna otra en 24h rinde peor (medido)
    if n_ent == 1:
        for h in hits:
            if h["tipo"] == "ENTRADA":
                h["tipo"] = "ENTRADA-SOLITARIA (el sistema la salta: historicamente peor)"
    print(f"[{stamp}] {n_ent} ENTRADA(s) en las ultimas {a.horas}h y "
          f"{len(hits)-n_ent} PRE-AVISO(s) en las ultimas 3h\n")
    for h in hits:
        if h["tipo"] == "PRE-AVISO":
            h["edad"] = edad_dias(h["symbol"])
            h["bvx"] = bybit_volx(h["symbol"])
            h["gvx"] = gate_volx(h["symbol"])
            h["mvx"] = mexc_volx(h["symbol"])
            print(f"  [RADAR] {h['symbol']:14s} +{h['chispa']:.0%} en 4h, vol {h['volx']:.0f}x, "
                  f"delta {h['delta']:+.2f} — hace {h['hace_h']}h. Vigilar: si llega a +10%/6h es ENTRADA.")
            continue
        calidad = ("COMPRA AGRESIVA" if h["delta"] > 0.03
                   else "hueca (peor continuacion)" if h["delta"] < -0.01 else "mixta")
        risk_e = (h["px_actual"] - h["stop_estruct"]) / h["px_actual"]
        stop8 = h["px_actual"] * 0.92
        pos_e = a.cuenta * a.riesgo / max(risk_e, 1e-9)
        pos_8 = a.cuenta * a.riesgo / 0.08
        marca = "  [SOLITARIA - el sistema la salta]" if "SOLITARIA" in h["tipo"] else ""
        if h.get("liq_d", 0) > 100e6:
            marca += "  [GIGANTE >100M$/dia - el sistema la salta]"
        edad = edad_dias(h["symbol"])
        bvx = bybit_volx(h["symbol"])
        h["edad"], h["bvx"] = edad, bvx
        h["gvx"] = gate_volx(h["symbol"])
        h["mvx"] = mexc_volx(h["symbol"])
        if h["hace_h"] <= 2:
            base_tok = h["symbol"].replace("USDT", "")
            for pre in ("1000000", "1000"):
                if base_tok.startswith(pre):
                    base_tok = base_tok[len(pre):]
            h["news"] = fetch_news(base_tok)
        ctx = []
        if edad is not None:
            ctx.append(f"edad {edad}d" + (" (RECIEN LISTADO, peor)" if edad < 90
                                          else " (3-12m, punto dulce)" if edad < 365 else ""))
        ctx.append(f"Bybit vol {bvx:.0f}x (amplia)" if bvx and bvx >= 6
                   else f"Bybit vol {bvx:.1f}x (estrecha)" if bvx else "Bybit: sin datos")
        pr = h.get("print_ratio")
        if pr:
            ctx.append(f"print medio {pr:.1f}x base" +
                       (" -> MULTITUD (bueno)" if pr < 1.2 else
                        " -> ACTOR UNICO? (ojo, firma de scam-pump)" if pr > 2.0 else ""))
        marca += "  |  " + ", ".join(ctx)
        print(f"  {h['symbol']:16s} disparo hace {h['hace_h']}h ({h['hora']:%d %H:%M} UTC)  "
              f"chispa +{h['chispa']:.0%}  vol {h['volx']:.0f}x  delta {h['delta']:+.2f} -> {calidad}{marca}")
        print(f"      precio {h['px_actual']:.6g} (ya corrido {h['corrido']:+.1%} desde deteccion)  "
              f"TP ref +40%: {h['px_actual']*1.40:.6g}")
        print(f"      stop estructural {h['stop_estruct']:.6g} (dist {risk_e:.1%}, pos {pos_e:.0f}$)  |  "
              f"stop 8%: {stop8:.6g} (pos {pos_8:.0f}$)  [cuenta {a.cuenta:.0f}$, riesgo {a.riesgo:.0%}]")
        print()
    print("Backtest de referencia: P(+25% mas)=31%, retorno medio 7d +4.2%, mediana NEGATIVA,")
    print("retroceso medio -15% antes de resolverse. Las 'ya corridas' >10% pagan peor entrada.")
    print("ENTRADA: orden LIMITE al precio de deteccion (post-only), valida 6h — se ejecuta")
    print("~100% de las veces y anade +0.1%/trade vs mercado (medido). Desempate entre")
    print("senales simultaneas: mayor delta primero (criterio blando, en validacion).")
    # registro para revision/historial (tras el enriquecimiento: edad/amplitud ya calculadas)
    import csv
    log_path = "senales_log.csv"
    vistos = set()
    if os.path.exists(log_path):
        with open(log_path, newline="", encoding="utf-8") as f:
            vistos = {(r["symbol"], r["hora"]) for r in csv.DictReader(f)}
    nuevos = [h for h in hits if h["tipo"].startswith("ENTRADA")
              and (h["symbol"], str(h["hora"])) not in vistos]
    if nuevos:
        new_file = not os.path.exists(log_path)
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["symbol", "hora", "px_deteccion", "stop_estruct", "delta",
                            "liq_d", "print_ratio", "tipo", "edad", "bvx", "gvx", "mvx"])
            for h in nuevos:
                w.writerow([h["symbol"], h["hora"], h["px_deteccion"], h["stop_estruct"],
                            round(h["delta"], 4), round(h.get("liq_d", 0)),
                            round(h.get("print_ratio", 0), 2), h["tipo"],
                            h.get("edad") if h.get("edad") is not None else "",
                            round(h["bvx"], 1) if h.get("bvx") else "",
                            round(h["gvx"], 1) if h.get("gvx") else "",
                            round(h["mvx"], 1) if h.get("mvx") else ""])

    write_html(hits, stamp, a.cuenta, a.riesgo, historial=_historial())
    print("\npanel actualizado: senales.html")


if __name__ == "__main__":
    main()
