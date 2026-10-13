"""Capa visual del IGNITION TERMINAL. El escaner (ignition_scan.py) la importa."""
import itertools
from urllib.parse import quote as _q

import requests

S = requests.Session()
_uid = itertools.count()
try:
    import json as _json
    _CATS = _json.load(open("categorias.json"))
except Exception:
    _CATS = {}

# tokens (superficie oscura #10151d)
INK, MUT = "#dbe4ee", "#8fa0b3"
GRN, RED, AMB, BLU = "#4cc38a", "#f1655f", "#e5b567", "#6cb1ff"
BG, SURF, BORDER = "#0a0e14", "#10151d", "#202b3a"


def fetch_news(base):
    import xml.etree.ElementTree as ET
    try:
        r = S.get("https://news.google.com/rss/search",
                  params={"q": f"{base} crypto", "hl": "es"}, timeout=8)
        root = ET.fromstring(r.content)
        out = []
        for item in root.iter("item"):
            out.append((item.findtext("title") or "", item.findtext("link") or "",
                        (item.findtext("pubDate") or "")[:16]))
            if len(out) >= 3:
                break
        return out
    except Exception:
        return []


def _fmt(p):
    return f"{p:.6g}"


def _area_svg(closes, marker_px, marker_name):
    if not closes or len(closes) < 5:
        return ""
    uid = next(_uid)
    W, H, PADR = 560, 84, 64
    lo, hi = min(closes), max(closes)
    if marker_px:
        lo, hi = min(lo, marker_px), max(hi, marker_px)
    rng = (hi - lo) or 1e-12
    xs = lambda k: k * (W - PADR) / (len(closes) - 1)
    ys = lambda c: H - 8 - (c - lo) / rng * (H - 20)
    pts = " ".join(f"{xs(k):.1f},{ys(c):.1f}" for k, c in enumerate(closes))
    up = closes[-1] >= closes[0]
    col = GRN if up else RED
    area = f"0,{H-8} {pts} {xs(len(closes)-1):.1f},{H-8}"
    mk = ""
    if marker_px and lo <= marker_px <= hi:
        y = ys(marker_px)
        mk = (f'<line x1="0" y1="{y:.1f}" x2="{W-PADR}" y2="{y:.1f}" stroke="{AMB}" '
              f'stroke-width="1" stroke-dasharray="4,4" opacity=".9"/>'
              f'<text x="{W-PADR+6}" y="{y+3:.1f}" fill="{AMB}" font-size="10" '
              f'font-family="JetBrains Mono,monospace">{marker_name} {_fmt(marker_px)}</text>')
    dot = f'<circle cx="{xs(len(closes)-1):.1f}" cy="{ys(closes[-1]):.1f}" r="3" fill="{col}"/>'
    last = (f'<text x="{W-PADR+6}" y="{ys(closes[-1])+3:.1f}" fill="{INK}" font-size="10" '
            f'font-family="JetBrains Mono,monospace">{_fmt(closes[-1])}</text>')
    return f"""<svg viewBox="0 0 {W} {H}" style="width:100%;height:{H}px;display:block">
<title>ultimas 48h · min {_fmt(min(closes))} · max {_fmt(max(closes))} · ultimo {_fmt(closes[-1])}</title>
<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="{col}" stop-opacity=".25"/>
<stop offset="100%" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>
<polygon points="{area}" fill="url(#g{uid})"/>
<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"
 stroke-linejoin="round"/>{mk}{dot}{last}</svg>"""


def _levels_svg(stop8, estruct, entry, tp, now):
    W, H = 560, 46
    lo = min(stop8, estruct, now) * 0.995
    hi = max(tp, now) * 1.005
    x = lambda p: 8 + (p - lo) / (hi - lo) * (W - 16)
    def tick(p, name, color, top):
        px, ty, ny = x(p), (12 if top else H - 4), (22 if top else H - 14)
        return (f'<line x1="{px:.0f}" y1="16" x2="{px:.0f}" y2="{H-18}" stroke="{color}" stroke-width="2"/>'
                f'<text x="{px:.0f}" y="{ty}" fill="{MUT}" font-size="8.5" text-anchor="middle" '
                f'letter-spacing="1">{name}</text>'
                f'<text x="{px:.0f}" y="{ny}" fill="{color}" font-size="9.5" text-anchor="middle" '
                f'font-family="JetBrains Mono,monospace">{_fmt(p)}</text>') if False else (
                f'<line x1="{px:.0f}" y1="16" x2="{px:.0f}" y2="{H-16}" stroke="{color}" stroke-width="2"/>'
                f'<text x="{px:.0f}" y="{10 if top else H-2}" fill="{MUT}" font-size="8.5" '
                f'text-anchor="middle" letter-spacing="1">{name} <tspan fill="{color}" '
                f'font-family="JetBrains Mono,monospace" font-size="9.5">{_fmt(p)}</tspan></text>')
    mid = H / 2
    seg = (f'<line x1="{x(min(stop8,estruct)):.0f}" y1="{mid}" x2="{x(entry):.0f}" y2="{mid}" '
           f'stroke="{RED}" stroke-width="3" opacity=".35"/>'
           f'<line x1="{x(entry):.0f}" y1="{mid}" x2="{x(tp):.0f}" y2="{mid}" '
           f'stroke="{GRN}" stroke-width="3" opacity=".35"/>')
    now_dot = (f'<circle cx="{x(now):.0f}" cy="{mid}" r="4" fill="{INK}"/>'
               f'<text x="{x(now):.0f}" y="{mid-8}" fill="{INK}" font-size="8.5" '
               f'text-anchor="middle">AHORA</text>')
    ticks = (tick(stop8, "STOP 8%", RED, True) + tick(estruct, "ESTRUCT", RED, False)
             + tick(entry, "ENTRADA", AMB, True) + tick(tp, "TP +40%", GRN, True))
    return (f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:{H}px;display:block">'
            f'<line x1="8" y1="{mid}" x2="{W-8}" y2="{mid}" stroke="{BORDER}" stroke-width="1"/>'
            f'{seg}{ticks}{now_dot}</svg>')


def _badge(txt, color, strong=False):
    bgc = f"{color}22" if not strong else color
    fg = color if not strong else "#0a0e14"
    return (f'<span style="background:{bgc};color:{fg};border:1px solid {color}55;'
            f'border-radius:4px;padding:2px 8px;font-size:10.5px;font-weight:600;'
            f'letter-spacing:.6px;margin-right:6px;white-space:nowrap">{txt}</span>')


def _ctx_badges(h, base):
    """Badges de contexto comunes a ENTRABLE y A VIGILAR."""
    d = h["delta"]
    b = [(_badge("COMPRA AGRESIVA", GRN) if d > 0.03 else
          _badge("CHISPA HUECA", RED) if d < -0.01 else _badge("CHISPA MIXTA", MUT))]
    if h.get("edad") is not None:
        e = h["edad"]
        b.append(_badge(f"EDAD {e}D" + (" — RECIEN LISTADO" if e < 90 else " ✓" if e < 365 else ""),
                        RED if e < 90 else GRN if e < 365 else MUT))
    venues = [("BYB", h.get("bvx")), ("GATE", h.get("gvx")), ("MEXC", h.get("mvx"))]
    con_dato = [(n, v) for n, v in venues if v]
    if con_dato:
        amplios = sum(1 for _, v in con_dato if v >= 6)
        txt = " · ".join(f"{n} {v:.0f}X" for n, v in con_dato)
        b.append(_badge(f"AMPLITUD {txt}" + (" ✓" if amplios >= 2 else ""),
                        GRN if amplios >= 2 else MUT))
    if h.get("print_ratio"):
        pr = h["print_ratio"]
        b.append(_badge("PRINTS PEQUEÑOS ✓" if pr < 1.2 else "⚠ PRINTS GRANDES" if pr > 2
                        else f"PRINTS {pr:.1f}X", GRN if pr < 1.2 else RED if pr > 2 else MUT))
    cat = _CATS.get(base.lower())
    if cat:
        b.append(_badge(f"NARRATIVA: {cat}", GRN if cat == "MEME" else MUT))
    return b


def _ministat(label, value, color=INK):
    return (f'<div style="text-align:right;margin-left:18px"><div style="font-size:9px;'
            f'color:{MUT};letter-spacing:1.2px">{label}</div><div class="mono" '
            f'style="font-size:13px;color:{color}">{value}</div></div>')


def _links(sym, base, news=True):
    s, b = _q(sym), _q(base)
    ls = [("GRAFICO", f"https://es.tradingview.com/chart/?symbol=BINANCE%3A{s}.P"),
          ("X LIVE", f"https://x.com/search?q=%24{b}&f=live"),
          ("NEWS", f"https://news.google.com/search?q={b}%20crypto"),
          ("DEXSCREENER", f"https://dexscreener.com/search?q={b}"),
          ("COINGECKO", f"https://www.coingecko.com/es/search?query={b}")]
    if not news:
        ls = [l for l in ls if l[0] != "NEWS"]
    return "".join(f'<a class="btn" href="{u}" target="_blank">{t}</a>' for t, u in ls)


def _base(sym):
    b = sym.replace("USDT", "")
    for pre in ("1000000", "1000"):
        if b.startswith(pre):
            b = b[len(pre):]
    return b


def write_html(hits, stamp, cuenta, riesgo, historial=None):
    frescas = [h for h in hits if h["tipo"].startswith("ENTRADA") and h["hace_h"] <= 2]
    viejas = [h for h in hits if h["tipo"].startswith("ENTRADA") and h["hace_h"] > 2]
    radar = [h for h in hits if h["tipo"] == "PRE-AVISO"]
    actuales = {h["symbol"] for h in hits}
    historial = [x for x in (historial or []) if x["symbol"] not in actuales]

    def card(h, fresca):
        salta = "SOLITARIA" in h["tipo"] or h.get("liq_d", 0) > 100e6
        base = _base(h["symbol"])
        d = h["delta"]
        b = _ctx_badges(h, base)
        if "SOLITARIA" in h["tipo"]:
            b.append(_badge("SOLITARIA — EL SISTEMA LA SALTA", RED, strong=True))
        if h.get("liq_d", 0) > 100e6:
            b.append(_badge("GIGANTE >100M$/D — EL SISTEMA LA SALTA", RED, strong=True))
        entry = h["px_deteccion"]
        stop8, tp = entry * 0.92, entry * 1.40
        risk_e = (h["px_actual"] - h["stop_estruct"]) / h["px_actual"]
        est_ok = 0.06 <= risk_e <= 0.12
        pos8 = cuenta * riesgo / 0.08
        pose = cuenta * riesgo / max(risk_e, 1e-9)
        estado, ecol = (("LARGO · ENTRABLE", GRN) if fresca and not salta else
                        ("LARGO · SALTAR", RED) if salta else ("LARGO · YA CORRIDA", MUT))
        news_html = ""
        if h.get("news"):
            items = "".join(f'<div class="nw">▸ <a href="{l}" target="_blank">{t[:100]}</a> '
                            f'<span style="color:{MUT}">{dd}</span></div>' for t, l, dd in h["news"])
            news_html = f'<div class="newsbox"><div class="nlbl">ULTIMAS NOTICIAS</div>{items}</div>'
        stats = (_ministat("HACE", f"{h['hace_h']}h")
                 + _ministat("CHISPA 6H", f"+{h['chispa']:.0%}", GRN)
                 + _ministat("VOLUMEN", f"{h['volx']:.0f}x")
                 + _ministat("DELTA", f"{d:+.2f}", GRN if d > 0.03 else RED if d < -0.01 else INK)
                 + _ministat("CORRIDO", f"{h['corrido']:+.1%}",
                             RED if h["corrido"] > 0.10 else INK)
                 + _ministat("LIQ", f"{h.get('liq_d',0)/1e6:.0f}M$/d"))
        return f"""
<div class="card{' skip' if salta else ''}" data-fresh="{1 if (fresca and not salta) else 0}"
     data-sym="{h['symbol']}" style="border-left:3px solid {ecol}">
 <div class="row1">
  <div><span class="sym">{h['symbol']}</span>
   <span class="pill" style="color:{ecol};border-color:{ecol}">{estado}</span></div>
  <div class="stats">{stats}</div>
 </div>
 {_area_svg(h.get('spark'), entry, 'ENTRADA')}
 {_levels_svg(stop8, h['stop_estruct'], entry, tp, h['px_actual'])}
 <div class="badges">{''.join(b)}</div>
 <div class="grid5">
  <div><s1>ENTRADA LIMITE</s1><s2 style="color:{AMB}">{_fmt(entry)}</s2><s3>post-only · valida 6h</s3></div>
  <div><s1>STOP 8%</s1><s2>{_fmt(stop8)}</s2><s3>posicion {pos8:.0f}$</s3></div>
  <div><s1>STOP ESTRUCTURAL {'✓ USABLE' if est_ok else '✗ FUERA 6-12%'}</s1><s2>{_fmt(h['stop_estruct'])}</s2><s3>{risk_e:.0%} · pos {pose:.0f}$</s3></div>
  <div><s1>TAKE PROFIT</s1><s2 style="color:{GRN}">{_fmt(tp)}</s2><s3>+40%</s3></div>
  <div><s1>SALIDA TIEMPO</s1><s2>7 dias</s2><s3>no se toca antes</s3></div>
 </div>
 <div class="links">{_links(h['symbol'], base)}</div>
 {news_html}
</div>"""

    def rcard(h):
        base = _base(h["symbol"])
        d = h["delta"]
        trig = h.get("trigger_px", h["px_deteccion"] * 1.03)
        falta = trig / h["px_actual"] - 1
        rb = _ctx_badges(h, base)
        if h.get("liq_d", 0) > 100e6:
            rb.append(_badge("GIGANTE >100M$/D — NO SERIA OPERABLE", RED, strong=True))
        qual = "".join(rb)
        stats = (_ministat("HACE", f"{h['hace_h']}h")
                 + _ministat("MOVIMIENTO 4H", f"+{h['chispa']:.0%}", AMB)
                 + _ministat("VOLUMEN", f"{h['volx']:.0f}x")
                 + _ministat("DELTA", f"{d:+.2f}"))
        return f"""
<div class="card radar" data-fresh="0">
 <div class="row1">
  <div><span class="sym" style="color:{AMB}">{h['symbol']}</span>
   <span class="pill" style="color:{AMB};border-color:{AMB}">LARGO · A VIGILAR</span></div>
  <div class="stats">{stats}</div>
 </div>
 {_area_svg(h.get('spark'), trig, 'CONFIRMA')}
 <div class="badges">{qual}</div>
 <div class="grid5">
  <div><s1>PRECIO AHORA</s1><s2>{_fmt(h['px_actual'])}</s2><s3>&nbsp;</s3></div>
  <div><s1>CONFIRMARIA EN</s1><s2 style="color:{AMB}">{_fmt(trig)}</s2><s3>{falta:+.1%} desde aqui</s3></div>
  <div style="grid-column:span 3"><s1>PLAN</s1><s2 style="font-size:12.5px;font-family:Inter">usa esta ventana: grafico + X + dex. Si confirma, aparecera arriba como ENTRABLE</s2><s3>&nbsp;</s3></div>
 </div>
 <div class="links">{_links(h['symbol'], base, news=False)}</div>
</div>"""

    # radar de figuras que mueven mercado (titulares, gratis; X API es de pago)
    figuras_html = ""
    try:
        vistos_t = set()
        items = []
        for q in ("Trump crypto bitcoin", "Elon Musk crypto"):
            for t, l, dd in fetch_news(q.replace(" crypto bitcoin", "").replace(" crypto", "")) or []:
                if t[:60] not in vistos_t:
                    vistos_t.add(t[:60])
                    items.append((t, l, dd))
        if items:
            figuras_html = "".join(
                f'<div class="nw">▸ <a href="{l}" target="_blank">{t[:92]}</a> '
                f'<span style="color:{MUT}">{dd}</span></div>' for t, l, dd in items[:6])
    except Exception:
        pass

    main = []
    if frescas:
        main.append(f'<div class="sec" style="color:{GRN}">ENTRABLES <b>{len(frescas)}</b></div>'
                    + "".join(card(h, True) for h in frescas))
    else:
        main.append(f'<div class="sec" style="color:{MUT}">SIN ENTRABLES AHORA'
                    f'<span class="secnote">media ~1/dia en el universo — el vacio es normal</span></div>')
    if radar:
        main.append(f'<div class="sec" style="color:{AMB}">A VIGILAR — RADAR +7%/4H <b>{len(radar)}</b>'
                    f'<span class="secnote">tu ventana de preparacion antes de que confirme</span></div>'
                    + "".join(rcard(h) for h in radar))
    if viejas:
        main.append(f'<div class="sec" style="color:{MUT}">YA CORRIDAS <b>{len(viejas)}</b>'
                    f'<span class="secnote">contexto — el sistema entra a T+0, no tarde</span></div>'
                    + "".join(card(h, False) for h in viejas))
    if historial:
        rows = []
        for x in historial:
            chg = x.get("chg")
            if chg is None:
                est, ecol, chgtxt = "—", MUT, "s/d"
            elif chg >= 0.40:
                est, ecol, chgtxt = "≈TP ✓", GRN, f"{chg:+.0%}"
            elif chg <= -0.08:
                est, ecol, chgtxt = "≈STOP", RED, f"{chg:+.0%}"
            else:
                est, ecol, chgtxt = "abierta", INK, f"{chg:+.1%}"
            saltada = "SOLITARIA" in x.get("tipo", "") or "GIGANTE" in x.get("tipo", "")
            d = x.get("delta", 0)
            dcol = GRN if d > 0.03 else RED if d < -0.01 else MUT
            edad = x.get("edad")
            etxt = f"{edad}d" if edad is not None else "—"
            ecol2 = RED if (edad is not None and edad < 90) else \
                GRN if (edad is not None and edad < 365) else MUT
            pr = x.get("print_ratio", 0)
            flags = []
            if saltada:
                flags.append("saltada")
            if pr and pr > 2:
                flags.append("actor unico")
            base_h = _base(x["symbol"])
            hb = _ctx_badges(x, base_h)
            if saltada:
                hb.append(_badge("EL SISTEMA LA SALTO", RED, strong=True))
            entry_h, stop8_h, tp_h = x["px"], x["px"] * 0.92, x["px"] * 1.40
            pos8_h = cuenta * riesgo / 0.08
            t0ms = int(x["hora"].timestamp() * 1000)
            rows.append(
                f'<div class="hrow"{" style=opacity:.45" if saltada else ""} onclick="tog(this)">'
                f'<span class="mono hsym">▸ {x["symbol"]}</span>'
                f'<span class="hdt">{x["hora"].strftime("%d-%m %H:%M")}</span>'
                f'<span class="mono">{_fmt(x["px"])}</span>'
                f'<span class="mono" style="color:{ecol}">{chgtxt}</span>'
                f'<span style="color:{ecol};font-size:10px;letter-spacing:1px">{est}</span>'
                f'<span class="mono" style="color:{dcol};font-size:11px">{d:+.2f}</span>'
                f'<span class="mono" style="color:{ecol2};font-size:11px">{etxt}</span>'
                f'<span class="mono" style="color:{MUT};font-size:11px">{x.get("liq_d",0)/1e6:.0f}M</span>'
                f'<span style="color:{RED if flags else MUT};font-size:9.5px">{", ".join(flags)}</span>'
                f'<a class="btn" style="padding:1px 8px" onclick="event.stopPropagation()" '
                f'href="https://es.tradingview.com/chart/?symbol=BINANCE%3A{_q(x["symbol"])}.P" '
                f'target="_blank">GRAF</a></div>'
                f'<div class="hdet" hidden data-sym="{x["symbol"]}" data-t0="{t0ms}" '
                f'data-entry="{entry_h}">'
                f'<div class="hchart">cargando grafica…</div>'
                f'<div class="badges">{"".join(hb)}</div>'
                f'<div class="grid5">'
                f'<div><s1>ENTRADA (fue)</s1><s2 style="color:{AMB}">{_fmt(entry_h)}</s2><s3>limite en deteccion</s3></div>'
                f'<div><s1>STOP 8%</s1><s2>{_fmt(stop8_h)}</s2><s3>pos {pos8_h:.0f}$</s3></div>'
                f'<div><s1>TP +40%</s1><s2 style="color:{GRN}">{_fmt(tp_h)}</s2><s3>&nbsp;</s3></div>'
                f'<div style="grid-column:span 2"><s1>OJO</s1>'
                f'<s2 style="font-size:11.5px;font-family:Inter;color:{MUT}">entrar tarde queda FUERA '
                f'del sistema (el backtest entra a T+0). Vigilar ≠ perseguir.</s2><s3>&nbsp;</s3></div>'
                f'</div><div class="links">{_links(x["symbol"], base_h)}</div></div>')
        main.append(
            f'<div class="sec" style="color:{BLU}">HISTORIAL 7 DIAS <b>{len(historial)}</b>'
            f'<span class="secnote">estado aprox por precio actual — veredicto exacto: revision.py</span></div>'
            f'<div class="card" style="padding:8px 18px">'
            f'<div class="hrow hhead"><span>PAR</span><span>SEÑAL</span><span>ENTRADA</span>'
            f'<span>AHORA</span><span>ESTADO</span><span>Δ</span><span>EDAD</span>'
            f'<span>LIQ</span><span>AVISOS</span><span></span></div>'
            + "".join(rows) + "</div>")

    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="90"><title>IGNITION TERMINAL</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{background:{BG};color:{INK};font-family:Inter,system-ui,sans-serif;margin:0;
 font-variant-numeric:tabular-nums}}
.mono,s2{{font-family:'JetBrains Mono',Consolas,monospace}}
a{{color:{BLU};text-decoration:none}}
.top{{position:sticky;top:0;background:{BG}ee;backdrop-filter:blur(6px);z-index:5;
 border-bottom:1px solid {BORDER};padding:12px 26px;display:flex;justify-content:space-between;align-items:center}}
.brand{{font-weight:800;font-size:15px;letter-spacing:3px;color:{AMB}}}
.topstats{{display:flex;gap:22px;align-items:baseline}}
.ts div{{font-size:9px;color:{MUT};letter-spacing:1.2px}}
.ts span{{font-size:14px;font-weight:600}}
.wrap{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px;padding:18px 26px;
 max-width:1340px;margin:auto}}
.card{{background:{SURF};border:1px solid {BORDER};border-radius:8px;padding:14px 18px 12px;
 margin-bottom:14px;transition:border-color .15s}}
.card:hover{{border-color:#31405a}}
.card.skip{{opacity:.45}}
.card.radar{{background:#12110c}}
.row1{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}}
.sym{{font-size:21px;font-weight:800;letter-spacing:.5px}}
.pill{{font-size:10px;font-weight:800;letter-spacing:1.5px;border:1px solid;border-radius:20px;
 padding:3px 10px;margin-left:10px;vertical-align:3px}}
.stats{{display:flex}}
.badges{{margin:9px 0 4px}}
.grid5{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:8px;
 border-top:1px solid {BORDER};padding-top:9px}}
s1{{display:block;font-size:8.5px;color:{MUT};letter-spacing:1.3px;margin-bottom:2px}}
s2{{display:block;font-size:15px;font-weight:700}}
s3{{display:block;font-size:10px;color:{MUT};margin-top:1px}}
.links{{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}}
.btn{{border:1px solid {BORDER};border-radius:5px;padding:4px 11px;font-size:10px;
 letter-spacing:1px;font-weight:600;transition:all .12s}}
.btn:hover{{border-color:{BLU};background:{BLU}18}}
.newsbox{{margin-top:10px;background:{BG};border-radius:6px;padding:8px 12px}}
.nlbl{{font-size:8.5px;color:{MUT};letter-spacing:1.3px;margin-bottom:4px}}
.nw{{font-size:11.5px;padding:1.5px 0}} .nw a{{color:#9ecbff}}
.hrow{{display:grid;grid-template-columns:150px 100px 104px 82px 76px 62px 60px 58px 96px 1fr;
 align-items:center;padding:9px 0;border-bottom:1px dashed {BORDER};font-size:14px}}
.hrow:last-child{{border-bottom:none}}
.hrow{{cursor:pointer}} .hrow:hover{{background:#151b25}} .hrow:hover .hsym{{color:{BLU}}}
.hsym{{font-size:15px}}
.hhead{{cursor:default;font-size:9.5px}}
.hhead:hover{{background:none}}
.hdet{{background:{BG};border:1px solid {BORDER};border-radius:6px;padding:10px 14px;margin:4px 0 10px}}
.hchart{{color:{MUT};font-size:11px;min-height:20px}}
.hhead{{font-size:8.5px;color:{MUT};letter-spacing:1.3px}}
.hsym{{font-weight:700}}
.hdt{{color:{MUT};font-size:11px}}
.sec{{font-size:11.5px;font-weight:800;letter-spacing:2.5px;margin:10px 0 12px}}
.sec b{{background:{BORDER};border-radius:10px;padding:1px 8px;margin-left:6px}}
.secnote{{font-weight:400;letter-spacing:.3px;color:{MUT};margin-left:12px;font-size:11px;text-transform:none}}
.panel{{background:{SURF};border:1px solid {BORDER};border-radius:8px;padding:14px 16px;margin-bottom:16px}}
.panel h3{{margin:0 0 10px;font-size:10px;color:{AMB};letter-spacing:2.5px}}
.panel .r{{font-size:12px;padding:3.5px 0;color:{INK};line-height:1.45}}
.panel .r b{{color:{AMB};font-weight:600}}
.step{{display:flex;gap:10px;padding:5px 0;font-size:12px;line-height:1.5;color:{INK}}}
.step b{{color:{INK};font-weight:700}}
.num{{flex:0 0 20px;height:20px;border-radius:50%;color:#0a0e14;font-weight:800;
 font-size:11px;display:flex;align-items:center;justify-content:center;margin-top:2px}}
.hero{{display:flex;gap:18px;margin-bottom:6px}}
.hero div{{flex:1}} .hero .hv{{font-size:22px;font-weight:800}} .hero .hl{{font-size:9px;color:{MUT};letter-spacing:1px}}
#notif{{cursor:pointer;border:1px solid {BORDER};background:none;color:{MUT};border-radius:5px;
 padding:4px 10px;font-size:10px;font-family:Inter;letter-spacing:1px}}
</style></head><body>
<div class="top">
 <span class="brand">⚡ IGNITION TERMINAL</span>
 <div class="topstats">
  <div class="ts"><div>ENTRABLES</div><span style="color:{GRN}">{len(frescas)}</span></div>
  <div class="ts"><div>RADAR</div><span style="color:{AMB}">{len(radar)}</span></div>
  <div class="ts"><div>CORRIDAS</div><span style="color:{MUT}">{len(viejas)}</span></div>
  <div class="ts"><div>CUENTA · RIESGO</div><span>{cuenta:.0f}$ · {riesgo:.0%}</span></div>
  <div class="ts"><div>ACTUALIZADO</div><span>{stamp}</span></div>
  <div class="ts"><div>PROX. ESCANEO</div><span id="cd" style="color:{AMB}">—</span></div>
  <button id="notif" onclick="askNotif()">🔔 AVISOS</button>
 </div>
</div>
<div class="wrap">
<div>{''.join(main)}</div>
<div>
 <div class="panel"><h3>COMO FUNCIONA — SIN JERGA</h3>
  <div class="r" style="color:{MUT};font-size:11.5px;margin-bottom:8px">
   Si, solo salta cuando la moneda YA esta subiendo. Es a proposito: probamos 50+
   formas de predecir ANTES de la subida y ninguna funciono — la unica apuesta que
   gana es comprar el arranque confirmado y montar la continuacion.</div>
  <div class="step"><span class="num" style="background:{GRN}">1</span><div>
   <b>DETECTA</b> una moneda que sube <b>+10% en 6 horas</b> con <b>4× su volumen
   normal</b>, tras 5 dias tranquila. Eso es "acaba de encenderse" — no un meneo.</div></div>
  <div class="step"><span class="num" style="background:{RED}">2</span><div>
   <b>DESCARTA</b> dos tipos que fallan casi siempre: la que sube <b>sola</b> (sin
   ninguna otra ignicion ese dia = probable manipulacion) y la <b>gigante</b>
   (&gt;100M$/dia: demasiado pesada para volar +40%).</div></div>
  <div class="step"><span class="num" style="background:{AMB}">3</span><div>
   <b>ENTRA</b> con orden <b>limite</b> al precio de la deteccion (no persigas con
   market: el precio casi siempre respira de vuelta y el limite se llena solo,
   ahorrando comision).</div></div>
  <div class="step"><span class="num" style="background:{RED}">4</span><div>
   <b>PROTEGE</b> con stop a <b>−8%</b> (o bajo el minimo del arranque si la tarjeta
   marca ✓). Mas cerca no: el ruido normal de estas monedas te sacaria siempre.
   Posicion = (cuenta × riesgo) ÷ distancia del stop → la tarjeta ya lo calcula.</div></div>
  <div class="step"><span class="num" style="background:{GRN}">5</span><div>
   <b>COBRA</b> en <b>+40%</b>, o vende a los <b>7 dias</b>, lo que llegue antes.
   Entre medias <b>no se toca nada</b>: probamos 6 formas de "gestionar" (trailing,
   breakeven, parciales...) y TODAS perdieron dinero contra no hacer nada.</div></div>
  <div class="r" style="border-top:1px solid {BORDER};margin-top:9px;padding-top:9px">
   <b>Por que gana perdiendo 7 de cada 10:</b> cada acierto paga <b>5€ por cada 1€</b>
   arriesgado. Tres aciertos cubren siete fallos... y sobra. El sistema no intenta
   acertar mucho — intenta que los aciertos sean enormes y los fallos, pequeños.</div>
  <div class="r" style="color:{MUT};font-size:11px">
   Maximo 3-4 posiciones a la vez. Si hay varias señales, prioriza la de mayor delta
   (Δ) — la que tiene compra agresiva de verdad detras.</div>
 </div>
 <div class="panel"><h3>QUE ESPERAR (BACKTEST 3 AÑOS)</h3>
  <div class="hero">
   <div><div class="hv" style="color:{GRN}">31%</div><div class="hl">ALCANZAN +25%</div></div>
   <div><div class="hv">+1.5%</div><div class="hl">POR TRADE</div></div>
   <div><div class="hv" style="color:{RED}">−15%</div><div class="hl">RETROCESO MEDIO</div></div>
  </div>
  <div class="r">La mediana pierde: pagan los ganadores de cola. Rachas de 8-12 rojas son rutina, no error.</div>
  <div class="r" style="color:{MUT}">correccion de senales: <span class="mono">python revision.py</span></div>
 </div>
 <div class="panel"><h3>FIGURAS DEL MERCADO — TITULARES</h3>
  {figuras_html or f'<div class="r" style="color:{MUT}">sin titulares ahora</div>'}
  <div class="r" style="color:{MUT};font-size:10.5px;border-top:1px solid {BORDER};
   margin-top:7px;padding-top:7px">Trump/Musk via Google News (minutos de retraso vs
   el tweet; la API de X es de pago). OJO: estas figuras mueven BTC/DOGE/majors —
   los gigantes que el sistema salta. Es contexto de clima, no señal.
   <a href="https://x.com/search?q=crypto%20(from%3Aelonmusk%20OR%20from%3ArealDonaldTrump)&f=live"
   target="_blank" style="font-size:10px">VER EN X →</a></div>
 </div>
 <div class="panel"><h3>DICCIONARIO DE BADGES</h3>
  <div class="r"><b style="color:{GRN}">COMPRA AGRESIVA</b> la subida lleva compra a mercado
   de verdad detras (delta &gt; +0.03). Historicamente retiene mejor la ganancia.</div>
  <div class="r"><b style="color:{RED}">CHISPA HUECA</b> el precio sube pero los que cruzan
   el mercado VENDEN (delta negativo): subida sin dinero empujando — squeeze o
   iliquidez. Se desinfla mas a menudo.</div>
  <div class="r"><b style="color:{MUT}">CHISPA MIXTA</b> delta entre −0.01 y +0.03: ni compra
   clara ni venta clara. Neutral — decide con el resto de badges.</div>
  <div class="r"><b style="color:{RED}">⚠ PRINTS GRANDES</b> las ordenes que empujan son
   anormalmente grandes (&gt;2× lo normal del par). NO prueba que sea una sola mano
   (pueden ser varias ballenas o un MM) — lo medido es que estas igniciones
   FRACASAN mas, sea quien sea. Los grandes que ganan trocean sus ordenes.</div>
  <div class="r"><b style="color:{GRN}">PRINTS PEQUEÑOS ✓</b> enjambre de ordenes pequeñas:
   el perfil con el que arrancan las ganadoras — multitud real o un grande bien
   camuflado; para operar da igual, el patron es el que paga.</div>
  <div class="r"><b style="color:{MUT}">PRINTS 1.2-2X</b> zona gris, ni chicas ni sospechosas.</div>
  <div class="r"><b style="color:{AMB}">EDAD</b> &lt;90d = trampa (los del airdrop venden
   contra todo pump) · 90-365d ✓ = punto dulce medido · &gt;1 año = pesada.</div>
  <div class="r"><b style="color:{GRN}">AMPLITUD ✓</b> expansion del volumen en Bybit, Gate
   y MEXC a la vez que en Binance. ✓ = amplia en ≥2 exchanges (≥6× su normal):
   estampida global. Sin ✓ = el pump vive en un solo exchange — mas sospechoso
   de movimiento local/manipulado.</div>
  <div class="r"><b style="color:{MUT}">NARRATIVA</b> categoria del token (CoinGecko):
   <b>MEME</b> la que mas gana (27-28%) · <b>AI / GAMING</b> medias · <b>INFRA</b>
   (cadenas/infraestructura) irregular · <b>DEFI</b> la peor en 2023-25. Solo
   contexto: no cambia las reglas.</div>
  <div class="r"><b style="color:{AMB}">STOP ESTRUCT ✓/✗</b> en la tarjeta: ✓ = el minimo
   del arranque cae entre 6-12% y puedes usarlo como stop con logica de mercado;
   ✗ = cae fuera de ese rango → usa el 8% fijo.</div>
  <div class="r"><b style="color:{RED}">SOLITARIA / GIGANTE</b> filtros duros del sistema:
   sin otra ignicion en 24h = probable manipulacion; &gt;100M$/dia = demasiado
   pesada para +40%. Se saltan siempre.</div>
  <div class="r" style="border-top:1px solid {BORDER};margin-top:8px;padding-top:8px;color:{MUT}">
   Regla de oro: un badge rojo es aviso; DOS O MAS rojos apuntando al mismo sitio,
   dejala pasar aunque cumpla las reglas.</div>
 </div>
</div></div>
<script>
function tog(row){{const d=row.nextElementSibling;if(!d||!d.classList.contains('hdet'))return;
d.hidden=!d.hidden;
if(!d.hidden&&!d.dataset.loaded){{d.dataset.loaded=1;cargarChart(d);}}}}
async function cargarChart(d){{const box=d.querySelector('.hchart');try{{
const r=await fetch('https://fapi.binance.com/fapi/v1/klines?symbol='+d.dataset.sym+
 '&interval=1h&startTime='+(+d.dataset.t0-36e5*12)+'&limit=200');
const k=await r.json();const cs=k.map(x=>+x[4]);const entry=+d.dataset.entry;
let lo=Math.min(...cs,entry),hi=Math.max(...cs,entry);const rg=(hi-lo)||1e-12;
const W=560,H=80,PR=64;const xs=i=>i*(W-PR)/(cs.length-1);const ys=c=>H-8-(c-lo)/rg*(H-20);
const pts=cs.map((c,i)=>xs(i).toFixed(1)+','+ys(c).toFixed(1)).join(' ');
const col=cs[cs.length-1]>=cs[0]?'{GRN}':'{RED}';const ye=ys(entry);
box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:'+H+'px">'+
 '<polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="2"/>'+
 '<line x1="0" y1="'+ye.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+ye.toFixed(1)+
 '" stroke="{AMB}" stroke-width="1" stroke-dasharray="4,4"/>'+
 '<text x="'+(W-PR+6)+'" y="'+(ye+3).toFixed(1)+'" fill="{AMB}" font-size="10" '+
 'font-family="JetBrains Mono,monospace">ENTRADA '+entry+'</text></svg>';
}}catch(e){{box.textContent='grafica no disponible (sin conexion a Binance desde el navegador)';}}}}
function cdt(){{const n=new Date();const m=15-(n.getMinutes()%15);
document.getElementById('cd').textContent=(m-1)+':'+String(59-n.getSeconds()).padStart(2,'0');}}
setInterval(cdt,1000);cdt();
function askNotif(){{Notification.requestPermission().then(p=>{{
document.getElementById('notif').textContent=p==='granted'?'🔔 AVISOS ON':'🔕 BLOQUEADOS';}});}}
(function(){{if(!('Notification' in window))return;
if(Notification.permission==='granted'){{document.getElementById('notif').textContent='🔔 AVISOS ON';
const seen=JSON.parse(localStorage.getItem('seen')||'[]');
document.querySelectorAll('[data-fresh="1"]').forEach(c=>{{const s=c.dataset.sym;
if(!seen.includes(s)){{new Notification('⚡ IGNICION ENTRABLE: '+s,
{{body:'Abre el terminal: entrada limite, stop y tamaño en la tarjeta.'}});seen.push(s);}}}});
localStorage.setItem('seen',JSON.stringify(seen.slice(-80)));}}}})();
</script></body></html>"""
    with open("senales.html", "w", encoding="utf-8") as f:
        f.write(html)
