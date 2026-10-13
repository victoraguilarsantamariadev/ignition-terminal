"""
¿Los modelos "top" (boosting, random forest) superan el techo de la logistica?
Mismo protocolo: entrena en periodo A, evalua en B (nunca visto). Si el limite
es de INFORMACION, todos convergen ~0.62; si era del MODELO, el boosting sube.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from momentum_ignition import detect, load, SPLIT

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
times = ev["t"]
ev["calor"] = [((times >= t - pd.Timedelta(hours=24)) & (times < t)).sum() for t in times]
liq = []
for _, e in ev.iterrows():
    hp = frames[e["symbol"]]
    liq.append(hp.iloc[max(0, e["i"] - 720):e["i"]]["qv"].resample("1D").sum().median())
ev["liq_d"] = np.log10(np.maximum(liq, 1))
ld = {k: pd.Timestamp(v, unit="ms") for k, v in json.load(open("listing_dates.json")).items()}
ev["edad_d"] = [(t - ld.get(s, pd.Timestamp("2000-01-01"))).days
                for s, t in zip(ev["symbol"], ev["t"])]
cats = json.load(open("categorias.json"))
ev["base"] = (ev["symbol"].str.replace("USDT", "", regex=False)
              .str.replace(r"^1000+", "", regex=True).str.lower())
ev["es_meme"] = (ev["base"].map(cats) == "MEME").astype(int)
ctx = pd.read_csv("ignition_features.csv", parse_dates=["t"])
df = ev.merge(ctx.drop(columns=["periodo", "liq_30d"], errors="ignore"),
              on=["symbol", "t"], how="left")
try:
    bb = pd.read_csv("ignitions_bybit.csv", parse_dates=["t"])
    df = df.merge(bb[["symbol", "t", "volx_bybit"]], on=["symbol", "t"], how="left")
except Exception:
    df["volx_bybit"] = np.nan
df["y"] = (df["fwd_max"] >= 0.40).astype(int)
df["periodo"] = np.where(df["t"] < SPLIT, "A", "B")

FEATS = ["ign_ret", "volx", "delta_share", "calor", "liq_d", "edad_d", "es_meme",
         "btc_ret24", "btc_trend20", "pos_30d", "limpieza", "spot_part", "basis",
         "funding_d", "volx_bybit"]
for c in FEATS:
    df[c] = pd.to_numeric(df[c], errors="coerce")
    df[c] = df[c].fillna(df[c].median())
tr, te = df[df["periodo"] == "A"], df[df["periodo"] == "B"]
mu, sd = tr[FEATS].mean(), tr[FEATS].std().replace(0, 1)
Xtr, Xte = (tr[FEATS] - mu) / sd, (te[FEATS] - mu) / sd
ytr, yte = tr["y"], te["y"]
print(f"train A: {len(tr)} (P={ytr.mean():.1%}) | test B: {len(te)} (P={yte.mean():.1%})")
print(f"{len(FEATS)} features (todas las capas: mercado, contexto, edad, narrativa, Bybit)\n")
print(f"{'modelo':26s} {'AUC train':>9s} {'AUC B (real)':>12s} {'tercil top B':>12s}")
for name, m in [
    ("logistica regularizada", LogisticRegression(max_iter=3000, C=0.5)),
    ("gradient boosting", GradientBoostingClassifier(n_estimators=150, max_depth=3,
                                                     learning_rate=0.05, subsample=0.8,
                                                     random_state=7)),
    ("random forest", RandomForestClassifier(n_estimators=400, max_depth=5,
                                             min_samples_leaf=15, random_state=7)),
]:
    m.fit(Xtr, ytr)
    a_tr = roc_auc_score(ytr, m.predict_proba(Xtr)[:, 1])
    p_te = m.predict_proba(Xte)[:, 1]
    a_te = roc_auc_score(yte, p_te)
    top = yte[p_te >= np.quantile(p_te, 2 / 3)].mean()
    print(f"{name:26s} {a_tr:>9.3f} {a_te:>12.3f} {top:>11.1%}")
print("\n(tercil top B = P(+40%) en el tercio de senales que el modelo puntua mejor)")
