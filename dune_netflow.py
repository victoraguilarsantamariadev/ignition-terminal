"""
On-chain #2: FLUJOS A/DESDE EXCHANGES durante la ignicion (BSC, via Dune).

Hipotesis: en las basura el token fluye HACIA los CEX durante la ignicion
(holders depositando para vender la subida); en las ganadoras no, o sale.

Usa las mismas 30 igniciones del piloto + tokens.transfers + cex.addresses.
"""
import sys
import time

import numpy as np
import pandas as pd
import requests
from scipy.stats import mannwhitneyu

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

KEY = open(".dune_key").read().strip()
H = {"X-Dune-API-Key": KEY, "Content-Type": "application/json"}
DUNE = "https://api.dune.com/api/v1"

# reutiliza la seleccion del piloto (misma semilla y fuente)
import json


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
cexaddr AS (
  SELECT address FROM cex.addresses WHERE blockchain = 'bnb'
)
SELECT e.sym, e.clase, CAST(e.t0 AS varchar) AS t0,
  sum(IF(t.block_time >  e.t0 - INTERVAL '6' hour
         AND t."to" IN (SELECT address FROM cexaddr), t.amount_usd, 0)) AS a_cex_ign,
  sum(IF(t.block_time >  e.t0 - INTERVAL '6' hour
         AND t."from" IN (SELECT address FROM cexaddr), t.amount_usd, 0)) AS de_cex_ign,
  sum(IF(t.block_time <= e.t0 - INTERVAL '6' hour
         AND t."to" IN (SELECT address FROM cexaddr), t.amount_usd, 0)) / 12.0 AS a_cex_prev,
  sum(IF(t.block_time <= e.t0 - INTERVAL '6' hour
         AND t."from" IN (SELECT address FROM cexaddr), t.amount_usd, 0)) / 12.0 AS de_cex_prev
FROM e
JOIN tokens.transfers t
  ON t.blockchain = 'bnb'
 AND t.contract_address = e.token
 AND t.block_time BETWEEN e.t0 - INTERVAL '78' hour AND e.t0
GROUP BY 1, 2, 3
"""

r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "ignition_netflow", "query_sql": SQL, "is_private": True})
r.raise_for_status()
qid = r.json()["query_id"]
print(f"query {qid} creada", file=sys.stderr, flush=True)
r = requests.post(f"{DUNE}/query/{qid}/execute", headers=H, timeout=30,
                  json={"performance": "medium"})
eid = r.json()["execution_id"]
state = None
for _ in range(60):
    time.sleep(10)
    st = requests.get(f"{DUNE}/execution/{eid}/status", headers=H, timeout=30).json()
    state = st.get("state")
    print("  estado:", state, file=sys.stderr, flush=True)
    if state in ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED"):
        break
res = requests.get(f"{DUNE}/execution/{eid}/results", headers=H, timeout=60).json()
if state == "QUERY_STATE_FAILED":
    print("FALLO SQL:", json.dumps(res)[:600])
    sys.exit(1)
rows = res.get("result", {}).get("rows", [])
df = pd.DataFrame(rows)
for c in ["a_cex_ign", "de_cex_ign", "a_cex_prev", "de_cex_prev"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["net_a_cex_ign"] = df["a_cex_ign"] - df["de_cex_ign"]          # >0 = entra al exchange (venta en camino)
df["ratio_a_cex"] = df["a_cex_ign"] / df["a_cex_prev"].replace(0, np.nan)
df.to_csv("onchain_netflow.csv", index=False)

print(f"{len(df)} eventos con flujos:\n")
print(df.sort_values(["clase"])[["sym", "clase", "a_cex_ign", "de_cex_ign",
                                 "net_a_cex_ign", "ratio_a_cex"]].round(0).to_string(index=False))
print("\nMedianas por clase:")
print(df.groupby("clase")[["a_cex_ign", "de_cex_ign", "net_a_cex_ign", "ratio_a_cex"]]
      .median().round(0).to_string())
g = df[df["clase"] == "ganadora"]["net_a_cex_ign"].dropna()
b = df[df["clase"] == "basura"]["net_a_cex_ign"].dropna()
if len(g) >= 5 and len(b) >= 5:
    print(f"\nMW net_a_cex: p={mannwhitneyu(g, b).pvalue:.4f}")
