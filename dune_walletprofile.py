"""
Perfil de las 128 wallets candidatas: TODO su trading DEX en BSC desde 2025-06.

Por wallet-token: USD comprado/vendido y cantidades -> precio medio de compra
vs precio medio de venta = PnL REALIZADO por posicion.
Responde:
  1) ¿Aciertan en general (edge real) o solo en nuestra muestra (suerte)?
  2) ¿Coordinacion? (muchas candidatas comprando el mismo token casi a la vez)
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

QUOTES = {  # tokens-moneda a excluir (compras de WBNB/stables no son "picks")
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
}

rec = pd.read_csv("smartmoney_recurrence.csv", index_col=0)
cands = rec[(rec["n_gan"] >= 2) & (rec["n_bas"] == 0)].index.tolist()
w_vals = [f"(FROM_HEX('{w.lower().replace('0x','')}'))" for w in cands]

SQL = f"""
WITH sw(wallet) AS (VALUES
  {',\n  '.join(w_vals)}
),
b AS (
  SELECT taker AS wallet, token_bought_address AS token,
         sum(amount_usd) AS usd_b, sum(token_bought_amount) AS amt_b,
         min(block_time) AS t_first_buy, count(*) AS n_buys
  FROM dex.trades
  WHERE blockchain = 'bnb'
    AND taker IN (SELECT wallet FROM sw)
    AND block_time >= TIMESTAMP '2025-06-01'
    AND amount_usd > 50
  GROUP BY 1, 2
),
s AS (
  SELECT taker AS wallet, token_sold_address AS token,
         sum(amount_usd) AS usd_s, sum(token_sold_amount) AS amt_s
  FROM dex.trades
  WHERE blockchain = 'bnb'
    AND taker IN (SELECT wallet FROM sw)
    AND block_time >= TIMESTAMP '2025-06-01'
    AND amount_usd > 50
  GROUP BY 1, 2
)
SELECT CAST(b.wallet AS varchar) AS wallet, CAST(b.token AS varchar) AS token,
       b.usd_b, b.amt_b, CAST(b.t_first_buy AS varchar) AS t_first_buy, b.n_buys,
       COALESCE(s.usd_s, 0) AS usd_s, COALESCE(s.amt_s, 0) AS amt_s
FROM b
LEFT JOIN s ON b.wallet = s.wallet AND b.token = s.token
WHERE b.usd_b >= 300
ORDER BY b.usd_b DESC
LIMIT 3000
"""

r = requests.post(f"{DUNE}/query", headers=H, timeout=30,
                  json={"name": "smartmoney_profile", "query_sql": SQL, "is_private": True})
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
res = requests.get(f"{DUNE}/execution/{eid}/results", headers=H, timeout=90).json()
if state == "QUERY_STATE_FAILED":
    print("FALLO SQL:", json.dumps(res)[:800])
    sys.exit(1)
df = pd.DataFrame(res.get("result", {}).get("rows", []))
for c in ["usd_b", "amt_b", "usd_s", "amt_s", "n_buys"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["t_first_buy"] = pd.to_datetime(df["t_first_buy"])
df = df[~df["token"].str.lower().isin(QUOTES)]
df.to_csv("smartmoney_profile.csv", index=False)

# PnL realizado por posicion (solo donde han vendido algo significativo)
pos = df[(df["amt_s"] > 0) & (df["amt_b"] > 0)].copy()
pos = pos[pos["amt_s"] <= pos["amt_b"] * 1.10]          # sanidad
pos["px_b"] = pos["usd_b"] / pos["amt_b"]
pos["px_s"] = pos["usd_s"] / pos["amt_s"]
pos["ratio"] = pos["px_s"] / pos["px_b"]
pos = pos[(pos["ratio"] > 0.01) & (pos["ratio"] < 100)]  # fuera outliers absurdos

print(f"\n{df['wallet'].nunique()} wallets activas | {len(df)} posiciones | "
      f"{len(pos)} con PnL realizado medible")
print(f"\nPnL realizado global de sus posiciones (precio venta / precio compra):")
print(f"  mediana {pos['ratio'].median():.2f}x | media {pos['ratio'].mean():.2f}x | "
      f"% posiciones ganadoras: {(pos['ratio'] > 1).mean():.0%}")

wal = pos.groupby("wallet").agg(n_pos=("ratio", "size"), med_ratio=("ratio", "median"),
                                win=("ratio", lambda x: (x > 1).mean()),
                                usd=("usd_b", "sum")).sort_values("usd", ascending=False)
serias = wal[wal["n_pos"] >= 5]
print(f"\nWallets con >=5 posiciones cerradas: {len(serias)}")
print(f"  % de esas wallets con winrate > 50%: {(serias['win'] > 0.5).mean():.0%}")
print(f"  mediana de su ratio mediano: {serias['med_ratio'].median():.2f}x")
print(f"\nTop 12 por capital:")
print(serias.head(12).round(2).to_string())

# coordinacion: tokens con muchas candidatas comprando en ventana corta
co = df.groupby("token").agg(n_wallets=("wallet", "nunique"),
                             usd=("usd_b", "sum"),
                             primer=("t_first_buy", "min"),
                             ultimo=("t_first_buy", "max"))
co["span_h"] = (co["ultimo"] - co["primer"]).dt.total_seconds() / 3600
co = co[co["n_wallets"] >= 10].sort_values("n_wallets", ascending=False)
print(f"\nCoordinacion — tokens comprados por >=10 candidatas (span = horas entre primera y ultima):")
print(co.head(10)[["n_wallets", "usd", "span_h"]].round(0).to_string())
