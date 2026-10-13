"""
Juicio final a la tesis MM: el tape de la FASE DE CONTINUACION (t0+6h a t0+72h).

Prediccion tesis-MM:       en ganadoras, prints grandes COMPRANDO (imb_50k > 0)
                           y cuota de ballenas mayor que en basura.
Prediccion tesis-estampida: prints pequenos dominando tambien la continuacion,
                           grandes vendiendo (distribucion).

Reusa la muestra de ignition_tape.csv (85 ganadoras + 85 basura) y la
maquinaria de descarga/parseo de ignition_tape.py.
"""
import sys

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from ignition_tape import tape_feats
from momentum_ignition import SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

prev = pd.read_csv("ignition_tape.csv", parse_dates=["t"])
rows = []
for n, (_, e) in enumerate(prev.iterrows(), 1):
    t0 = pd.Timestamp(e["t"])
    ft = tape_feats(e["symbol"], t0 + pd.Timedelta(hours=6), t0 + pd.Timedelta(hours=72))
    if ft is None:
        continue
    rows.append(dict(clase=e["clase"], symbol=e["symbol"], t=e["t"], **ft))
    print(f"[{n}/{len(prev)}] {e['symbol']} {e['clase']}", file=sys.stderr, flush=True)

df = pd.DataFrame(rows)
df.to_csv("continuation_tape.csv", index=False)
df["periodo"] = np.where(pd.to_datetime(df["t"]) < SPLIT, "A", "B")
g, b = df[df["clase"] == "ganadora"], df[df["clase"] == "basura"]
feats = ["share_10k", "share_50k", "imb_10k", "imb_50k", "imb_small",
         "delta_share", "avg_trade", "max_print"]
print(f"\nCONTINUACION (t0+6h..t0+72h): {len(g)} ganadoras vs {len(b)} basura\n")
print(f"{'feature':12s} {'med_GANA':>10s} {'med_BASURA':>10s} {'p-MW':>8s} {'dir A':>6s} {'dir B':>6s}")
for f in feats:
    aa, bb = g[f].dropna(), b[f].dropna()
    if len(aa) < 25 or len(bb) < 25:
        continue
    pv = mannwhitneyu(aa, bb).pvalue
    dirs = []
    for per in ("A", "B"):
        gm = df[(df["periodo"] == per) & (df["clase"] == "ganadora")][f].median()
        bm = df[(df["periodo"] == per) & (df["clase"] == "basura")][f].median()
        dirs.append("+" if gm > bm else "-")
    print(f"{f:12s} {aa.median():>10.4f} {bb.median():>10.4f} {pv:>8.4f} {dirs[0]:>6s} {dirs[1]:>6s}")

# y el veredicto directo sobre la tesis MM: ¿los prints grandes COMPRAN la continuacion ganadora?
print("\nVeredicto tesis-MM (solo ganadoras, fase de continuacion):")
print(f"  imbalance prints >=50k$: mediana {g['imb_50k'].median():+.3f} "
      f"({'COMPRAN' if g['imb_50k'].median() > 0.02 else 'VENDEN' if g['imb_50k'].median() < -0.02 else 'neutros'})")
print(f"  imbalance prints >=10k$: mediana {g['imb_10k'].median():+.3f}")
print(f"  imbalance prints <1k$ (retail): mediana {g['imb_small'].median():+.3f}")
print(f"  cuota ballenas ganadoras vs basura: {g['share_50k'].median():.3f} vs {b['share_50k'].median():.3f}")
