"""¿El tape anade informacion mas alla de la liquidez del par?"""
import sys

import pandas as pd
from scipy.stats import mannwhitneyu

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

tape = pd.read_csv("ignition_tape.csv", parse_dates=["t"])
feats = pd.read_csv("ignition_features.csv", parse_dates=["t"])
df = tape.merge(feats[["symbol", "t", "liq_30d"]], on=["symbol", "t"], how="inner")
df["liq_usd"] = 10 ** df["liq_30d"]
print(f"{len(df)} eventos emparejados con liquidez")
print(f"correlacion avg_trade vs liq:  {df['avg_trade'].corr(df['liq_30d']):.2f}")
print(f"correlacion share_50k vs liq:  {df['share_50k'].corr(df['liq_30d']):.2f}")

sub = df[df["liq_usd"] < 100e6]
g = sub[sub["clase"] == "ganadora"]
b = sub[sub["clase"] == "basura"]
print(f"\nSolo pares NO gigantes (<100M$/dia): {len(g)} ganadoras vs {len(b)} basura")
for f in ["share_10k", "share_50k", "avg_trade", "max_print", "imb_10k"]:
    p = mannwhitneyu(g[f].dropna(), b[f].dropna()).pvalue
    print(f"  {f:12s} med_G={g[f].median():>9.4f}  med_B={b[f].median():>9.4f}  p={p:.4f}")
