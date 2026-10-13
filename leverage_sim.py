"""
Simulacion de una cuenta de 1000$ operando L_B (estructural, TP 25%, 7d)
con distintas politicas de tamano/apalancamiento, usando los trades reales
del backtest (cache de 400d) en orden aleatorio (2000 secuencias Monte Carlo).

Dos familias de politicas:
  A) Riesgo fijo por trade: apuesta f% de la cuenta a la distancia del stop.
     Tamano de posicion = equity * f / dist_stop  (el apalancamiento resulta
     de ahi; con stops del 8-15% casi nunca supera 1-2x).
  B) "A lo bruto": toda la cuenta como margen con apalancamiento fijo Lx.
     Si la distancia al stop >= 0.9/L, Binance te liquida antes de que el stop
     trabaje -> perdida ~100% del margen (aprox conservadora, aislado).

Metricas por politica: mediana del equity final tras las ~102 operaciones
(~1 anyo), percentil 5, prob de acabar con menos de la mitad, prob de ruina
(equity < 10%), y max drawdown mediano.
"""
import sys

import numpy as np

from trade_rules import build, simulate
from consensus_backtest import perp_symbols

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TOP, DAYS, CACHE = 100, 400, ".cache_1h"

trades = []  # (date, ret_neto, dist_stop)
for n, s in enumerate(perp_symbols(TOP), 1):
    try:
        r = build(s, DAYS, CACHE)
    except Exception as ex:
        print(f"{s}: ERROR {ex}", file=sys.stderr, flush=True)
        continue
    if not r:
        continue
    d, sig, hp = r
    fired = sig.index[sig["L_B"]]
    for ret, rmul, hit, t in simulate(d, hp, fired, 1, "estructural", 0.25):
        trades.append((t, ret, abs(ret / rmul) if rmul != 0 else np.nan))
print(f"{len(trades)} trades cargados", file=sys.stderr, flush=True)

trades.sort(key=lambda x: x[0])
rets = np.array([x[1] for x in trades])
dists = np.array([x[2] for x in trades])
ok = np.isfinite(dists) & (dists > 0.005)
rets, dists = rets[ok], dists[ok]
R = rets / dists

print(f"\nDistribucion de los {len(rets)} trades L_B (estructural, TP25, 7d):")
print(f"  ret neto: media {rets.mean():+.2%} | mediana {np.median(rets):+.2%} | "
      f"peor {rets.min():+.2%} | mejor {rets.max():+.2%} | std {rets.std():.2%}")
print(f"  dist. stop: media {dists.mean():.1%} | min {dists.min():.1%} | max {dists.max():.1%}")
print(f"  R (ret/riesgo): media {R.mean():+.2f} | std {R.std():.2f}")
kelly = R.mean() / R.var()
print(f"  Kelly aproximado f* = mean(R)/var(R) = {kelly:.1%} de la cuenta por trade")

rng = np.random.default_rng(7)
N_SIM = 2000


def run_policy(kind, param):
    finals, maxdds, wipes = [], [], 0
    for _ in range(N_SIM):
        idx = rng.permutation(len(rets))
        eq, peak, maxdd = 1.0, 1.0, 0.0
        for i in idx:
            if kind == "riesgo_fijo":
                eq *= 1 + param * (rets[i] / dists[i])
            else:  # apalancamiento fijo L, toda la cuenta
                L = param
                if dists[i] >= 0.9 / L:
                    eq *= 0.0  # liquidado antes del stop
                else:
                    eq *= 1 + L * rets[i]
            if eq <= 0.001:
                eq = 0.0
                break
            peak = max(peak, eq)
            maxdd = max(maxdd, 1 - eq / peak)
        finals.append(eq)
        maxdds.append(maxdd if eq > 0 else 1.0)
        if eq == 0.0:
            wipes += 1
    f = np.array(finals)
    return (np.median(f), np.percentile(f, 5), (f < 0.5).mean(),
            (f < 0.1).mean(), np.median(maxdds), wipes / N_SIM)


print(f"\nCuenta inicial 1000$ | {len(rets)} trades (~1 anyo) | {N_SIM} secuencias Monte Carlo")
print(f"{'politica':28s} {'mediana':>9s} {'p5':>8s} {'P(<500$)':>9s} {'P(<100$)':>9s} {'maxDD':>7s} {'P(liq total)':>12s}")
for label, kind, param in [
    ("riesgo 1%/trade", "riesgo_fijo", 0.01),
    ("riesgo 2%/trade", "riesgo_fijo", 0.02),
    ("riesgo 5%/trade", "riesgo_fijo", 0.05),
    (f"riesgo Kelly ({kelly:.0%})", "riesgo_fijo", kelly),
    ("riesgo medio-Kelly", "riesgo_fijo", kelly / 2),
    ("todo con 3x", "lev_fijo", 3),
    ("todo con 5x", "lev_fijo", 5),
    ("todo con 10x", "lev_fijo", 10),
    ("todo con 25x", "lev_fijo", 25),
]:
    med, p5, phalf, pruin, mdd, pliq = run_policy(kind, param)
    print(f"{label:28s} {med*1000:>8.0f}$ {p5*1000:>7.0f}$ {phalf:>8.1%} {pruin:>8.1%} {mdd:>6.1%} {pliq:>11.1%}")

print("\nNota: secuencial (no solapa trades), sin funding; liquidacion aproximada a 0.9/L.")
