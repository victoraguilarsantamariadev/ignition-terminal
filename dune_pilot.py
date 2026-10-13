"""
Piloto on-chain (Dune): ¿llega una avalancha de COMPRADORES UNICOS (wallets)
durante las igniciones ganadoras que no llega en las basura?

1) Mapea simbolo -> contrato BSC con CoinGecko (solo matches inequivocos).
2) Elige hasta 15 ganadoras (fwd_max>=40%) y 15 basura (fwd_max<10%) mapeadas.
3) Una sola query en Dune sobre dex.trades (blockchain='bnb'):
   compradores unicos y volumen en la ventana de ignicion (6h) vs la media
   por-6h de los 3 dias previos.
4) Compara ratios ganadoras vs basura.
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
print(f"{len(mapping)} tokens mapeados a contrato BSC de forma inequivoca", file=sys.stderr)

ev = ev[ev["base"].isin(mapping)]
gan = ev[ev["fwd_max"] >= 0.40].sample(frac=1, random_state=7).head(15)
bas = ev[ev["fwd_max"] < 0.10].sample(frac=1, random_state=7).head(15)
sel = pd.concat([gan.assign(clase="ganadora"), bas.assign(clase="basura")])
print(f"seleccionados {len(gan)} ganadoras + {len(bas)} basura", file=sys.stderr)

vals = []
for _, e in sel.iterrows():
    addr = mapping[e["base"]].lower().replace("0x", "")
    t0 = pd.Timestamp(e["t"]).strftime("%Y-%m-%d %H:%M:%S")
    vals.append(f"('{e['base']}', FROM_HEX('{addr}'), TIMESTAMP '{t0}', '{e['clase']}')")
sql = f"""
WITH e(sym, token, t0, clase) AS (VALUES
  {',\n  '.join(vals)}
)
SELECT e.sym, e.clase, CAST(e.t0 AS varchar) AS t0,
  count(DISTINCT IF(d.block_time >  e.t0 - INTERVAL '6' hour, d.taker)) AS buyers_ign,
  count(DISTINCT IF(d.block_time <= e.t0 - INTERVAL '6' hour, d.taker)) / 12.0 AS buyers_prev,
  sum(IF(d.block_time >  e.t0 - INTERVAL '6' hour, d.amount_usd, 0)) AS vol_ign,
  sum(IF(d.block_time <= e.t0 - INTERVAL '6' hour, d.amount_usd, 0)) / 12.0 AS vol_prev
FROM e
JOIN dex.trades d
  ON d.blockchain = 'bnb'
 AND d.token_bought_address = e.token
 AND d.block_time BETWEEN e.t0 - INTERVAL '78' hour AND e.t0
GROUP BY 1, 2, 3
"""
r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "ignition_onchain_pilot", "query_sql": sql, "is_private": True})
r.raise_for_status()
qid = r.json()["query_id"]
print(f"query {qid} creada, ejecutando...", file=sys.stderr)
r = requests.post(f"{DUNE}/query/{qid}/execute", headers=H, timeout=30,
                  json={"performance": "medium"})
r.raise_for_status()
eid = r.json()["execution_id"]
for _ in range(60):
    time.sleep(10)
    st = requests.get(f"{DUNE}/execution/{eid}/status", headers=H, timeout=30).json()
    print("  estado:", st.get("state"), file=sys.stderr, flush=True)
    if st.get("state") in ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED"):
        break
res = requests.get(f"{DUNE}/execution/{eid}/results", headers=H, timeout=60).json()
rows = res.get("result", {}).get("rows", [])
if not rows:
    print("SIN RESULTADOS:", json.dumps(res)[:500])
    sys.exit(1)
df = pd.DataFrame(rows)
df["ratio_buyers"] = df["buyers_ign"] / df["buyers_prev"].replace(0, np.nan)
df["ratio_vol"] = df["vol_ign"] / df["vol_prev"].replace(0, np.nan)
df.to_csv("onchain_pilot.csv", index=False)

print(f"\n{len(df)} eventos con datos on-chain (dex.trades BSC):\n")
print(df.sort_values(["clase", "ratio_buyers"], ascending=[True, False])
        [["sym", "clase", "t0", "buyers_ign", "buyers_prev", "ratio_buyers", "ratio_vol"]]
        .to_string(index=False))
print("\nMedianas por clase:")
print(df.groupby("clase")[["buyers_ign", "ratio_buyers", "ratio_vol"]].median().round(2).to_string())
try:
    from scipy.stats import mannwhitneyu
    g = df[df["clase"] == "ganadora"]["ratio_buyers"].dropna()
    b = df[df["clase"] == "basura"]["ratio_buyers"].dropna()
    if len(g) >= 5 and len(b) >= 5:
        print(f"\nMann-Whitney ratio_buyers: p={mannwhitneyu(g, b).pvalue:.4f}")
except Exception:
    pass
