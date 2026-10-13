# Ignition Terminal

Plataforma de investigación y señales para **perpetuos USDT de criptomonedas** (Binance, con
contraste en Bybit). Escanea todo el universo de pares, detecta eventos de momentum
("igniciones") y patrones de agotamiento, y los opera en papel en una cartera **multiactivo,
largos y cortos a la vez**, con reglas de una cuenta de prop firm.

Lo central no es una estrategia ganadora, sino **el método de investigación**: 62 hipótesis
pre-registradas, juzgadas fuera de muestra y descartadas con su resultado documentado, y un
seguimiento en vivo que compara cada señal real con lo que prometía el backtest.

Esta es la versión pública. Las dos estrategias que siguen en validación (una cartera corta
market-neutral y un patrón de corto de evento) están en un repositorio privado: aquí se ven sus
resultados, no sus reglas.

> Proyecto personal de investigación. Nada de esto es consejo de inversión.

## Qué hace

| Pieza | Qué hace |
|---|---|
| **Escáner en vivo** (`ignition_scan.py`) | Recorre todos los perpetuos USDT de Binance y detecta igniciones: +10 % en 6 h, volumen 6 h ≥ 4× su mediana de 30 días, precio plano los 5 días previos y ninguna ignición en las 72 h anteriores. Calcula stop, TP y tamaño de posición por riesgo. |
| **Libro** (`libro.py`) | Simulación continua de un challenge de prop firm (100k, riesgo 1 % por operación, máx. 4 posiciones simultáneas entre largos y cortos, objetivo +10 %, límite total −10 %, diario −5 %). Tres libros en paralelo: combinado, solo largos y solo cortos. |
| **Terminal** (`dashboard.py`) | Panel HTML con radar de señales, tarjetas por par (niveles, badges de contexto, gráfica) e historial con el resultado real de cada señal. |
| **Corrector** (`revision.py`) | Revisa cada señal registrada (TP / stop / tiempo / en curso) y la compara con la tasa del backtest. |
| **Grabadoras** (`recorder_*.py`, `watchdog_liq.py`) | Stream de liquidaciones por websocket con reconexión y watchdog; foto horaria de funding, libro, open interest y ratios de ~500 perpetuos. |

## Datos

Todo a partir de APIs públicas o gratuitas, cacheado en local para no repetir descargas:

- **Velas 1h y 15m** de ~95 perpetuos durante ~3 años, con delta agresor (taker buy/sell) de perpetuo y spot.
- **aggTrades** (cada operación ejecutada): ~6,8 GB en 1.315 ficheros, para estudiar el tape tick a tick.
- **Posicionamiento**: open interest, funding, basis, ratios long/short y liquidaciones (Binance y Coinalyze).
- **On-chain** (Dune, BSC): compradores únicos en DEX, flujos hacia exchanges y perfil de PnL de wallets.
- **Contexto**: categorías de CoinGecko (narrativa), anuncios de Binance (listados y airdrops) y fechas de listado.

## Método de investigación

- **Split temporal fijo:** periodo A (09-2023 a 07-2025) para construir y periodo B (08-2025 en adelante) para validar. Una idea solo asciende si mejora **en los dos**; se juzga por consistencia entre periodos, no por la mejor celda de una rejilla.
- **Pre-registro:** cada hipótesis y su predicción se escriben antes de mirar los datos. Las hipótesis nuevas se testean solo sobre eventos posteriores al 04-09-2026; los 1.011 eventos históricos se dan por agotados para no sobreajustar.
- **Sin lookahead:** todas las features se calculan con información disponible en el momento de la señal. Por ejemplo, la amplitud multi-exchange se reconstruye a t0 con las velas históricas de cada exchange, no con el dato de hoy.
- **Ejecución realista:** entrada al open de la vela siguiente, costes del 0,3 % ida y vuelta, simulación path-dependent con velas 1h (qué toca antes, stop o TP) y deduplicación de eventos.
- **Estadística:** casos-control emparejados con Wilcoxon, Mann-Whitney entre ganadoras y basura, regresión logística, gradient boosting y random forest entrenados en A y evaluados en B (AUC), Monte Carlo de 2.000 secuencias para dimensionar posición y apalancamiento, y walk-forward para la selección de wallets on-chain.
- **Control de sesgos:** sesgo de supervivencia declarado en cada test (los pares deslistados no están en el universo) e indicando a favor de qué tesis empuja.

## Resultados

**Techo de predicción.** Separar igniciones ganadoras (+40 % en 7 días) de basura con datos de
exchange llega a AUC 0,620 con logística, 0,642 con GBM y 0,655 con random forest, entrenando
en A y evaluando en B. Que todos los modelos converjan indica que **el límite es de información,
no de modelo**.

**Carteras con validación en ambos periodos** (en espera por escala, no operables con cuenta pequeña):

| Estrategia | Periodo A | Periodo B |
|---|---|---|
| **Cartera corta market-neutral** de altcoins, 15-27 posiciones simultáneas con cobertura en BTC y rebalanceo diario (reglas en el repo privado) | +38,3 %, Sharpe 0,66, maxDD −33 % | +17,8 %, Sharpe 0,76, maxDD −12 % |
| **Cash-and-carry** delta-neutral (largo spot + corto perp de la misma moneda, top 10 por funding) | +7,3 %/año, maxDD −1,3 % | +12,2 %/año, maxDD −0,2 % |

El cash-and-carry no tiene pata de precio en el backtest: su único riesgo modelado es que el
funding se gire.

**Cortos de evento.** Nueve variantes juzgadas. Solo sobrevive una (A: +1,21 % por operación,
PF 1,25, n = 320; B: +4,38 %, PF 2,93, n = 97), con la advertencia de que está inflada por la
selección. Está en papel y sus reglas quedan en el repo privado.

**En vivo (papel, desde el 03-09-2026).** El detector de igniciones reproduce la tasa del
backtest (29 %), pero el libro combinado está en **−10,7 %** y suspendido por las reglas del
challenge: el stop del 8 % mata operaciones que después habrían sido ganadoras. El libro de
solo cortos va en −3,6 % con 12 operaciones. Es el tipo de resultado que este proyecto está
diseñado para detectar antes de arriesgar dinero.

**62 hipótesis descartadas**, documentadas en [`PENDIENTES.md`](PENDIENTES.md) para no
reabrirlas: salidas gestionadas (breakeven, trailing, parciales), entradas en retroceso y con
orden límite, apalancamiento > 2×, filtros de régimen de BTC, smart money on-chain, anuncios
de Binance, huella de TWAP en el tape, consenso de 8 fórmulas, entre otras.

## Stack

Python · pandas · NumPy · SciPy · scikit-learn · requests · websocket-client · Dune (SQL) ·
HTML generado para el panel · Programador de tareas de Windows para las grabadoras.

## Decisiones de ingeniería

- **Clientes HTTP** con sesión reutilizada, reintentos y respeto de `Retry-After` y de los límites de cada API (por ejemplo, 40 llamadas/min en Coinalyze).
- **Caché local por fuente** (velas 1h/15m, Binance, Coinalyze, resultados del libro) para que los estudios se repitan sin volver a descargar.
- **Lectura de aggTrades** directamente desde el zip, en streaming y cargando solo las columnas necesarias, para trabajar con gigas de ticks en un portátil.
- **Grabadoras desacopladas** del análisis: el websocket de liquidaciones escribe JSONL diario y un watchdog lo relanza si cae.

## Limitaciones y siguientes pasos

- **Ejecución secuencial.** El escáner tarda 2-4 minutos en recorrer el universo porque las peticiones van una a una. Es trabajo limitado por E/S: con `asyncio`/`aiohttp` o un pool de hilos, dentro de los límites de la API, bajaría a segundos. El parseo de aggTrades es CPU y se paralelizaría por fichero con `multiprocessing`, ya que el GIL impide hacerlo con hilos.
- **Memoria y formato.** Los datos viven en CSV y zip. Pasar a Parquet con `float32` y tipos categóricos reduciría memoria y tiempo de carga.
- **Sin tests automatizados.** La validación es estadística (A/B, pre-registro), no unitaria. El simulador de ejecución merece tests de casos límite: stop y TP en la misma vela, huecos de datos.
- **Scripts planos.** El código está organizado como cuaderno de investigación: un script por hipótesis. El núcleo reutilizado (detección, simulación de trades, carga de datos) se extraería a un paquete.

## Uso

```bash
python ignition_scan.py             # escanea todo el universo (~2-4 min)
python ignition_scan.py --horas 24  # igniciones de las últimas 24 h
python revision.py --dias 7         # resultado real de las señales de la última semana
python libro.py                     # actualiza los libros y genera libro.html
```
