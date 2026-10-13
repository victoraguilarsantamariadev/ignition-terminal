"""
Capa NARRATIVA (fuente nueva: categorias de CoinGecko).

H1: ¿la categoria del token (MEME/AI/GAMING/DEFI/INFRA/OTRO) predice ganadora?
H2 "calor sectorial": ¿ignicion cuya categoria tuvo OTRA ignicion en los 7 dias
   previos (narrativa caliente) rinde mas? Examen descriptivo + trade real, A/B.

Pre-registro: promocion solo si el trade real mejora en AMBOS periodos.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

from momentum_ignition import detect, load, simulate, SPLIT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

S = requests.Session()
CG = "https://api.coingecko.com/api/v3"
CACHE = "categorias.json"


def cg(path, **params):
    for _ in range(8):
        r = S.get(f"{CG}/{path}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(30)
            continue
        if r.status_code != 200:
            return None
        time.sleep(2.6)  # limite free ~25/min
        return r.json()
    return None


def bucket(cats):
    c = " | ".join(cats).lower()
    if "meme" in c:
        return "MEME"
    if "artificial intelligence" in c or "ai agents" in c or "ai " in c:
        return "AI"
    if "gaming" in c or "play to earn" in c or "metaverse" in c:
        return "GAMING"
    if "defi" in c or "decentralized finance" in c or "yield" in c or "dex" in c:
        return "DEFI"
    if "layer 1" in c or "layer 2" in c or "smart contract platform" in c or "infrastructure" in c:
        return "INFRA"
    return "OTRO"


def resolver_categorias(bases):
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    lista = cg("coins/list") or []
    cands = {}
    for c in lista:
        s = c["symbol"].lower()
        if s in bases:
            cands.setdefault(s, []).append(c["id"])
    # desambiguar por market cap
    todos = [i for ids in cands.values() for i in ids]
    mcap = {}
    for k in range(0, len(todos), 250):
        page = cg("coins/markets", vs_currency="usd", ids=",".join(todos[k:k + 250]),
                  per_page=250) or []
        for m in page:
            mcap[m["id"]] = m.get("market_cap") or 0
    elegido = {s: max(ids, key=lambda i: mcap.get(i, 0)) for s, ids in cands.items()}
    out = {}
    for n, (s, cid) in enumerate(sorted(elegido.items()), 1):
        d = cg(f"coins/{cid}", localization="false", tickers="false",
               market_data="false", community_data="false", developer_data="false")
        cats = [x for x in (d or {}).get("categories", []) if x]
        out[s] = bucket(cats)
        print(f"[{n}/{len(elegido)}] {s}: {out[s]}", file=sys.stderr, flush=True)
    json.dump(out, open(CACHE, "w"))
    return out


def main():
    frames, events = {}, []
    import glob
    for f in sorted(glob.glob(".cache_1h/*_perp_1h_1100.csv")):
        sym = os.path.basename(f).split("_")[0]
        hp = load(f)
        if hp is None:
            continue
        frames[sym] = hp
        events += detect(hp, sym)
    ev = pd.DataFrame(events)
    ev["t"] = pd.to_datetime(ev["t"])
    ev["base"] = (ev["symbol"].str.replace("USDT", "", regex=False)
                  .str.replace(r"^1000+", "", regex=True).str.lower())
    cats = resolver_categorias(set(ev["base"]))
    ev["cat"] = ev["base"].map(cats).fillna("OTRO")
    ev["periodo"] = np.where(ev["t"] < SPLIT, "A", "B")
    ev["ganadora"] = ev["fwd_max"] >= 0.40
    ev = ev.sort_values("t").reset_index(drop=True)

    print(f"\n[H1] P(ganadora +40%) por categoria y periodo:")
    for (p, c), g in ev.groupby(["periodo", "cat"]):
        if len(g) < 25:
            continue
        print(f"  {p} {c:7s} n={len(g):>4d}  P={g['ganadora'].mean():.1%}")

    # H2: calor sectorial causal (otra ignicion de la MISMA categoria en 7d previos,
    # de otro simbolo)
    hot = []
    for k, e in ev.iterrows():
        prev = ev[(ev["t"] >= e["t"] - pd.Timedelta(days=7)) & (ev["t"] < e["t"])
                  & (ev["cat"] == e["cat"]) & (ev["symbol"] != e["symbol"])]
        hot.append(len(prev) > 0)
    ev["sector_hot"] = hot

    print(f"\n[H2] Calor sectorial (misma narrativa activa en 7d previos):")
    for (p, h), g in ev.groupby(["periodo", "sector_hot"]):
        print(f"  {p} {'CALIENTE' if h else 'fria    '} n={len(g):>4d}  "
              f"P(+40%)={g['ganadora'].mean():.1%}  fwd_ret {g['fwd_ret'].mean():+.2%}")

    print(f"\n[H2-trade] Examen real (stop 8%/TP40), sector caliente vs frio:")
    print(f"{'grupo':12s} {'per':4s} {'n':>5s} {'exp':>7s} {'wr':>6s} {'PF':>5s}")
    for gname, mask in [("caliente", ev["sector_hot"]), ("frio", ~ev["sector_hot"])]:
        rows = {"A": [], "B": []}
        for k in np.flatnonzero(mask.to_numpy()):
            e = ev.iloc[k]
            r = simulate(frames[e["symbol"]], e, 0.08, 0.40)
            if r:
                rows[e["periodo"]].append(r[0])
        for p in ("A", "B"):
            rr = np.array(rows[p])
            if len(rr) < 25:
                continue
            wins, losses = rr[rr > 0], rr[rr <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
            print(f"{gname:12s} {p:4s} {len(rr):>5d} {rr.mean():>+6.2%} {(rr>0).mean():>5.1%} {pf:>5.2f}")

    ev.to_csv("narrative_events.csv", index=False)


if __name__ == "__main__":
    main()
