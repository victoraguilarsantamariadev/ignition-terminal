"""
Fase 2 walk-forward: ¿la presencia de las 128 wallets candidatas ("smart")
compradas en la pre-ventana predice el resultado en eventos NUEVOS
(no usados para seleccionarlas)?
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
print(f"{len(cands)} wallets candidatas", file=sys.stderr)

ev = pd.read_csv("ignitions.csv", parse_dates=["t"])
ev["base"] = ev["symbol"].str.replace("USDT", "", regex=False).str.replace(r"^1000+", "", regex=True)
mapping = cg_bsc_map(sorted(ev["base"].unique()))
ev = ev[ev["base"].isin(mapping)]
gan_all = ev[ev["fwd_max"] >= 0.40].sample(frac=1, random_state=7)
bas_all = ev[ev["fwd_max"] < 0.10].sample(frac=1, random_state=7)
# test = los NO usados en el piloto (que fueron los 15 primeros de cada uno)
gan_t = gan_all.iloc[15:35]
bas_t = bas_all.iloc[15:35]
sel = pd.concat([gan_t.assign(clase="ganadora"), bas_t.assign(clase="basura")])
print(f"test: {len(gan_t)} ganadoras + {len(bas_t)} basura nuevas", file=sys.stderr)

ev_vals, w_vals = [], []
for _, e in sel.iterrows():
    addr = mapping[e["base"]].lower().replace("0x", "")
    t0 = pd.Timestamp(e["t"]).strftime("%Y-%m-%d %H:%M:%S")
    ev_vals.append(f"('{e['base']}_{t0[:10]}', FROM_HEX('{addr}'), TIMESTAMP '{t0}', '{e['clase']}')")
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
  count(DISTINCT d.taker) AS n_smart,
  sum(d.amount_usd) AS usd_smart
FROM e
LEFT JOIN dex.trades d
  ON d.blockchain = 'bnb'
 AND d.token_bought_address = e.token
 AND d.block_time BETWEEN e.t0 - INTERVAL '72' hour AND e.t0 - INTERVAL '6' hour
 AND d.taker IN (SELECT wallet FROM sw)
GROUP BY 1, 2
"""

r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "ignition_smartmoney_wf", "query_sql": SQL, "is_private": True})
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
df = pd.DataFrame(res.get("result", {}).get("rows", []))
df["n_smart"] = pd.to_numeric(df["n_smart"], errors="coerce").fillna(0)
df.to_csv("smartmoney_wf.csv", index=False)

print(f"{len(df)} eventos test:\n")
print(df.sort_values(["clase", "n_smart"], ascending=[True, False]).to_string(index=False))
print("\nPresencia de wallets candidatas (>=1 comprando en pre-ventana):")
for c, g in df.groupby("clase"):
    print(f"  {c:9s}: {(g['n_smart'] >= 1).mean():.0%} de los eventos "
          f"(media {g['n_smart'].mean():.1f} wallets)")
con = df[df["n_smart"] >= 1]
sin = df[df["n_smart"] == 0]
if len(con) >= 5 and len(sin) >= 5:
    print(f"\nP(ganadora | candidatas presentes) = {(con['clase']=='ganadora').mean():.0%}  (n={len(con)})")
    print(f"P(ganadora | sin candidatas)       = {(sin['clase']=='ganadora').mean():.0%}  (n={len(sin)})")
