# Hipótesis pendientes — SOLO testear con datos nuevos (no re-minar los 1.011 eventos)

**Protocolo**: cada hipótesis se escribe ANTES de mirar datos, se testea sobre eventos
posteriores a 2026-09-04 (o fuentes nuevas), y asciende solo si mejora el trade real
en la muestra virgen. Los 1.011 eventos históricos están agotados.

## Candidatas ya medidas que esperan validación en virgen
- [ ] Amplitud Bybit (volumen expandiéndose multi-exchange) — mejoró +0.4/+0.4 en histórico
- [ ] Share de bots profesionales en DEX pre-ignición (Dune) — sobrevivió 4 tests, mecanismo entendido
- [ ] Edad del par 90-365d como preferencia — solapa con liquidez, no limpio
- [ ] Desempate por delta en días multi-señal — +1.4% en solo 25 días de muestra
- [ ] Firma multitud (print medio bajo) — se debilitó al controlar liquidez (p=0.016)

## Upgrade ML (madura con la muestra viva)
- [ ] Score calibrado por señal (gradient boosting, 15 features) en el panel:
      re-entrenar cuando haya ~200-300 eventos POSTERIORES a 2026-09-04 y validar
      walk-forward en el tramo siguiente. Techo confirmado con A→B:
      logística 0.620 / GBM 0.642 / RF 0.655 AUC; tercil top ~30% — el límite es
      información, no modelo. No re-entrenar sobre los 1.011 históricos.

## Ideas nuevas en cola (sin testear nunca)
- [ ] Calor sectorial: igniciones en la misma narrativa/categoría (labels CoinGecko) vs calor global
- [ ] Gestión por imbalance de prints grandes EN VIVO (websocket) durante posición abierta
- [ ] Pata Solana del estudio on-chain (WIF/BONK/PENGU nativos)
- [ ] Estacionalidad horaria/semanal de igniciones (baja prioridad, alto riesgo de ruido)
- [ ] Universo extra: backtest de ignición en pares exclusivos de Gate/MEXC (datos vírgenes reales)

## En espera POR ESCALA (validada en ambos regímenes; no operable con cuenta chica)
- [ ] CASH-AND-CARRY delta-neutral (carry_neutral.py, 2026-09-09): largo spot +
      corto perp misma moneda, top-10 por funding trailing 7d. +7.3%/+12.2% anual
      por periodo, maxDD -1.3%/-0.2%, Sharpe 7/17. Es "el trade de los fondos":
      cobrar el funding de los apalancados, sin dirección. Sobre capital total
      real: ~4-6%/año a 1x (dos patas). Con 1k no compensa el esfuerzo; con 10k+
      o apalancado 2-3x (gestión de margen seria) es la manga de renta fija.

## Requieren dinero o infraestructura (decidir tras validación en papel)
- [ ] Datos sociales (LunarCrush/X): la capa del catalizador — única ortogonal restante
- [ ] Labels on-chain actualizadas (Arkham/Nansen): netflow de verdad
- [ ] Grabadora 24/7 (OI horario, liquidaciones, libro) — cada día sin grabar es dataset perdido

## Muertas — NO reabrir (62 tests, 2026-09-03/16)
- FADE de igniciones malas (fade_malas.py, 2026-09-16): cortar las que el largo
  descarta (solitarias/gigantes). Todo ~0 o negativo con signos inestables
  (solitarias +0.36/-0.66). Las malas no se desploman: se desinflan de lado, y
  su fwd_max medio (+9-12%) ejecuta el stop. 9º y ultimo juicio al corto de
  evento: NINGUN corto sobrevive cerca de una ignicion. Familia cerrada.
- ROUND-TRIP post-pico (peak_reversal.py): rotura de estructura tras +40% -> corto.
  685 eventos: -1.9% a -4.1%/trade, negativo ambos periodos. La deriva MEDIA tras
  la "rotura confirmada" es +3.2%/3d (los re-encendidos pagan todo; la mediana
  -1.6% es la que ve el ojo). Séptimo juicio al corto de evento.
- Cortos ESTRUCTURALES cesta bruta (bleed_test.py): -17%/-49% por periodo,
  maxDD -51%. La mediana baja pero la cesta corta come la MEDIA, y la media
  incluye las explosiones que el sistema largo caza.
- Predicción desde silencio (L_B †OOS) · footprint previo · delta como filtro ·
  cortos de evento ×3 (sweep máximos, ignición bajista, divergencia distribución) ·
  salidas gestionadas ×6 (breakeven, trailing ×2, parcial, corte 48h, flujo 24h) ·
  stops <8% · apalancamiento >2x · pullback entry · límite -1/-2% · TWAP tamaños ·
  TWAP cadencia · squeeze funding · basis · BTC régimen · posición en rango ·
  limpieza · anuncios Binance · compradores DEX · netflow labels gratis ·
  smart money direccional (=bots 1.00x) · OI/liq previos (Coinalyze) ·
  consenso 8 fórmulas · TP≠40 · 14 días · RR>1:5 estructural · calor sectorial 7d ·
  rebote hueco como filtro (falló su pre-registro)

## El examen que manda
- 2026-09-10: primera revisión del lote de papel (`python revision.py --dias 7`)
- 40-50 trades de papel → decisión de dinero real al 2%
- Columna "mi ojo" vs "máquina" en cada señal → medir si la capa discrecional suma
