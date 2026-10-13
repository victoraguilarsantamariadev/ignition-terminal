"""
Test decisivo: misma ERA (eventos desde 2025-08), excluyendo los 30 del piloto
de seleccion, con denominador. Si share_smart separa ganadoras de basura DENTRO
de la misma epoca/nicho, la tesis smart-money queda viva de verdad.
"""
import json
import sys
import time

import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY = open(".dune_key").read().strip()
H = {"X-Dune-API-Key": KEY, "Content-Type": "application/json"}
DUNE = "https://api.dune.com/api/v1"


def cg_bsc_map(bases):
    r = requests.get("https://api.coingecko.com/api/v3/coins/list",
                     params={"include_platform": "true"}, timeout=60)
    coins = r.json()
    out = {}
    for b in bases:
        cands = [c for c in coins if c["symbol"].lower() == b.lower()
                 and c.get("platforms", {}).get("binance-smart-chain")]
        if len(cands) == 1:
            out[b] = cands[0]["platforms"]["binance-smart-chain"]
    return out


rec = pd.read_csv("smartmoney_recurrence.csv", index_col=0)
cands = rec[(rec["n_gan"] >= 2) & (rec["n_bas"] == 0)].index.tolist()

ev = pd.read_csv("ignitions.csv", parse_dates=["t"])
ev["base"] = ev["symbol"].str.replace("USDT", "", regex=False).str.replace(r"^1000+", "", regex=True)
mapping = cg_bsc_map(sorted(ev["base"].unique()))
ev = ev[ev["base"].isin(mapping)]

# eventos del piloto de seleccion (mismas semillas) para excluirlos
gan_all = ev[ev["fwd_max"] >= 0.40].sample(frac=1, random_state=7)
bas_all = ev[ev["fwd_max"] < 0.10].sample(frac=1, random_state=7)
pilot_keys = set((r["symbol"], r["t"]) for _, r in
                 pd.concat([gan_all.head(15), bas_all.head(15)]).iterrows())

era = ev[ev["t"] >= "2025-08-01"]
era = era[~era.apply(lambda r: (r["symbol"], r["t"]) in pilot_keys, axis=1)]
gan_t = era[era["fwd_max"] >= 0.40].sample(frac=1, random_state=11).head(40)
bas_t = era[era["fwd_max"] < 0.10].sample(frac=1, random_state=11).head(40)
sel = pd.concat([gan_t.assign(clase="ganadora"), bas_t.assign(clase="basura")])
print(f"test era 2025-08+: {len(gan_t)} gan + {len(bas_t)} bas", file=sys.stderr)

ev_vals, w_vals = [], []
for _, e in sel.iterrows():
    addr = mapping[e["base"]].lower().replace("0x", "")
    t0 = pd.Timestamp(e["t"]).strftime("%Y-%m-%d %H:%M:%S")
    ev_vals.append(f"('{e['base']}_{t0[:13]}', FROM_HEX('{addr}'), TIMESTAMP '{t0}', '{e['clase']}')")
for w in cands:
    w_vals.append(f"(FROM_HEX('{w.lower().replace('0x','')}'))")

SQL = f"""
WITH e(sym, token, t0, clase) AS (VALUES
  {',\n  '.join(ev_vals)}
),
sw(wallet) AS (VALUES
  {',\n  '.join(w_vals)}
)
SELECT e.sym, e.clase,
  count(DISTINCT d.taker) AS n_total,
  count(DISTINCT IF(d.taker IN (SELECT wallet FROM sw), d.taker)) AS n_smart,
  sum(d.amount_usd) AS usd_total,
  sum(IF(d.taker IN (SELECT wallet FROM sw), d.amount_usd, 0)) AS usd_smart
FROM e
LEFT JOIN dex.trades d
  ON d.blockchain = 'bnb'
 AND d.token_bought_address = e.token
 AND d.block_time BETWEEN e.t0 - INTERVAL '72' hour AND e.t0 - INTERVAL '6' hour
GROUP BY 1, 2
"""

r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "ignition_smartmoney_era", "query_sql": SQL, "is_private": True})
r.raise_for_status()
qid = r.json()["query_id"]
r = requests.post(f"{DUNE}/query/{qid}/execute", headers=H, timeout=30,
                  json={"performance": "medium"})
eid = r.json()["execution_id"]
state = None
for _ in range(90):
    time.sleep(10)
    st = requests.get(f"{DUNE}/execution/{eid}/status", headers=H, timeout=30).json()
    state = st.get("state")
    print("  estado:", state, file=sys.stderr, flush=True)
    if state in ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED"):
        break
res = requests.get(f"{DUNE}/execution/{eid}/results", headers=H, timeout=60).json()
if state == "QUERY_STATE_FAILED":
    print("FALLO SQL:", json.dumps(res)[:800])
    sys.exit(1)
df = pd.DataFrame(res.get("result", {}).get("rows", []))
for c in ["n_total", "n_smart", "usd_total", "usd_smart"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
df["share_smart"] = df["n_smart"] / df["n_total"].replace(0, np.nan)
df["share_usd"] = df["usd_smart"] / df["usd_total"].replace(0, np.nan)
df.to_csv("smartmoney_era.csv", index=False)

act = df[df["n_total"] >= 50]
print(f"\n{len(df)} eventos misma era | con actividad (n_total>=50): "
      f"{(act['clase']=='ganadora').sum()} gan vs {(act['clase']=='basura').sum()} bas\n")
for c, g in act.groupby("clase"):
    print(f"  {c:9s}: share_smart mediana {g['share_smart'].median():.4f} | media {g['share_smart'].mean():.4f} | "
          f"share_usd mediana {g['share_usd'].median():.4f} | P(share>2%)={ (g['share_smart']>0.02).mean():.0%}")
from scipy.stats import mannwhitneyu
g_ = act[act["clase"] == "ganadora"]["share_smart"].dropna()
b_ = act[act["clase"] == "basura"]["share_smart"].dropna()
if len(g_) >= 8 and len(b_) >= 8:
    print(f"\n  MW share_smart: p={mannwhitneyu(g_, b_).pvalue:.4f}")
    gu = act[act["clase"] == "ganadora"]["share_usd"].dropna()
    bu = act[act["clase"] == "basura"]["share_usd"].dropna()
    print(f"  MW share_usd:   p={mannwhitneyu(gu, bu).pvalue:.4f}")
# y la version "filtro": P(ganadora | share_usd > 5%)
hi = act[act["share_usd"] > 0.05]
lo = act[act["share_usd"] <= 0.05]
if len(hi) >= 5:
    print(f"\n  P(ganadora | share_usd>5%) = {(hi['clase']=='ganadora').mean():.0%} (n={len(hi)})")
    print(f"  P(ganadora | share_usd<=5%) = {(lo['clase']=='ganadora').mean():.0%} (n={len(lo)})")
