"""
¿Que separa las igniciones GANADORAS (+40% en 7d) de las BASURA (stop sin +40%)?

Features de contexto en el momento de la ignicion (todas computables en vivo):
  btc_ret24     retorno de BTC en las 24h previas (¿mercado empujando?)
  btc_trend20   BTC vs hace 20 dias (regimen)
  pos_30d       posicion del precio en el rango de 30d (1=rompiendo maximos,
                0=rebotando desde minimos)
  limpieza      cierre de la ignicion dentro del rango de la ventana 6h
                (1 = cierra en maximos, sin mecha: subida limpia)
  spot_part     volumen spot / volumen perp en la ventana (¿compra real?)
  basis         perp/spot - 1 en la ignicion
  funding_d     funding del dia de la ignicion
  liq_30d       volumen diario mediano 30d (log10) — tamano del par

Clases (stop 8% / TP +40%): GANADORA = alcanza +40% (limpia o tras stop);
BASURA = salta el stop y nunca llega. El chop se excluye.
Juicio: Mann-Whitney + consistencia de direccion en periodos A/B.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from consensus_backtest import FAPI, klines_1h
from momentum_ignition import detect, load, SPLIT
from stop_autopsy import clasificar

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CACHE = ".cache_1h"

btc = klines_1h(FAPI, "BTCUSDT", 1100, CACHE)
btc_c = btc["c"]

frames, spot, fund, events = {}, {}, {}, []
for f in sorted(glob.glob(f"{CACHE}/*_perp_1h_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    hp = load(f)
    if hp is None:
        continue
    frames[sym] = hp
    sp_f = f"{CACHE}/{sym}_spot_1h_1100.csv"
    if os.path.exists(sp_f):
        spot[sym] = pd.read_csv(sp_f, index_col=0, parse_dates=True)
    fu_f = f"{CACHE}/{sym}_funding_1100.csv"
    if os.path.exists(fu_f):
        fund[sym] = pd.read_csv(fu_f, index_col=0, parse_dates=True).iloc[:, 0]
    events += detect(hp, sym)
print(f"{len(events)} igniciones", file=sys.stderr, flush=True)

rows = []
for e in events:
    sym, i, t = e["symbol"], e["i"], e["t"]
    hp = frames[sym]
    clase = clasificar(hp, e, 0.08, 0.40)
    if clase.startswith("chop"):
        continue
    w = hp.iloc[i - 5:i + 1]
    rng = w["h"].max() - w["l"].min()
    limpieza = (hp.iloc[i]["c"] - w["l"].min()) / rng if rng > 0 else np.nan
    j = btc_c.index.searchsorted(t)
    btc_ret24 = btc_trend20 = np.nan
    if 480 < j < len(btc_c):
        btc_ret24 = btc_c.iloc[j - 1] / btc_c.iloc[j - 25] - 1
        btc_trend20 = btc_c.iloc[j - 1] / btc_c.iloc[j - 481] - 1
    h30 = hp.iloc[max(0, i - 720):i]["h"].max()
    l30 = hp.iloc[max(0, i - 720):i]["l"].min()
    pos_30d = (e["entry"] - l30) / (h30 - l30) if h30 > l30 else np.nan
    sp = spot.get(sym)
    spot_part = basis = np.nan
    if sp is not None:
        sw = sp.reindex(w.index)
        if sw["qv"].notna().all():
            spot_part = sw["qv"].sum() / max(w["qv"].sum(), 1)
            basis = hp.iloc[i]["c"] / sw["c"].iloc[-1] - 1
    fu = fund.get(sym)
    funding_d = np.nan
    if fu is not None:
        k = fu.index.searchsorted(t)
        if k > 0:
            funding_d = fu.iloc[k - 1]
    liq = np.log10(max(hp.iloc[max(0, i - 720):i]["qv"].resample("1D").sum().median(), 1))
    rows.append(dict(symbol=sym, t=t, ganadora=clase.startswith("ganador"),
                     btc_ret24=btc_ret24, btc_trend20=btc_trend20, pos_30d=pos_30d,
                     limpieza=limpieza, spot_part=spot_part, basis=basis,
                     funding_d=funding_d, liq_30d=liq))

df = pd.DataFrame(rows)
df["periodo"] = np.where(df["t"] < SPLIT, "A", "B")
df.to_csv("ignition_features.csv", index=False)
g, b = df[df["ganadora"]], df[~df["ganadora"]]
print(f"\n{len(g)} ganadoras vs {len(b)} basura (chop excluido). "
      f"8 features -> umbral Bonferroni ~0.006\n")
print(f"{'feature':12s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
feats = ["btc_ret24", "btc_trend20", "pos_30d", "limpieza", "spot_part",
         "basis", "funding_d", "liq_30d"]
for f in feats:
    aa, bb = g[f].dropna(), b[f].dropna()
    if len(aa) < 30 or len(bb) < 30:
        continue
    p = mannwhitneyu(aa, bb).pvalue
    dirs = []
    for per in ("A", "B"):
        gg = df[(df["periodo"] == per) & df["ganadora"]][f].median()
        bb_ = df[(df["periodo"] == per) & ~df["ganadora"]][f].median()
        dirs.append("+" if gg > bb_ else "-")
    print(f"{f:12s} {aa.median():>10.4f} {bb.median():>10.4f} {p:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")
print("\n(dir A/B: '+' = ganadoras mas altas en ese periodo; buscamos p<0.006 Y misma direccion)")
