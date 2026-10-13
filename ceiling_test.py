"""
1) Examen de ascenso de los candidatos pendientes (tamano de chispa, multiplo
   de volumen) a nivel de trade real, por periodo.
2) Techo multivariante: regresion logistica con TODAS las features, entrenada
   en el periodo A y evaluada en el B (AUC). Mide cuanta senal comun total
   existe en los datos de exchange para separar ganadoras de basura.
3) Stats del sistema final con todos los filtros ascendidos.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

frames, events = {}, []
for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
    sym = os.path.basename(f).split("_")[0]
    hp = load(f)
    if hp is None:
        continue
    frames[sym] = hp
    events += detect(hp, sym)
ev = pd.DataFrame(events)
ev["t"] = pd.to_datetime(ev["t"])
ev = ev.sort_values("t").reset_index(drop=True)

# calor causal y liquidez para cada evento
times = ev["t"]
ev["calor"] = [((times >= t - pd.Timedelta(hours=24)) & (times < t)).sum() for t in times]
liq = []
for _, e in ev.iterrows():
    hp = frames[e["symbol"]]
    liq.append(hp.iloc[max(0, e["i"] - 720):e["i"]]["qv"].resample("1D").sum().median())
ev["liq_d"] = liq
ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")

# ---------- 1) examen de chispa y volx ----------
print("=" * 70)
print("[1] EXAMEN trade real (stop 8% / TP 40%) de chispa y volx")
print(f"{'filtro':24s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
t1, t2 = ev["ign_ret"].quantile([1 / 3, 2 / 3])
v1, v2 = ev["volx"].quantile([1 / 3, 2 / 3])
for fname, mask in [
    ("chispa grande (top1/3)", ev["ign_ret"] >= t2),
    ("chispa pequena (bot1/3)", ev["ign_ret"] <= t1),
    ("volx alto (top1/3)", ev["volx"] >= v2),
    ("volx bajo (bot1/3)", ev["volx"] <= v1),
]:
    rows = {"A": [], "B": []}
    for k in np.flatnonzero(mask.to_numpy()):
        e = ev.iloc[k]
        r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
        if r:
            rows[e["periodo"]].append(r[0])
    for p in ("A", "B"):
        rr = np.array(rows[p])
        if len(rr) < 25:
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        print(f"{fname:24s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")

# ---------- 2) techo multivariante ----------
print("\n[2] TECHO MULTIVARIANTE (logistica, entrena A -> evalua B)")
ctx = pd.read_csv("ignition_features.csv", parse_dates=["t"])
df = ev.merge(ctx.drop(columns=["periodo"]), on=["symbol", "t"], how="inner")
df["ganadora"] = df["ganadora"].astype(int)
FEATS = ["ign_ret", "volx", "delta_share", "calor", "btc_ret24", "btc_trend20",
         "pos_30d", "limpieza", "spot_part", "basis", "funding_d", "liq_30d"]
df["liq_30d"] = df["liq_30d"].fillna(np.log10(df["liq_d"]))
sub = df.dropna(subset=[c for c in FEATS if c not in ("spot_part", "basis")]).copy()
for c in ("spot_part", "basis"):
    sub[c] = sub[c].fillna(sub[c].median())
tr, te = sub[sub["periodo"] == "A"], sub[sub["periodo"] == "B"]
mu, sd = tr[FEATS].mean(), tr[FEATS].std().replace(0, 1)
Xtr, Xte = (tr[FEATS] - mu) / sd, (te[FEATS] - mu) / sd
m = LogisticRegression(max_iter=2000, C=0.5).fit(Xtr, tr["ganadora"])
auc_tr = roc_auc_score(tr["ganadora"], m.predict_proba(Xtr)[:, 1])
auc_te = roc_auc_score(te["ganadora"], m.predict_proba(Xte)[:, 1])
print(f"  entrena A: n={len(tr)} (P(gan)={tr['ganadora'].mean():.1%}) -> AUC in-sample {auc_tr:.3f}")
print(f"  evalua  B: n={len(te)} (P(gan)={te['ganadora'].mean():.1%}) -> AUC out-of-sample {auc_te:.3f}")
proba = m.predict_proba(Xte)[:, 1]
top = te[proba >= np.quantile(proba, 2 / 3)]
bot = te[proba <= np.quantile(proba, 1 / 3)]
print(f"  en B: tercil superior del modelo P(gan)={top['ganadora'].mean():.1%} | "
      f"tercil inferior {bot['ganadora'].mean():.1%}")
coefs = sorted(zip(FEATS, m.coef_[0]), key=lambda x: -abs(x[1]))
print("  pesos (top 5):", ", ".join(f"{k}={v:+.2f}" for k, v in coefs[:5]))

# ---------- 3) sistema final con filtros ascendidos ----------
print("\n[3] SISTEMA FINAL: calor>=1 en 24h + par <100M$/dia")
mask = (ev["calor"] >= 1) & (ev["liq_d"] < 100e6)
rows = {"A": [], "B": []}
for k in np.flatnonzero(mask.to_numpy()):
    e = ev.iloc[k]
    r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
    if r:
        rows[e["periodo"]].append(r[0])
for p in ("A", "B"):
    rr = np.array(rows[p])
    wins, losses = rr[rr > 0], rr[rr <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
    print(f"  {p}: n={len(rr):>4d}  exp {rr.mean():+.2%}  wr {(rr>0).mean():.1%}  PF {pf:.2f}")
