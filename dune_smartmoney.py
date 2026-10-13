"""
Piloto "smart money": ¿existen wallets que compran ANTES (72h..6h previas) de
varias igniciones ganadoras distintas, y no de las basura?

Saca los 200 mayores compradores pre-ignicion de cada evento (15 ganadoras +
15 basura, BSC) y mide recurrencia entre SIMBOLOS distintos por clase.
Los bots/routers aparecen en ambas clases por igual: la senal seria recurrencia
sesgada hacia las ganadoras.
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


ev = pd.read_csv("ignitions.csv", parse_dates=["t"])
ev["base"] = ev["symbol"].str.replace("USDT", "", regex=False).str.replace(r"^1000+", "", regex=True)
mapping = cg_bsc_map(sorted(ev["base"].unique()))
ev = ev[ev["base"].isin(mapping)]
gan = ev[ev["fwd_max"] >= 0.40].sample(frac=1, random_state=7).head(15)
bas = ev[ev["fwd_max"] < 0.10].sample(frac=1, random_state=7).head(15)
sel = pd.concat([gan.assign(clase="ganadora"), bas.assign(clase="basura")])

vals = []
for _, e in sel.iterrows():
    addr = mapping[e["base"]].lower().replace("0x", "")
    t0 = pd.Timestamp(e["t"]).strftime("%Y-%m-%d %H:%M:%S")
    vals.append(f"('{e['base']}', FROM_HEX('{addr}'), TIMESTAMP '{t0}', '{e['clase']}')")

SQL = f"""
WITH e(sym, token, t0, clase) AS (VALUES
  {',\n  '.join(vals)}
),
buys AS (
  SELECT e.sym, e.clase, d.taker AS wallet, sum(d.amount_usd) AS usd
  FROM e
  JOIN dex.trades d
    ON d.blockchain = 'bnb'
   AND d.token_bought_address = e.token
   AND d.block_time BETWEEN e.t0 - INTERVAL '72' hour AND e.t0 - INTERVAL '6' hour
  GROUP BY 1, 2, 3
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY sym, t0_rank ORDER BY usd DESC) AS rn
  FROM (SELECT b.*, CONCAT(b.sym, b.clase) AS t0_rank FROM buys b)
)
SELECT sym, clase, CAST(wallet AS varchar) AS wallet, usd
FROM ranked
WHERE rn <= 200
"""

r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "ignition_smartmoney", "query_sql": SQL, "is_private": True})
r.raise_for_status()
qid = r.json()["query_id"]
print(f"query {qid} creada", file=sys.stderr, flush=True)
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
rows = res.get("result", {}).get("rows", [])
df = pd.DataFrame(rows)
df["usd"] = pd.to_numeric(df["usd"], errors="coerce")
df.to_csv("smartmoney_raw.csv", index=False)
print(f"{len(df)} filas wallet-evento\n")

# recurrencia entre SIMBOLOS distintos por clase
rec = (df.groupby(["wallet", "clase"])["sym"].nunique().unstack(fill_value=0)
       .rename(columns={"ganadora": "n_gan", "basura": "n_bas"}))
for c in ("n_gan", "n_bas"):
    if c not in rec:
        rec[c] = 0
print("Distribucion de recurrencia (n wallets):")
print(f"  en >=2 ganadoras distintas: {(rec['n_gan'] >= 2).sum()}")
print(f"  en >=3 ganadoras distintas: {(rec['n_gan'] >= 3).sum()}")
print(f"  en >=2 basura distintas:    {(rec['n_bas'] >= 2).sum()}")
print(f"  en >=3 basura distintas:    {(rec['n_bas'] >= 3).sum()}")
exclusivas = rec[(rec["n_gan"] >= 2) & (rec["n_bas"] == 0)]
bots = rec[(rec["n_gan"] >= 2) & (rec["n_bas"] >= 2)]
print(f"\n  'smart' candidatas (>=2 ganadoras, 0 basura): {len(exclusivas)}")
print(f"  bots/mixtas (>=2 y >=2):                      {len(bots)}")
if len(exclusivas):
    top = exclusivas.sort_values("n_gan", ascending=False).head(10)
    print("\nTop candidatas:")
    for w, r_ in top.iterrows():
        syms = df[(df["wallet"] == w) & (df["clase"] == "ganadora")]["sym"].unique()
        usd = df[df["wallet"] == w]["usd"].sum()
        print(f"  {w[:20]}...  {int(r_['n_gan'])} ganadoras ({', '.join(syms)})  {usd:,.0f}$")
rec.to_csv("smartmoney_recurrence.csv")
