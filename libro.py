"""
EL LIBRO: simulacion continua del challenge sobre las señales de papel.

Reglas simuladas (perfil HyroTrader 2-step, fase 1):
  balance inicial 100k · riesgo 1%/trade (sizing estatico) · max 4 posiciones
  simultaneas (largos+cortos) · objetivo +10% · limite total -10% · diario -5%.
Largos: entrada=px deteccion, stop -8%, TP +40%, 7d. Cortos: stop/tp del log, 10d.
Los resultados por señal se cachean (libro_cache.json) para no repetir llamadas.
Salida: resumen en consola + libro.html + libro_equity.csv
"""
import csv
import json
import os
import sys
import time

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

os.chdir(os.path.dirname(os.path.abspath(__file__)))
FAPI = "https://fapi.binance.com"
import requests
S = requests.Session()

BAL, RIESGO, SLOTS = 100_000.0, 0.01, 4
OBJETIVO, DD_TOTAL, DD_DIA = 0.10, 0.10, 0.05
INICIO = pd.Timestamp("2026-09-03")
CACHE = "libro_cache.json"


def klines(sym, t0, limit):
    for _ in range(4):
        try:
            r = S.get(FAPI + "/fapi/v1/klines", timeout=20,
                      params=dict(symbol=sym, interval="1h",
                                  startTime=int(t0.timestamp() * 1000) + 3600_000,
                                  limit=limit))
            if r.status_code == 429:
                time.sleep(10)
                continue
            return r.json()
        except requests.RequestException:
            time.sleep(3)
    return []


def resolver(sig):
    """Devuelve (exit_ts_ms, ret_precio, dist_stop, estado) o None si sigue viva."""
    sym, t0 = sig["symbol"], pd.Timestamp(sig["hora"])
    if sig["lado"] == "L":
        entry, stop, tp, horas = float(sig["px_deteccion"]), \
            float(sig["px_deteccion"]) * 0.92, float(sig["px_deteccion"]) * 1.40, 168
    else:
        entry, stop, tp, horas = float(sig["px_deteccion"]), \
            float(sig["stop_corto"]), float(sig["tp_corto"]), 240
    dist = abs(stop / entry - 1)
    k = klines(sym, t0, horas + 2)
    time.sleep(0.08)
    for n, bar in enumerate(k or []):
        hi, lo, cl, ts = float(bar[2]), float(bar[3]), float(bar[4]), int(bar[0])
        if sig["lado"] == "L":
            if lo <= stop:
                return ts, stop / entry - 1 - 0.003, dist, "STOP"
            if hi >= tp:
                return ts, tp / entry - 1 - 0.003, dist, "TP"
        else:
            if hi >= stop:
                return ts, -(stop / entry - 1) - 0.003, dist, "STOP"
            if lo <= tp:
                return ts, -(tp / entry - 1) - 0.003, dist, "TP"
        if n >= horas - 1:
            r = (cl / entry - 1) if sig["lado"] == "L" else -(cl / entry - 1)
            return ts, r - 0.003, dist, "TIEMPO"
    return None


def cargar_senales():
    out = []
    if os.path.exists("senales_log.csv"):
        with open("senales_log.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if "SOLITARIA" in r.get("tipo", "") or "GIGANTE" in r.get("tipo", ""):
                    continue
                r["lado"] = "L"
                out.append(r)
    if os.path.exists("cortos_log.csv"):
        with open("cortos_log.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["lado"] = "S"
                out.append(r)
    out = [r for r in out if pd.Timestamp(r["hora"]) >= INICIO]
    out.sort(key=lambda r: r["hora"])
    return out


def simular(senales, cache, lados=("L", "S")):
    abiertas, trades, saltadas = [], [], 0
    for s in senales:
        if s["lado"] not in lados:
            continue
        key = f"{s['symbol']}|{s['hora']}|{s['lado']}"
        t_sig = pd.Timestamp(s["hora"])
        abiertas = [a for a in abiertas if a["exit"] is None or a["exit"] > t_sig]
        vivas = len([a for a in abiertas
                     if a["exit"] is None or a["exit"] > t_sig])
        if vivas >= SLOTS:
            saltadas += 1
            continue
        if key in cache:
            res = cache[key]
        else:
            r = resolver(s)
            res = None if r is None else {"exit_ms": r[0], "ret": r[1],
                                          "dist": r[2], "estado": r[3]}
            if res is not None:
                cache[key] = res
        if res is None:
            abiertas.append({"exit": None, "sym": s["symbol"]})
            continue
        exit_t = pd.Timestamp(res["exit_ms"], unit="ms")
        pnl = BAL * RIESGO * (res["ret"] / max(res["dist"], 1e-9))
        trades.append(dict(sym=s["symbol"], lado=s["lado"], t=t_sig, exit=exit_t,
                           estado=res["estado"], ret=res["ret"], pnl=pnl))
        abiertas.append({"exit": exit_t, "sym": s["symbol"]})

    df = pd.DataFrame(trades)
    n_open = len([a for a in abiertas if a["exit"] is None])
    if df.empty:
        return dict(df=df, n_open=n_open, saltadas=saltadas, ret=0.0, dd=0.0,
                    peor=0.0, wr=0.0, estado="SIN TRADES AUN")
    df = df.sort_values("exit")
    df["equity"] = BAL + df["pnl"].cumsum()
    eq_d = df.set_index("exit")["equity"].resample("1D").last().ffill()
    ret_total = df["pnl"].sum() / BAL
    dd = (eq_d / eq_d.cummax() - 1).min()
    peor_dia = (df.groupby(df["exit"].dt.date)["pnl"].sum() / BAL).min()
    wr = (df["ret"] > 0).mean()
    if ret_total >= OBJETIVO:
        estado = "OBJETIVO +10% ✓"
    elif dd <= -DD_TOTAL or peor_dia <= -DD_DIA:
        estado = "SUSPENDIDO"
    else:
        estado = "VIVO"
    return dict(df=df, n_open=n_open, saltadas=saltadas, ret=ret_total, dd=dd,
                peor=peor_dia, wr=wr, estado=estado)


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    senales = cargar_senales()
    libros = {
        "COMBINADO": simular(senales, cache, ("L", "S")),
        "SOLO LARGOS": simular(senales, cache, ("L",)),
        "SOLO CORTOS": simular(senales, cache, ("S",)),
    }
    json.dump(cache, open(CACHE, "w"))
    print(f"LIBROS (challenge simulado 100k, riesgo 1%, {SLOTS} slots) desde {INICIO.date()}")
    for nombre, r in libros.items():
        d = r["df"]
        extra = "" if d.empty else (f" | wr {r['wr']:.0%} | TP:{(d['estado']=='TP').sum()} "
                                    f"STOP:{(d['estado']=='STOP').sum()} T:{(d['estado']=='TIEMPO').sum()}")
        print(f"  {nombre:12s}: {r['ret']:+.2%} | {len(d)} cerrados, {r['n_open']} abiertos"
              f" | maxDD {r['dd']:+.2%} | peor dia {r['peor']:+.2%} | {r['estado']}{extra}")
    df = libros["COMBINADO"]["df"]
    if not df.empty:
        df.to_csv("libro_equity.csv", index=False)

    bloques = ""
    for nombre, r in libros.items():
        c = ("#4cc38a" if "✓" in r["estado"] else
             "#f1655f" if r["estado"] == "SUSPENDIDO" else
             "#8fa0b3" if "SIN" in r["estado"] else "#e5b567")
        d = r["df"]
        bloques += f"""
<div class="lb"><div class="lbn">{nombre}</div>
 <div class="lbr" style="color:{c}">{r['ret']:+.2%} · {r['estado']}</div>
 <div class="lbk">{len(d)} cerrados · {r['n_open']} abiertos · wr {r['wr']:.0%} ·
 maxDD {r['dd']:+.1%} · peor dia {r['peor']:+.1%} · saltados {r['saltadas']}</div></div>"""
    filas = "".join(
        f"<tr><td>{t['sym']}</td><td>{'LARGO' if t['lado']=='L' else 'CORTO'}</td>"
        f"<td>{t['t']:%d-%m %H:%M}</td><td>{t['exit']:%d-%m %H:%M}</td>"
        f"<td style='color:{'#4cc38a' if t['pnl']>0 else '#f1655f'}'>{t['estado']}</td>"
        f"<td style='color:{'#4cc38a' if t['pnl']>0 else '#f1655f'};text-align:right'>"
        f"{t['pnl']:+,.0f}$</td></tr>"
        for t in df.sort_values('exit', ascending=False).to_dict('records')) if not df.empty else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="600"><title>LIBRO — challenge simulado</title><style>
body{{background:#0a0e14;color:#dbe4ee;font-family:Consolas,monospace;padding:26px;max-width:920px;margin:auto}}
h1{{color:#e5b567;font-size:16px;letter-spacing:2px}}
.lb{{background:#10151d;border:1px solid #202b3a;border-radius:8px;padding:12px 16px;
 margin-bottom:10px;display:grid;grid-template-columns:150px 260px 1fr;align-items:center;gap:14px}}
.lbn{{font-size:11px;letter-spacing:2px;color:#8fa0b3;font-weight:700}}
.lbr{{font-size:20px;font-weight:700}}
.lbk{{font-size:11px;color:#8fa0b3}}
table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:13px}}
td,th{{padding:6px 8px;border-bottom:1px dashed #202b3a;text-align:left}}
th{{color:#8fa0b3;font-size:9px;letter-spacing:1.5px}}
a{{color:#58a6ff;text-decoration:none}}</style></head><body>
<h1>📒 LIBROS — CHALLENGE SIMULADO (100K · 1% · {SLOTS} SLOTS · desde {INICIO.date()}) &nbsp;
<a href="senales.html">◂ largos</a> · <a href="cortos.html">cortos</a></h1>
{bloques}
<table><tr><th>PAR</th><th>LADO</th><th>ENTRADA</th><th>SALIDA</th><th>ESTADO</th><th>P&L (libro combinado)</th></tr>
{filas}</table>
<p style="color:#8fa0b3;font-size:11px">Reglas fijas, entrada limite en deteccion, sin discrecion.
Tres libros, mismas señales: el dia que uno apruebe de forma sostenida, esa es tu configuracion
de challenge — y la fee deja de ser apuesta.</p></body></html>"""
    with open("libro.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("  -> libro.html actualizado")


if __name__ == "__main__":
    main()
