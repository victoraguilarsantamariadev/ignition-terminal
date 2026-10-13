"""
El corrector: revisa cada senal registrada en senales_log.csv y dice que paso.

Por senal: estado (TP +40% / STOP -8% / TIEMPO 7d / EN CURSO), maximo alcanzado,
¿fue pump valido? (+25% o mas), y el contexto que tenia (delta, liq, print).
Al final: estadistica agregada vs la referencia del backtest.

Uso: python revision.py          (todas las senales del log)
     python revision.py --dias 7 (solo las de los ultimos 7 dias)
"""
import argparse
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


def klines_desde(sym, t0):
    r = S.get(FAPI + "/fapi/v1/klines",
              params=dict(symbol=sym, interval="1h",
                          startTime=int(pd.Timestamp(t0).timestamp() * 1000), limit=200),
              timeout=20)
    df = pd.DataFrame(r.json(), columns=["t", "o", "h", "l", "c", "v", "ct", "qv", "n", "tbv", "tbqv", "x"])
    for k in ("o", "h", "l", "c"):
        df[k] = df[k].astype(float)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    return df.set_index("t")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=9999)
    a = ap.parse_args()
    log = pd.read_csv("senales_log.csv", parse_dates=["hora"])
    log = log[log["hora"] >= pd.Timestamp.now() - pd.Timedelta(days=a.dias)]
    log = log.drop_duplicates(["symbol", "hora"]).sort_values("hora")
    if log.empty:
        print("sin senales en el log para ese rango")
        return

    print(f"{'par':14s} {'senal':>12s} {'estado':>10s} {'max':>7s} {'valido':>7s} "
          f"{'delta':>6s} {'contexto'}")
    resultados = []
    for _, s in log.iterrows():
        entry = s["px_deteccion"]  # entrada limite al precio de deteccion
        stop = entry * 0.92
        tp = entry * 1.40
        k = klines_desde(s["symbol"], s["hora"] + pd.Timedelta(hours=1))
        time.sleep(0.1)
        if k.empty:
            continue
        k7 = k.iloc[:168]
        estado, ret = "EN CURSO", k7["c"].iloc[-1] / entry - 1
        for _, r in k7.iterrows():
            if r["l"] <= stop:
                estado, ret = "STOP", stop / entry - 1
                break
            if r["h"] >= tp:
                estado, ret = "TP+40%", tp / entry - 1
                break
        if estado == "EN CURSO" and len(k) >= 168:
            estado = "TIEMPO"
        maxr = k7["h"].max() / entry - 1
        valido = "SI" if maxr >= 0.25 else ("aun no" if len(k) < 168 else "no")
        gigante = " GIGANTE" if maxr >= 0.40 else ""
        ctx = []
        if s.get("print_ratio", 0) and s["print_ratio"] > 2:
            ctx.append("actor unico?")
        if "SOLITARIA" in str(s.get("tipo", "")):
            ctx.append("solitaria(saltada)")
        if s.get("liq_d", 0) > 100e6:
            ctx.append("gigante(saltada)")
        resultados.append(dict(estado=estado, ret=ret, maxr=maxr,
                               operable="saltada" not in " ".join(ctx)))
        print(f"{s['symbol']:14s} {s['hora'].strftime('%d-%m %H:%M'):>12s} {estado:>10s} "
              f"{maxr:>+6.0%} {valido:>7s}{gigante} {s['delta']:>+6.2f} {', '.join(ctx)}")

    df = pd.DataFrame(resultados)
    op = df[df["operable"]]
    cerradas = op[op["estado"] != "EN CURSO"]
    print(f"\n--- {len(op)} senales operables ({len(cerradas)} cerradas) ---")
    if len(cerradas) >= 3:
        print(f"pump valido (+25%): {(cerradas['maxr'] >= 0.25).mean():.0%}  "
              f"(backtest: ~31%)")
        print(f"TP+40% alcanzado:   {(cerradas['estado'] == 'TP+40%').mean():.0%}  (backtest: ~15%)")
        print(f"retorno medio:      {cerradas['ret'].mean():+.2%}  (backtest: ~+1.5%)")
    print("Cada senal cerrada es un dato out-of-sample: alimenta PENDIENTES.md")


if __name__ == "__main__":
    main()
