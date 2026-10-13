"""
Cruce de las igniciones con el calendario de anuncios de Binance.

1) Descarga el historico de anuncios (catalogo 48 = nuevos listados, 93 =
   actividades/airdrops) hasta cubrir el rango del backtest.
2) Extrae los tickers mencionados en cada titulo: patron "(TOKEN)".
3) Para cada ignicion, busca anuncio que mencione su token en la ventana
   [-72h, +24h] alrededor del disparo.
4) Compara P(ganadora +40%) con y sin anuncio, por periodo.
"""
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
URL = "https://www.binance.com/bapi/apex/v1/public/apex/cms/article/list/query"
LIMIT_TS = pd.Timestamp("2023-08-01").timestamp() * 1000


def fetch_catalog(catalog_id, max_pages=80):
    rows = []
    for page in range(1, max_pages + 1):
        try:
            r = S.get(URL, params=dict(type=1, catalogId=catalog_id, pageNo=page,
                                       pageSize=50), timeout=30)
            arts = r.json()["data"]["catalogs"][0]["articles"]
        except Exception as ex:
            print(f"  catalogo {catalog_id} pag {page}: fin/error {ex}", file=sys.stderr, flush=True)
            break
        if not arts:
            break
        rows += [(a["title"], a["releaseDate"]) for a in arts]
        print(f"  catalogo {catalog_id} pag {page}: {len(arts)} (hasta "
              f"{pd.to_datetime(arts[-1]['releaseDate'], unit='ms').date()})",
              file=sys.stderr, flush=True)
        if arts[-1]["releaseDate"] < LIMIT_TS:
            break
        time.sleep(0.4)
    return rows


rows = fetch_catalog(48) + fetch_catalog(93)
ann = pd.DataFrame(rows, columns=["title", "ts"]).drop_duplicates()
ann["t"] = pd.to_datetime(ann["ts"], unit="ms")
ann["tokens"] = ann["title"].apply(lambda s: set(re.findall(r"\(([A-Z0-9]{2,12})\)", s)))
ann.to_csv("announcements.csv", index=False)
print(f"\n{len(ann)} anuncios desde {ann['t'].min().date()} hasta {ann['t'].max().date()}")

feats = pd.read_csv("ignition_features.csv", parse_dates=["t"])
feats["base"] = feats["symbol"].str.replace("USDT", "", regex=False) \
                               .str.replace(r"^1000+", "", regex=True)

def has_ann(row):
    lo, hi = row["t"] - pd.Timedelta(hours=72), row["t"] + pd.Timedelta(hours=24)
    m = ann[(ann["t"] >= lo) & (ann["t"] <= hi)]
    return any(row["base"] in tk for tk in m["tokens"])

feats["catalizador"] = feats.apply(has_ann, axis=1)
print(f"\nIgniciones con anuncio Binance en [-72h,+24h]: "
      f"{feats['catalizador'].sum()} de {len(feats)} ({feats['catalizador'].mean():.1%})")
print(f"\n{'grupo':22s} {'per':4s} {'n':>5s} {'P(ganadora +40%)':>17s}")
for (per, cat), g in feats.groupby(["periodo", "catalizador"]):
    label = "con anuncio" if cat else "sin anuncio"
    if len(g) < 5:
        continue
    print(f"{label:22s} {per:4s} {len(g):>5d} {g['ganadora'].mean():>16.1%}")
