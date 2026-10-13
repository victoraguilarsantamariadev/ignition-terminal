"""
Control del walk-forward: misma seleccion de eventos test, pero devolviendo
TAMBIEN el total de compradores pre-ventana, para normalizar:
  share_smart = wallets candidatas / compradores totales
Si las candidatas solo marcan "memecoin BSC 2026 activo", el share sera similar
en ganadoras y basura activas; si son senal, estaran sobrerrepresentadas en
las ganadoras incluso entre eventos igual de activos.
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
gan_t = ev[ev["fwd_max"] >= 0.40].sample(frac=1, random_state=7).iloc[15:35]
bas_t = ev[ev["fwd_max"] < 0.10].sample(frac=1, random_state=7).iloc[15:35]
sel = pd.concat([gan_t.assign(clase="ganadora"), bas_t.assign(clase="basura")])

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
                  json={"name": "ignition_smartmoney_ctrl", "query_sql": SQL, "is_private": True})
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
df.to_csv("smartmoney_ctrl.csv", index=False)

print(f"{len(df)} eventos test con denominador:\n")
print(df.sort_values(["clase", "share_smart"], ascending=[True, False])
      [["sym", "clase", "n_total", "n_smart", "share_smart", "share_usd"]]
      .round(4).to_string(index=False))

# comparacion SOLO entre eventos activos (n_total >= 100): mismo nicho
act = df[df["n_total"] >= 100]
print(f"\nSolo eventos con actividad DEX real (n_total>=100): "
      f"{(act['clase']=='ganadora').sum()} gan vs {(act['clase']=='basura').sum()} bas")
for c, g in act.groupby("clase"):
    print(f"  {c:9s}: share_smart mediana {g['share_smart'].median():.4f} | "
          f"share_usd mediana {g['share_usd'].median():.4f} | n_total mediana {g['n_total'].median():.0f}")
try:
    from scipy.stats import mannwhitneyu
    g_ = act[act["clase"] == "ganadora"]["share_smart"].dropna()
    b_ = act[act["clase"] == "basura"]["share_smart"].dropna()
    if len(g_) >= 5 and len(b_) >= 5:
        print(f"  MW share_smart (solo activos): p={mannwhitneyu(g_, b_).pvalue:.4f}")
except Exception:
    pass
